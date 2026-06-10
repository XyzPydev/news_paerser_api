import asyncio
import logging

from app.common.config import Settings
from app.services.telegram_userbot import run_userbot
from app.services.telegram_userbot_telethon import run_telethon_userbot

logger = logging.getLogger(__name__)


async def run_telegram_scraper(settings: Settings, stop_event: asyncio.Event) -> None:
    try:
        if settings.telegram_client.lower() == "telethon":
            await run_telethon_userbot(settings, stop_event)
        else:
            await run_userbot(settings, stop_event)
    except Exception:
        logger.exception("Telegram userbot stopped unexpectedly")
        while not stop_event.is_set():
            await asyncio.sleep(30)
