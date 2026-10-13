"""이미 보낸 공시를 기억한다.

GitHub Actions 는 실행마다 빈 디스크로 시작한다. 상태를 저장소에 커밋해야
다음 실행이 '어디까지 보냈는지'를 안다. 안 그러면 20분마다 같은 공시를
다시 보내 알림이 쓰레기통이 된다.

접수번호(rcept_no)는 YYYYMMDD + 일련번호라 시간순으로 증가한다. 최대값
하나만 들고 있으면 충분할 것 같지만, DART 는 같은 날 과거 번호를 뒤늦게
채워 넣기도 한다. 그래서 최근 접수번호 목록도 함께 들고 중복을 막는다.
"""
from __future__ import annotations

import json
from datetime import datetime

from .config import STATE_PATH

DIRTY = False            # 마지막 push 이후 상태가 바뀌었나 (gitsync 가 쓴다)
KEEP = 3000              # 최근 접수번호를 이만큼 기억한다 (며칠치)


def load() -> dict:
    if not STATE_PATH.exists():
        return {"last_rcept_no": "", "seen": [], "last_run": "",
                "last_daily": "", "pending": {},
                "news_sigs": [], "news_sent": []}
    try:
        d = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception:                                  # noqa: BLE001
        return {"last_rcept_no": "", "seen": [], "last_run": "",
                "last_daily": "", "pending": {},
                "news_sigs": [], "news_sent": []}
    d.setdefault("seen", [])
    d.setdefault("last_rcept_no", "")
    d.setdefault("last_run", "")
    d.setdefault("last_daily", "")
    d.setdefault("pending", {})
    d.setdefault("news_sigs", [])
    d.setdefault("news_sent", [])
    return d


def _core(d: dict) -> dict:
    return {k: v for k, v in d.items() if k != "last_run"}


def save(st: dict) -> bool:
    """바뀐 게 있을 때만 쓴다. 쓰면 True.

    last_run 만 달라진 상태를 매번 쓰면, 새 공시가 없어도 커밋이 계속 쌓이고
    저장소에 연결된 배포(Render 등)가 그때마다 다시 돈다.
    """
    st["seen"] = sorted(set(st.get("seen") or []))[-KEEP:]
    try:
        old = json.loads(STATE_PATH.read_text(encoding="utf-8")) if STATE_PATH.exists() else None
    except Exception:                                  # noqa: BLE001
        old = None
    if old is not None and _core(old) == _core(st):
        return False
    global DIRTY
    st["last_run"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    STATE_PATH.write_text(
        json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
    DIRTY = True
    return True


def is_new(st: dict, rcept_no: str) -> bool:
    return rcept_no not in set(st.get("seen") or [])


def mark(st: dict, rcept_no: str) -> None:
    st.setdefault("seen", []).append(rcept_no)
    if rcept_no > (st.get("last_rcept_no") or ""):
        st["last_rcept_no"] = rcept_no
