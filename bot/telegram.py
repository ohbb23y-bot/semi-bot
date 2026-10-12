"""텔레그램 전송.

메시지 한 건은 4096자가 한계다. 넘으면 텔레그램이 통째로 거절한다.
채널·그룹에는 분당 20건 안팎의 전송 제한도 있어, 429 가 오면 알려준
시간만큼 기다렸다 다시 보낸다.
"""
from __future__ import annotations

import html
import time

import truststore
truststore.inject_into_ssl()
import httpx

from .config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

API = "https://api.telegram.org/bot{token}/{method}"
LIMIT = 3900                      # 4096 에서 여유를 둔다
GAP = 1.2                         # 메시지 사이 간격(초). 넘치면 429 를 받아 기다린다.
_cli = httpx.Client(timeout=30)


def _call(method: str, **payload):
    if not TELEGRAM_BOT_TOKEN:
        raise SystemExit("TELEGRAM_BOT_TOKEN 이 .env 에 없습니다.")
    for _ in range(4):
        r = _cli.post(API.format(token=TELEGRAM_BOT_TOKEN, method=method), json=payload)
        d = r.json()
        if d.get("ok"):
            return d["result"]
        if r.status_code == 429:                      # 너무 빨리 보냈다
            wait = (d.get("parameters") or {}).get("retry_after", 5)
            time.sleep(min(int(wait), 60) + 1)
            continue
        raise SystemExit(f"텔레그램 {method} 실패: {d.get('description')}")
    raise SystemExit(f"텔레그램 {method} 실패: 전송 제한이 계속 걸립니다.")


def chunks(blocks: list[str]) -> list[str]:
    """블록 목록을 4096자 한계 안으로 묶는다.

    블록은 쪼개지 않는다. 인용 블록 한가운데서 잘리면 닫는 태그가 없어
    텔레그램이 메시지를 통째로 거절한다. 블록 사이는 빈 줄로 띄운다.
    """
    out, cur, n = [], [], 0
    for b in blocks:
        if n + len(b) + 2 > LIMIT and cur:
            out.append("\n\n".join(cur))
            cur, n = [], 0
        cur.append(b)
        n += len(b) + 2
    if cur:
        out.append("\n\n".join(cur))
    return out


def _chat(chat_id: str) -> str:
    chat = chat_id or TELEGRAM_CHAT_ID
    if not chat:
        raise SystemExit("TELEGRAM_CHAT_ID 가 .env 에 없습니다. python -m bot.whoami")
    return chat


def send_one(text: str, chat_id: str = "") -> None:
    """메시지 한 건."""
    _call("sendMessage", chat_id=_chat(chat_id), text=text,
          parse_mode="HTML", disable_web_page_preview=True)


def send(blocks: list[str], chat_id: str = "") -> int:
    """블록들을 4096자 안으로 묶어 보낸다. 보낸 메시지 수를 돌려준다."""
    sent = 0
    for body in chunks(blocks):
        send_one(body, chat_id)
        sent += 1
        time.sleep(GAP)
    return sent


def updates() -> list[dict]:
    """봇이 받은 메시지. chat_id 를 알아내는 데 쓴다."""
    return _call("getUpdates")


def esc(s: str) -> str:
    """HTML 모드에서 제목에 < > & 가 있으면 메시지가 통째로 깨진다."""
    # 네이버 제목에는 &quot; 같은 엔티티가 이미 들어 있다. 그대로 이스케이프하면
    # '&amp;quot;' 로 이중이 되어 따옴표 자리에 글자가 그대로 보인다.
    return html.escape(html.unescape(s or ""), quote=False)
