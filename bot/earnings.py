"""영업(잠정)실적 공시 요약: 이번 분기 · 예상치 대비 · 최근 분기 추이.

이번 분기 숫자는 공시 본문에서, 예상치(컨센서스)와 지난 분기 실적은 네이버
분기 재무에서 가져온다. 네이버 숫자는 연결 기준이라 공시가 별도 기준이면
섞지 않고 공시 숫자만 보여준다.

예상치는 '이번 분기가 아직 컨센서스로 남아 있을 때'만 쓴다. 네이버가 이미 실적으로
갱신했다면 예상치가 사라지므로, 그때는 예상치 줄을 생략한다.
"""
from __future__ import annotations

import re

from .sources import naver

from .summary import _idx, _num
from .telegram import esc

ROWS = (("매출액", "매출"), ("영업이익", "영업이익"), ("당기순이익", "순이익"))

# 공시 단위 → 억원
_TO_EOK = {"조원": 1e4, "억원": 1.0, "백만원": 1e-2, "천원": 1e-5, "원": 1e-8}


def _unit(c: list[str]) -> tuple[str, float]:
    cell = next((x for x in c if x.startswith("단위 :")), "")
    m = re.search(r"단위\s*:\s*([^,\s]+)", cell)
    u = m.group(1) if m else ""
    return u, _TO_EOK.get(u, 0.0)


def _period_key(c: list[str]) -> str:
    """'당기실적 2026-07-01 ~ 2026-09-30' → '202609'."""
    i = _idx(c, "당기실적")
    if i < 0 or i + 3 >= len(c):
        return ""
    m = re.match(r"(\d{4})-(\d{2})-\d{2}$", c[i + 3])
    return f"{m.group(1)}{m.group(2)}" if m else ""


def _label(key: str) -> str:
    return f"{key[:4]}.{(int(key[4:6]) + 2) // 3}Q"


def fmt(v: float | None) -> str:
    """억원 값을 읽기 좋게. 10만억 이상은 조 단위."""
    if v is None:
        return "-"
    if abs(v) >= 100000:
        return f"{v / 10000:,.1f}조"
    return f"{v:,.0f}억"


def _diff(actual: float | None, est: float | None) -> str:
    if actual is None or not est:
        return ""
    return f" ({(actual / est - 1) * 100:+.1f}%)" if est > 0 else ""


def naver_quarters(ticker: str) -> tuple[dict[str, dict], str]:
    """({분기키: {'매출액':v,...,'est':bool}}, 예상치 분기키). 실패하면 ({}, '')."""
    try:
        r = naver._c().get(f"{naver.M_BASE}/stock/{ticker}/finance/quarter")
        r.raise_for_status()
        info = r.json()["financeInfo"]
    except Exception:                                      # noqa: BLE001
        return {}, ""
    out: dict[str, dict] = {}
    est_key = ""
    for t in info.get("trTitleList") or []:
        out[t["key"]] = {"est": t.get("isConsensus") == "Y"}
        if t.get("isConsensus") == "Y":
            est_key = t["key"]
    for row in info.get("rowList") or []:
        if row.get("title") not in dict(ROWS):
            continue
        for k, cell in (row.get("columns") or {}).items():
            if k in out:
                out[k][row["title"]] = _num(cell.get("value"))
    return out, est_key


def lines(ticker: str, title: str, c: list[str]) -> list[str]:
    """요약 줄(HTML). 읽지 못하면 빈 목록."""
    unit, mul = _unit(c)
    key = _period_key(c)
    if not mul or not key:
        return []
    base = _idx(c, "1. 연결실적내용")
    if base < 0:
        base = _idx(c, "2. 별도실적내용")
    base = max(base, 0)

    cur: dict[str, float | None] = {}
    yoy: dict[str, float | None] = {}
    for lb, _ in ROWS:
        i = _idx(c, lb, base)
        if i < 0 or c[i + 1:i + 2] != ["당해실적"]:
            continue
        v = c[i + 2:i + 9]
        if len(v) < 6:
            continue
        n = _num(v[0])
        cur[lb] = n * mul if n is not None else None
        yoy[lb] = _num(v[5])
    if not any(cur.values()):
        return []

    consolidated = "별도" not in title
    quarters, est_key = naver_quarters(ticker) if consolidated else ({}, "")
    est = quarters.get(est_key, {}) if est_key == key else {}

    out = [f"<b>{_label(key)}</b> 잠정 · {'연결' if consolidated else '별도'}"]
    for lb, short in ROWS:
        if lb not in cur:
            continue
        s = f"{short} <b>{fmt(cur[lb])}</b>" if cur[lb] is not None else f"{short} <i>미공시</i>"
        if est.get(lb) is not None:
            s += f" · 예상 {fmt(est[lb])}{_diff(cur[lb], est[lb])}"
        if yoy.get(lb) is not None:
            s += f" · 전년 {yoy[lb]:+.1f}%"
        out.append(s)

    # 최근 추이: 이번 분기(공시값) + 앞선 실적 분기 4개
    past = sorted((k for k, v in quarters.items() if not v["est"] and k < key), reverse=True)[:4]
    if past:
        out.append("<i>추이  매출 / 영업이익 / 순이익</i>")
        out.append(f"{_label(key)}  " + " / ".join(fmt(cur.get(lb)) for lb, _ in ROWS))
        for k in past:
            q = quarters[k]
            out.append(f"{_label(k)}  " + " / ".join(fmt(q.get(lb)) for lb, _ in ROWS))
    return out
