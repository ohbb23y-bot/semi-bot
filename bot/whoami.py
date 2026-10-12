"""텔레그램 chat_id 알아내기.

    1) @BotFather 에서 /newbot 으로 봇을 만들고 토큰을 .env 에 넣는다
    2) 텔레그램에서 그 봇을 찾아 아무 말이나 보낸다
    3) python -m bot.whoami
"""
from __future__ import annotations

from . import telegram
from .config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID


def main() -> int:
    if not TELEGRAM_BOT_TOKEN:
        print("TELEGRAM_BOT_TOKEN 이 .env 에 없습니다.")
        print("@BotFather 에서 /newbot 으로 만든 뒤 토큰을 넣으세요.")
        return 1
    ups = telegram.updates()
    if not ups:
        print("봇이 받은 메시지가 없습니다.")
        print("텔레그램에서 봇을 찾아 아무 말이나 보낸 뒤 다시 실행하세요.")
        return 1
    seen = {}
    for u in ups:
        msg = u.get("message") or u.get("channel_post") or {}
        chat = msg.get("chat") or {}
        if chat.get("id"):
            seen[chat["id"]] = chat.get("title") or chat.get("username") or chat.get("first_name") or ""
    for cid, who in seen.items():
        print(f"  chat_id = {cid}    ({who})")
    print("\n.env 에 아래 줄을 넣으세요:")
    print(f"TELEGRAM_CHAT_ID={list(seen)[0]}")
    if TELEGRAM_CHAT_ID:
        print(f"\n(지금 설정된 값: {TELEGRAM_CHAT_ID})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
