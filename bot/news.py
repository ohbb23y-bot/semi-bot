"""반도체 관련 기사.

388종목을 하나씩 돌면 폴링 한 번에 388번 요청이라 네이버가 막는다.
대표 종목 몇 개의 기사만 받아 합치고, 제목에 반도체 키워드가 들어간 것만
남긴다. 공시가 난 종목은 그 종목 기사를 따로 붙인다 — 공시와 기사를 같이
봐야 무슨 일인지 읽힌다.
"""
from __future__ import annotations

import html
import re

from .sources import naver

# 업황을 끌고 가는 대표 종목. 이들 기사에 섹터 뉴스가 대부분 걸린다.
BELLWETHER = ["005930", "000660", "042700", "000990", "036930"]

KEYWORD = re.compile(
    r"반도체|메모리|HBM|DRAM|D램|낸드|NAND|파운드리|foundry|웨이퍼|노광"
    r"|패키징|후공정|전공정|TSMC|엔비디아|NVIDIA|AI\s*칩|소부장|감산|증설"
    r"|가동률|수출|관세", re.I)


def _dedup(items: list[dict]) -> list[dict]:
    seen, out = set(), []
    for it in items:
        key = (it.get("title") or "").strip()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out


def sector(limit: int = 12) -> list[dict]:
    """대표 종목 기사 중 반도체 키워드가 걸린 것."""
    pool: list[dict] = []
    for t in BELLWETHER:
        try:
            pool += naver.news(t, limit=15)
        except Exception:                              # noqa: BLE001
            continue                                   # 한 종목 실패로 멈추지 않는다
    pool = [n for n in _dedup(pool) if KEYWORD.search(n.get("title") or "")]
    pool.sort(key=lambda x: x.get("datetime") or "", reverse=True)
    return pool[:limit]


def for_ticker(ticker: str, name: str = "", limit: int = 2) -> list[dict]:
    """그 종목 기사. 제목에 회사 이름이 든 것만 남긴다.

    네이버 '종목 뉴스'에는 시황·테마 기사가 섞여 들어온다. 그대로 붙이면
    주연테크 수주 공시 밑에 '시총 미달 상폐 유예' 같은 기사가 달린다.
    공시를 읽는 데 보탬이 안 되고, 오히려 둘을 엮어 오해하게 만든다.
    """
    try:
        rows = naver.news(ticker, limit=12)
    except Exception:                                  # noqa: BLE001
        return []
    if not name:
        return rows[:limit]
    # 괄호·공백을 떼고 비교한다 ("윤성에프앤씨" vs "윤성 에프앤씨")
    key = re.sub(r"[\s()\[\]]", "", name)
    out = [r for r in rows
           if key and key in re.sub(r"[\s()\[\]]", "", r.get("title") or "")]
    return out[:limit]


# ── 최신성 · 중요도 ────────────────────────────────────────────

def age_min(item: dict) -> float | None:
    """기사가 나온 지 몇 분 됐나. 시각을 못 읽으면 None."""
    from datetime import datetime
    from .config import kst_now
    try:
        t = datetime.strptime((item.get("datetime") or "")[:16], "%Y-%m-%d %H:%M")
    except ValueError:
        return None
    return (kst_now() - t).total_seconds() / 60


def fresh(items: list[dict], minutes: int) -> list[dict]:
    """최근 N분 이내 기사만. 시각을 못 읽은 것은 믿을 수 없어 뺀다."""
    out = []
    for n in items:
        a = age_min(n)
        if a is not None and -5 <= a <= minutes:      # 시계 오차 5분은 봐준다
            out.append(n)
    return out


# 돈과 업황에 직접 닿는 말일수록 높게. 제목만 보고 가린다.
_POS = [
    (re.compile(r"수주|공급\s*계약|납품|계약\s*체결|낙찰"), 4),
    (re.compile(r"증설|신규\s*투자|설비\s*투자|CAPEX|팹|신공장|라인\s*(구축|증설)", re.I), 3),
    (re.compile(r"사상\s*최대|최대\s*실적|어닝|영업이익|영업익|잠정\s*실적"), 3),
    (re.compile(r"인수|M&A|합병|지분\s*(취득|매입|매각)|자사주"), 3),
    (re.compile(r"감산|증산|가격\s*(인상|상승|하락)|공급\s*(부족|과잉)|재고"), 3),
    (re.compile(r"HBM|DRAM|D램|낸드|NAND|파운드리|TSMC|엔비디아|NVIDIA", re.I), 2),
    (re.compile(r"수출|관세|규제|제재|보조금"), 2),
    (re.compile(r"삼성전자|SK하이닉스|하이닉스"), 1),
]
# 시황·상품·잡담은 업황 판단에 보탬이 안 된다.
_NEG = re.compile(
    r"ETF|리밸런싱|목표가|투자의견|추천|\[포토\]|\[사진\]|부고|인사|오늘의|"
    r"마감\s*시황|장중|주간\s*전망|일정|경제브리핑|\[속보\]\s*코스피", re.I)


def score(title: str, names: "set[str] | None" = None) -> int:
    t = title or ""
    s = sum(w for pat, w in _POS if pat.search(t))
    if _NEG.search(t):
        s -= 4
    if names and any(nm in t for nm in names):
        s += 2                                        # 우리 종목이 직접 나온다
    return s


def _gram(s: str) -> set[str]:
    s = re.sub(r"[^0-9A-Za-z가-힣]", "", html.unescape(s or ""))
    return {s[i:i + 2] for i in range(len(s) - 1)}


def seen_filter(items: list[dict], seen_titles: list[str], thresh: float = 0.45) -> list[dict]:
    """이미 보낸 기사와 같거나 거의 같은 내용이면 뺀다.

    제목이 글자 그대로 같을 때만 걸러서는, 같은 소식을 제목만 바꿔 다시 낸 기사와
    다른 언론사의 같은 보도가 계속 올라간다. 두 글자씩 끊어 겹치는 비율로 비교한다.
    """
    seen_g = [g for g in (_gram(t) for t in seen_titles) if g]
    out = []
    for it in items:
        g = _gram(it.get("title") or "")
        if not g:
            continue
        if any(len(g & s) / len(g | s) > thresh for s in seen_g):
            continue
        out.append(it)
    return out


def pick(items: list[dict], n: int = 4, min_score: int = 3,
         names: "set[str] | None" = None) -> list[dict]:
    """중요한 기사만 최대 n 개. 같은 내용을 다룬 기사는 하나만 남긴다."""
    ranked = sorted(items, key=lambda x: (score(x.get("title"), names),
                                          x.get("datetime") or ""), reverse=True)
    out: list[dict] = []
    for it in ranked:
        if score(it.get("title"), names) < min_score:
            break
        g = _gram(it.get("title"))
        if any(len(g & _gram(o["title"])) / max(1, len(g | _gram(o["title"]))) > 0.45
               for o in out):
            continue
        out.append(it)
        if len(out) >= n:
            break
    return out
