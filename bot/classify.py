"""공시 제목을 보고 중요도를 가른다.

DART 는 하루 700건 넘게 쏟아진다. 그중 대부분은 '기타시장안내' 같은
형식 공시다. 전부 보내면 알림이 소음이 되고, 정작 수주 공시를 놓친다.

규칙은 제목 문자열만 본다. 원문을 받아 읽으면 종목당 수 MB 라 폴링마다
쓸 수 없다. 제목만으로도 분류는 충분히 갈린다.
"""
from __future__ import annotations

import re

# 먼저 거르는 소음. 아래 CATEGORIES 보다 우선한다.
NOISE = re.compile(
    r"기타시장안내|투자설명서|증권발행실적보고서|일괄신고추가서류"
    r"|파생결합증권|발행조건확정|예탁원|호가|매매거래정지|거래재개"
    r"|주식분포현황|대차대조|사업보고서등제출기한연장"
)

# (분류, 아이콘, 패턴). 위에서부터 먼저 맞는 것을 쓴다.
CATEGORIES: list[tuple[str, str, re.Pattern]] = [
    ("수주", "📦", re.compile(
        r"단일판매|공급계약|수주|납품계약")),
    # 가압류·상장폐지 같은 위험은 '투자판단관련주요경영사항' 제목 아래에도 숨어 온다.
    # 증설 패턴이 먼저 잡아 버리지 않게 맨 앞에 둔다.
    ("위험신호", "⚠️", re.compile(
        r"가압류|가처분|감사의견|상장폐지|관리종목|소송|횡령|배임|회생|파산|불성실공시")),
    # 풍문·보도 해명과 조회공시 답변. '미확정'이어도 시장이 곧바로 반응하는 공시다.
    ("해명", "🗣", re.compile(r"풍문|조회공시|보도에\s*대한\s*해명")),
    ("증설·CAPEX", "🏭", re.compile(
        r"신규시설투자|시설투자|유형자산.*(취득|양수)|생산설비|공장\s*(신설|증설)"
        r"|투자판단관련주요경영사항")),
    # 5% 대량보유와 최대주주 변경은 지배구조가 흔들리는 신호다.
    ("지분변동", "🧿", re.compile(
        r"대량보유상황보고|주식등의대량|최대주주.*변경|의결권")),
    ("자금조달", "💰", re.compile(
        r"유상증자|무상증자|전환사채|신주인수권부사채|교환사채|자금조달"
        r"|차입금|채무보증")),
    ("실적", "📊", re.compile(
        r"영업\(잠정\)|잠정실적|매출액또는손익구조|결산실적|실적공시")),
    # 기업설명회(IR) 개최 — 실적 직후나 NDR 전에 나온다. 일정이 곧 재료다.
    ("IR", "🎤", re.compile(r"기업설명회|IR\s*개최")),
    ("주주환원", "🎁", re.compile(
        r"현금.?현물배당|자기주식.*(취득|소각|처분)|배당")),
    ("지배구조", "🔀", re.compile(
        r"합병|분할|영업양수|영업양도|주식교환|포괄적")),
    # 임원·주요주주 소유상황은 스톡옵션 행사 같은 일상 신고가 대부분이라
    # 건수가 압도적이다. 위 분류들과 섞으면 수주 공시가 묻힌다. 맨 뒤로
    # 보내고, --no-insider 로 끌 수 있게 한다.
    ("임원지분", "👤", re.compile(r"임원.*주요주주.*소유상황")),
]

# 알림 우선순위. 숫자가 작을수록 먼저 보여준다.
ORDER = {name: i for i, (name, _, _) in enumerate(CATEGORIES)}


def classify(report_nm: str) -> tuple[str, str] | None:
    """(분류, 아이콘). 중요하지 않으면 None."""
    title = (report_nm or "").strip()
    if not title or NOISE.search(title):
        return None
    for name, icon, pat in CATEGORIES:
        if pat.search(title):
            return name, icon
    return None


def sort_key(item: dict) -> tuple:
    """분류 우선순위 → 최신순."""
    return (ORDER.get(item.get("category", ""), 99),
            -int(item.get("rcept_no") or 0))
