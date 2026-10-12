"""DART OpenAPI — 공시 목록(list.json)과 공시 원문(document.xml).

DART 는 인증키당 하루 20,000건까지만 받고, 초당 호출이 많으면 응답 없이
커넥션을 끊는다. 그래서 초당 5건으로 묶고, 하루 18,000건을 넘기면 스스로 멈춘다.
"""
from __future__ import annotations

import threading
import time
from datetime import date
from typing import Any

from ..config import DART_API_KEY
from .http import get_with_retry

BASE = "https://opendart.fss.or.kr/api"
DAILY_BUDGET = 18000
MAX_CALLS_PER_SEC = 5.0


class DartError(RuntimeError):
    pass


_lock = threading.Lock()
_last_call = 0.0
_day = ""
_count = 0


def _throttle_and_count() -> None:
    """초당 호출 수를 묶고 오늘 호출 수를 센다 (프로세스가 떠 있는 동안)."""
    global _last_call, _day, _count
    with _lock:
        today = date.today().isoformat()
        if today != _day:
            _day, _count = today, 0
        if _count >= DAILY_BUDGET:
            raise DartError("오늘 DART 호출 한도(%d건)에 도달했습니다." % DAILY_BUDGET)
        wait = _last_call + 1.0 / MAX_CALLS_PER_SEC - time.time()
        if wait > 0:
            time.sleep(wait)
        _last_call = time.time()
        _count += 1


def calls_today() -> int:
    return _count


def _get(path: str, **params: Any) -> dict:
    if not DART_API_KEY:
        raise DartError("DART_API_KEY 가 설정되지 않았습니다.")
    params["crtfc_key"] = DART_API_KEY
    _throttle_and_count()
    try:
        r = get_with_retry("dart", BASE + "/" + path, params=params)
        r.raise_for_status()
    except Exception as exc:                            # noqa: BLE001
        raise DartError("DART 응답을 받지 못했습니다: " + str(exc)[:120]) from exc
    data = r.json()
    status = data.get("status")
    if status == "013":                                 # 조회 결과 없음 — 오류가 아니다
        return {"status": "013", "list": []}
    if status != "000":
        raise DartError("DART " + str(status) + ": " + str(data.get("message")))
    return data
