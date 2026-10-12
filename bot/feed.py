"""DART 공시를 날짜로 통째로 받아 우리 종목만 걸러낸다.

388종목을 하나씩 조회하면 폴링 한 번에 388건이다. 20분마다 돌리면 하루
28,000건으로 DART 한도(20,000건)를 넘긴다. 날짜로 받으면 하루 700여 건을
8번에 받아, 폴링 한 번에 8건이면 끝난다.
"""
from __future__ import annotations

from datetime import date, timedelta

from .sources import dart

from .classify import classify
from .config import universe

PAGE = 100
MAX_PAGES = 30               # 하루 3,000건이면 충분하다. 폭주 시 안전장치.


def fetch_day(day: str) -> list[dict]:
    """하루치 공시 전부. day 는 YYYYMMDD."""
    out: list[dict] = []
    page = 1
    while page <= MAX_PAGES:
        try:
            d = dart._get("list.json", bgn_de=day, end_de=day,
                          page_no=page, page_count=PAGE)
        except dart.DartError as exc:
            if "013" in str(exc) or "없습니다" in str(exc):
                break
            raise
        rows = d.get("list") or []
        out += rows
        total_page = int(d.get("total_page") or 1)
        if page >= total_page:
            break
        page += 1
    return out


def collect(days: int = 1) -> list[dict]:
    """최근 N일 공시 중 우리 종목의 '중요' 공시만.

    주말·휴일에는 공시가 없다. days 를 늘려도 호출만 늘고 소득이 없으므로
    기본 1일로 두고, 월요일 아침처럼 공백이 있을 때만 늘려 쓴다.
    """
    uni = universe()
    out: list[dict] = []
    for n in range(days):
        day = (date.today() - timedelta(days=n)).strftime("%Y%m%d")
        for r in fetch_day(day):
            code = (r.get("stock_code") or "").strip()
            if code not in uni:
                continue
            cat = classify(r.get("report_nm") or "")
            if cat is None:
                continue
            name, icon = cat
            out.append({
                "ticker": code,
                "name": uni[code],
                "corp_name": (r.get("corp_name") or "").strip(),
                "title": (r.get("report_nm") or "").strip(),
                "category": name,
                "icon": icon,
                "rcept_no": r.get("rcept_no") or "",
                "rcept_dt": r.get("rcept_dt") or "",
                "url": "https://dart.fss.or.kr/dsaf001/main.do?rcpNo="
                       + (r.get("rcept_no") or ""),
            })
    return out
