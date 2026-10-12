"""네이버 금융 — 뉴스 · 전종목 시세 · 일봉.

데일리 리포트의 등락, 기사 수집, 실적 공시의 예상치·분기 추이에 쓴다.
같은 요청이 몇 분 안에 반복되므로 간단한 메모리 캐시를 둔다.
"""
from __future__ import annotations

import json
import re
import time
from typing import Any

from .http import client

M_BASE = "https://m.stock.naver.com/api"
API_BASE = "https://api.finance.naver.com"
HEADERS = {"Referer": "https://m.stock.naver.com/"}

TTL_NEWS = 120          # 초
TTL_SNAPSHOT = 300
TTL_PRICE = 300

_cache: dict[str, tuple[float, Any]] = {}


def _cget(key: str, ttl: float):
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    return None


def _cput(key: str, value: Any) -> None:
    _cache[key] = (time.time(), value)


def _c():
    return client("naver", headers=HEADERS)


def _num(s: Any) -> float | None:
    if s is None:
        return None
    if isinstance(s, (int, float)):
        return float(s)
    t = str(s).strip().replace(",", "")
    if not t or t in ("-", "N/A"):
        return None
    t = re.sub(r"[배원%주]", "", t).strip()
    try:
        return float(t)
    except ValueError:
        return None


def ohlcv(ticker: str, start: str, end: str, timeframe: str = "day") -> list[dict]:
    """일/주/월 봉. start·end 는 YYYYMMDD."""
    key = "ohlcv:%s:%s:%s:%s" % (ticker, start, end, timeframe)
    hit = _cget(key, TTL_PRICE)
    if hit is not None:
        return hit
    r = _c().get(API_BASE + "/siseJson.naver",
                 params={"symbol": ticker, "requestType": "1", "startTime": start,
                         "endTime": end, "timeframe": timeframe}, timeout=40)
    r.raise_for_status()
    try:
        rows = json.loads(r.text.strip().replace("'", '"'))
    except json.JSONDecodeError:
        return []
    out = []
    for row in rows[1:]:
        if len(row) < 6:
            continue
        out.append({"date": str(row[0]), "open": row[1], "high": row[2],
                    "low": row[3], "close": row[4], "volume": row[5]})
    _cput(key, out)
    return out


def news(ticker: str, limit: int = 20) -> list[dict]:
    key = "news:%s:%d" % (ticker, limit)
    hit = _cget(key, TTL_NEWS)
    if hit is not None:
        return hit
    r = _c().get(M_BASE + "/news/stock/" + ticker,
                 params={"pageSize": limit, "page": 1})
    r.raise_for_status()
    out = []
    for group in r.json():
        for it in group.get("items") or []:
            dt = str(it.get("datetime") or "")
            pretty = dt
            if len(dt) >= 12:
                pretty = "%s-%s-%s %s:%s" % (dt[0:4], dt[4:6], dt[6:8], dt[8:10], dt[10:12])
            out.append({
                "title": it.get("title"),
                "press": it.get("officeName"),
                "datetime": pretty,
                "url": "https://n.news.naver.com/mnews/article/%s/%s"
                       % (it.get("officeId"), it.get("articleId")),
            })
    out.sort(key=lambda x: x["datetime"], reverse=True)
    out = out[:limit]
    _cput(key, out)
    return out


_MARKETS = ("KOSPI", "KOSDAQ")


def market_snapshot(market: str = "KOSPI", pages: int = 12,
                    page_size: int = 100) -> list[dict]:
    """시총 상위부터 훑는 전종목 시세."""
    key = "snapshot:%s:%d:%d" % (market, pages, page_size)
    hit = _cget(key, TTL_SNAPSHOT)
    if hit is not None:
        return hit
    out: list[dict] = []
    seen: set[str] = set()
    for page in range(1, pages + 1):
        try:
            r = _c().get(M_BASE + "/stocks/marketValue/" + market,
                         params={"page": page, "pageSize": page_size}, timeout=30)
            r.raise_for_status()
            stocks = r.json().get("stocks") or []
        except Exception:                               # noqa: BLE001
            break
        if not stocks:
            break
        for s in stocks:
            code = s.get("itemCode")
            if not code or code in seen:
                continue
            if s.get("stockEndType") != "stock":        # ETF·ETN·리츠 제외
                continue
            if not code.endswith("0"):                  # 우선주 제외
                continue
            seen.add(code)
            cap = _num(s.get("marketValueRaw"))
            close = _num(s.get("closePriceRaw")) or _num(s.get("closePrice"))
            out.append({
                "ticker": code,
                "name": s.get("stockName"),
                "market": market,
                "close": close,
                "market_cap": cap,
                "change_pct": _num(s.get("fluctuationsRatio")),
            })
    _cput(key, out)
    return out


def universe(pages: int = 12) -> list[dict]:
    rows: list[dict] = []
    for m in _MARKETS:
        rows.extend(market_snapshot(m, pages=pages))
    return rows
