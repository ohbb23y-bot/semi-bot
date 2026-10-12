"""단일판매·공급계약 공시 본문에서 계약 규모를 뽑는다.

공시 본문에 '계약금액 총액(원)', '최근 매출액(원)', '매출액 대비(%)' 가
이미 들어 있다. 제목만 보내면 계약이 큰지 작은지 알 수 없어, 본문을 한 번
받아 읽는다. 수주 공시는 하루 몇 건이라 DART 호출 부담이 없다.

정정 공시는 맨 앞에 '정정 전/후' 표가 붙고 그 뒤에 전체 본문이 다시 나온다.
그래서 같은 라벨이 둘 이상이면 **마지막** 것을 쓴다.
"""
from __future__ import annotations

import io
import re
import zipfile

from .config import DART_API_KEY
from .sources.dart import BASE
from .sources.http import get_with_retry

_CELL_END = re.compile(r"</(?:TD|TH|TE|TU|P|TR)\s*>", re.I)
_TAG = re.compile(r"<[^>]+>")


def _cells(xml: str) -> list[str]:
    s = _CELL_END.sub("\x00", xml)
    s = _TAG.sub("", s)
    s = (s.replace("&nbsp;", " ").replace("&amp;", "&")
          .replace("&lt;", "<").replace("&gt;", ">"))
    return [re.sub(r"\s+", " ", c).strip() for c in s.split("\x00")
            if c.strip()]


def _after(cells: list[str], *labels: str) -> str:
    """라벨 바로 다음 칸의 값. 같은 라벨이 여럿이면 마지막 것.

    서식마다 라벨 표기가 조금씩 다르다('매출액 대비(%)' / '매출액대비(%)'). 공백은 무시하고,
    여러 표기를 주면 앞에서부터 처음 찾아지는 것을 쓴다.
    """
    for label in labels:
        key = label.replace(" ", "")
        hit = ""
        for i, c in enumerate(cells[:-1]):
            if c == label or c.replace(" ", "") == key:
                hit = cells[i + 1]
        if hit:
            return hit
    return ""


def _num(s: str) -> float | None:
    s = (s or "").replace(",", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


def parse_cells(cells: list[str]) -> dict | None:
    amount = _num(_after(cells, "계약금액 총액(원)", "계약금액(원)", "확정 계약금액", "계약금액 총액"))
    other0 = _after(cells, "3. 계약상대방", "3. 계약상대")
    if amount is None and not other0.strip("-"):
        return None                            # 금액도 상대도 없으면 읽을 게 없다
    sales = _num(_after(cells, "최근 매출액(원)", "최근매출액(원)"))
    pct = _num(_after(cells, "매출액 대비(%)", "매출액대비(%)"))
    if pct is None and sales and amount is not None:
        pct = amount / sales * 100
    other = _after(cells, "3. 계약상대방", "3. 계약상대")
    item = _after(cells, "1. 판매ㆍ공급계약 내용", "- 체결계약명", "체결계약명")
    return {
        "item": "" if item == "-" else item,   # 무엇을 공급하나
        "amount": amount,                      # 원
        "sales": sales,                        # 원, 최근 사업연도 매출
        "pct": pct,                            # 매출액 대비 %
        "party": "" if other in ("", "-") else other,
        "end": _after(cells, "종료일"),
    }


def fetch(rcept_no: str) -> dict | None:
    """접수번호로 계약 규모를 읽는다. 아직 원문이 없거나 형식이 다르면 None."""
    try:
        r = get_with_retry("dart", BASE + "/document.xml",
                           params={"crtfc_key": DART_API_KEY,
                                   "rcept_no": rcept_no}, timeout=60)
    except Exception:                                  # noqa: BLE001
        return None
    if r.content[:2] != b"PK":                         # 014: 원문 아직 없음
        return None
    try:
        with zipfile.ZipFile(io.BytesIO(r.content)) as z:
            xml = z.read(z.namelist()[0]).decode("utf-8", "ignore")
    except Exception:                                  # noqa: BLE001
        return None
    return parse_cells(_cells(xml))


def eok(won: float | None) -> str:
    """원 → '76.7억원' / '1,234억원' / '0.5억원'."""
    if won is None:
        return "?"
    v = won / 1e8
    return f"{v:,.0f}억원" if v >= 100 else f"{v:,.1f}억원"


def line(info: dict) -> str:
    """텔레그램에 붙일 한 줄 (HTML)."""
    # 조건부 계약이거나 비공개라 금액이 '-' 인 공시도 있다
    bits = [f"💵 <b>{eok(info['amount'])}</b>" if info.get("amount") is not None
            else "💵 <i>금액 미공개</i>"]
    if info.get("pct") is not None:
        s = f"최근 매출 대비 <b>{info['pct']:.1f}%</b>"
        if info.get("sales"):
            s += f" (매출 {eok(info['sales'])})"
        bits.append(s)
    if info.get("end"):
        bits.append(f"~{info['end']}")
    return " · ".join(bits)


# ── IR 개최 공시 ────────────────────────────────────────────────

_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TIME = re.compile(r"^\d{1,2}:\d{2}$")


def ir_info(cells: list[str]) -> dict | None:
    """기업설명회 개최 공시에서 일시·개최목적을 뽑는다.

    서식이 두 가지다. 정식 서식은 '일시 → 날짜 → 시각', 공정공시 서식은
    '개최일자 / 개최시각'. 목적은 '3. 개최목적' 또는 '개최목적' 다음 칸.
    """
    date = time = ""
    for i, c in enumerate(cells[:-1]):
        if c in ("일시", "개최일자", "개최일시") and not date:
            for nxt in cells[i + 1:i + 4]:
                if _DATE.match(nxt):
                    date = nxt
                elif _TIME.match(nxt) and not time:
                    time = nxt
                if date and time:
                    break
        if c == "개최시각" and not time and _TIME.match(cells[i + 1]):
            time = cells[i + 1]
    if not date and "행사일" in cells:                  # 거래소 서식: 머리글 뒤에 값이 한꺼번에
        start = cells.index("행사일")
        for x in cells[start + 1:start + 14]:
            if _DATE.match(x) and not date:
                date = x
            elif _TIME.match(x) and not time:
                time = x
    purpose = (_after(cells, "3. 개최목적") or _after(cells, "개최목적")
               or _after(cells, "4. 실시목적"))
    method = (_after(cells, "4. 개최방법") or _after(cells, "개최방법")
              or _after(cells, "5. 실시방법"))
    if not (date or purpose):
        return None
    return {"date": date, "time": time,
            "purpose": "" if purpose == "-" else purpose,
            "method": "" if method == "-" else method}


def fetch_ir(rcept_no: str) -> dict | None:
    try:
        r = get_with_retry("dart", BASE + "/document.xml",
                           params={"crtfc_key": DART_API_KEY,
                                   "rcept_no": rcept_no}, timeout=60)
    except Exception:                                  # noqa: BLE001
        return None
    if r.content[:2] != b"PK":
        return None
    try:
        with zipfile.ZipFile(io.BytesIO(r.content)) as z:
            xml = z.read(z.namelist()[0]).decode("utf-8", "ignore")
    except Exception:                                  # noqa: BLE001
        return None
    return ir_info(_cells(xml))


def ir_line(info: dict) -> str:
    when = ""
    if info.get("date"):
        when = f"{info['date'][5:7]}/{info['date'][8:10]}"
        if info.get("time"):
            when += f" {info['time']}"
    bits = [b for b in (f"<b>{when}</b>" if when else "", info.get("purpose"),
                        info.get("method")) if b]
    return "📅 " + " · ".join(bits) if bits else ""
