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


def rank(items: list[dict], names: "set[str] | None" = None, min_score: int = 3) -> list[dict]:
    """중요도 점수가 기준 이상인 기사를 점수 높은 순으로. 같은 소식 걸러내기는 하지 않는다."""
    scored = [(score(x.get("title"), names), x.get("datetime") or "", x) for x in items]
    scored = [t for t in scored if t[0] >= min_score]
    scored.sort(key=lambda t: (t[0], t[1]), reverse=True)
    return [x for _, _, x in scored]


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


# ── 같은 사건 묶기 ─────────────────────────────────────────────
# 제목이 다르게 달려도 같은 소식을 다룬 기사가 많다(한 사건을 열 개 매체가 쓴다). 제목 글자가 아니라
# 제목·요약 소제목·본문 앞부분의 '단어 분포'가 얼마나 겹치는지로 같은 사건인지 본다.
import math
from collections import Counter

_ALIAS = {"삼전": "삼성전자", "하이닉스": "SK하이닉스", "닉스": "SK하이닉스", "하닉": "SK하이닉스",
          "SK하닉스": "SK하이닉스", "하닉스": "SK하이닉스", "삼전닉스": "삼성전자 SK하이닉스",
          "코스피지수": "코스피"}
_STOP = set("""반도체 전망 이번 올해 내년 관련 시장 기업 업체 수요 공급 증가 확대 실적 영향 가운데 대한 통해 위해
오늘 어제 지난 최근 이후 이상 이하 대비 기준 최대 최소 속보 단독 종합 시황 핫종목 이시각 코주부 개장시황 그리고 하지만
따르면 밝혔다 했다 한다 있다 된다 되는 이다 라고 에서 으로 에게 보다 까지 부터 처럼 만큼 정도 가량 사이 동안 한편 또한
기자 연합뉴스 뉴스1 뉴시스 서울 지난달 이날 전날 이어 가장 매우 다시 모두 함께 현재 전체""".split())
_PART = "은는이가을를의에도로과와"


def story_tokens(text: str) -> list[str]:
    out = []
    for w in re.findall(r"[0-9A-Za-z가-힣%.]{2,}", html.unescape(text or "")):
        w = w.strip(".")
        if len(w) >= 3 and w[-1] in _PART and not w[-1].isdigit():
            w = w[:-1]
        w = _ALIAS.get(w, w)
        for x in w.split():
            if len(x) >= 2 and x not in _STOP:
                out.append(x)
    return out


def story_sig(title: str, heads: list[str], body: str) -> dict[str, int]:
    """기사의 단어 분포. 제목은 두 번 센다."""
    text = (title + " ") * 2 + " ".join(heads) + " " + (body or "")[:400]
    return dict(Counter(story_tokens(text)))


def _vec(sig: dict[str, int]) -> dict[str, float]:
    return {t: 1 + math.log(c) for t, c in sig.items()}


def story_cos(a: dict[str, int], b: dict[str, int]) -> float:
    va, vb = _vec(a), _vec(b)
    num = sum(va[t] * vb[t] for t in va.keys() & vb.keys())
    da = math.sqrt(sum(x * x for x in va.values()))
    db = math.sqrt(sum(x * x for x in vb.values()))
    return num / (da * db) if da and db else 0.0


def cluster(items: list[dict], thr: float = 0.30) -> list[list[dict]]:
    """같은 사건끼리 묶는다. items 는 중요한 순으로 정렬돼 있고, 각 묶음의 첫 기사가 대표다."""
    groups: list[list[dict]] = []
    for n in items:
        best, bs = None, 0.0
        for g in groups:
            s = max(story_cos(n["sig"], m["sig"]) for m in g)
            if s > bs:
                best, bs = g, s
        if best is not None and bs >= thr:
            best.append(n)
        else:
            groups.append([n])
    return groups


def sig_keep(sig: dict[str, int], k: int = 30) -> list[str]:
    """상태 파일에 남길 요약: 많이 나온 단어 k 개."""
    return [t for t, _ in Counter(sig).most_common(k)]


def seen_story(sig: dict[str, int], stored: list, thr: float = 0.22) -> bool:
    """이미 보낸 소식과 같은 사건인가. stored 는 sig_keep 목록의 목록(단어 집합끼리 비교)."""
    a = set(sig_keep(sig))
    if not a:
        return False
    for ent in stored or []:
        b = set(ent.get("w") or ent) if isinstance(ent, dict) else set(ent)
        if b and len(a & b) / math.sqrt(len(a) * len(b)) >= thr:
            return True
    return False
