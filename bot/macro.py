"""반도체 업황 지표 (한국은행 ECOS, 월간).

DRAM 고정거래가격은 TrendForce 같은 유료 자료라 넣지 못한다. 대신 한은이
매달 내는 세 지수로 사이클을 읽는다. 셋을 같이 봐야 의미가 산다.

    수출금액지수 = 수출물량지수 × 수출물가지수  (대략)

금액만 오르면 가격 때문인지 물량 때문인지 알 수 없다. 물량은 느는데
가격이 빠지면 공급 과잉, 둘 다 오르면 업턴이다.
"""
from __future__ import annotations

import os

import truststore
truststore.inject_into_ssl()
import httpx
from dotenv import load_dotenv

from .config import ROOT

load_dotenv(ROOT / ".env")

KEY = (os.getenv("ECOS_API_KEY") or "").strip()
BASE = "https://ecos.bok.or.kr/api"
_cli = httpx.Client(timeout=60)

# (이름, 통계표, 항목, 단위설명)
SERIES = [
    ("반도체 수출금액", "403Y001", "30911AA", "2020=100"),
    ("반도체 수출물량", "403Y002", "30911AA", "2020=100"),
    ("반도체 수출물가", "402Y014", "30911AA", "2020=100"),
]


def _fetch(code: str, item: str, n: int = 26) -> dict[str, float]:
    """최근 n개월. 키가 없으면 빈 dict 를 돌려주고 호출부가 건너뛴다."""
    if not KEY:
        return {}
    from datetime import date
    today = date.today()
    end = f"{today.year}{today.month:02d}"
    y, m = today.year, today.month - n
    while m <= 0:
        y, m = y - 1, m + 12
    start = f"{y}{m:02d}"
    url = (f"{BASE}/StatisticSearch/{KEY}/json/kr/1/200/{code}/M/"
           f"{start}/{end}/{item}")
    try:
        d = _cli.get(url).json()
    except Exception:                                   # noqa: BLE001
        return {}
    node = d.get("StatisticSearch")
    if not node:
        return {}
    return {r["TIME"]: float(r["DATA_VALUE"])
            for r in node.get("row") or []
            if r.get("DATA_VALUE") not in (None, "", "-")}


def snapshot() -> list[dict]:
    """각 계열의 최신값 · 전월비 · 전년동월비."""
    out = []
    for name, code, item, unit in SERIES:
        d = _fetch(code, item)
        if not d:
            out.append({"name": name, "error": "자료 없음"})
            continue
        keys = sorted(d)
        last = keys[-1]
        prev = keys[-2] if len(keys) > 1 else None
        yago = last[:4] and f"{int(last[:4]) - 1}{last[4:]}"
        out.append({
            "name": name,
            "unit": unit,
            "period": f"{last[:4]}-{last[4:]}",
            "value": round(d[last], 1),
            "mom": round((d[last] / d[prev] - 1) * 100, 1) if prev and d.get(prev) else None,
            "yoy": round((d[last] / d[yago] - 1) * 100, 1) if d.get(yago) else None,
        })
    return out
