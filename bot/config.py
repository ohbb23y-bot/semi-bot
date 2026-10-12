"""반도체 봇 설정.

키는 전부 .env 에서 읽는다. 저장소에 올라가지 않는다(.gitignore).

    TELEGRAM_BOT_TOKEN=...   @BotFather 에서 /newbot 으로 발급
    TELEGRAM_CHAT_ID=...     봇에게 아무 말이나 보낸 뒤 python -m bot.whoami
    DART_API_KEY=...         https://opendart.fss.or.kr 에서 무료 발급
    ECOS_API_KEY=...         https://ecos.bok.or.kr 에서 무료 발급 (업황 지표용)
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

TELEGRAM_BOT_TOKEN = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
TELEGRAM_CHAT_ID = (os.getenv("TELEGRAM_CHAT_ID") or "").strip()
DART_API_KEY = (os.getenv("DART_API_KEY") or "").strip()

UNIVERSE_PATH = Path(__file__).resolve().parent / "universe.json"
STATE_PATH = Path(os.getenv("BOT_STATE_PATH") or Path(__file__).resolve().parent / "state.json")


def universe() -> dict[str, str]:
    """{티커: 종목명}. 반도체 스크리닝.xlsx 에서 뽑아둔 목록."""
    d = json.loads(UNIVERSE_PATH.read_text(encoding="utf-8"))
    return {r["ticker"]: r["name"] for r in d["rows"]}


def telegram_ready() -> bool:
    return bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)


def kst_now():
    """한국 시각 (tz 없는 datetime). 러너 시간대와 무관하게 KST 로 맞춘다."""
    from datetime import datetime, timedelta, timezone
    return datetime.now(timezone(timedelta(hours=9))).replace(tzinfo=None)
