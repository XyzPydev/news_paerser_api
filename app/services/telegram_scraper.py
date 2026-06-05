import asyncio
import logging

from app.common.config import Settings

logger = logging.getLogger(__name__)


async def run_telegram_scraper(settings: Settings, stop_event: asyncio.Event) -> None:
    channels = settings.telegram_channel_list
    if not channels:
        logger.info("Telegram scraper started without configured channels")
    else:
        logger.info("Telegram scraper configured for %d channel(s): %s", len(channels), channels)

    while not stop_event.is_set():
        await asyncio.sleep(5)
