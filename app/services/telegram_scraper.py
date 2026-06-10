import asyncio
import logging

from app.common.config import Settings
from app.services.telegram_userbot import run_userbot
from app.services.telegram_userbot_telethon import run_telethon_userbot

logger = logging.getLogger(__name__)


async def run_telegram_scraper(settings: Settings, stop_event: asyncio.Event) -> None:
    if not settings.telegram_api_id or settings.telegram_api_hash == "replace-me":
        logger.info(
            "Telegram scraper disabled: TELEGRAM_API_ID or TELEGRAM_API_HASH not configured. "
            "Set them in .env and run the authorization script to enable polling."
        )
        await stop_event.wait()
        return

    import os
    client_type = settings.telegram_client.lower()
    session_file = f"app/sessions/{settings.telegram_session_name}-{client_type}.session"
    if not os.path.exists(session_file):
        logger.warning(
            f"Telegram scraper session file not found at '{session_file}'. "
            "Please run 'uv run python scripts/telegram_login.py' (or scripts/telethon_login.py) "
            "on your host first to authorize the userbot."
        )
        await stop_event.wait()
        return

    try:
        if client_type == "telethon":
            await run_telethon_userbot(settings, stop_event)
        else:
            await run_userbot(settings, stop_event)
    except Exception:
        logger.exception("Telegram userbot stopped unexpectedly")
        while not stop_event.is_set():
            await asyncio.sleep(30)
