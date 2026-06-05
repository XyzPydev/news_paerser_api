import asyncio

from app.common.config import Settings


async def run_truth_scraper(settings: Settings, stop_event: asyncio.Event) -> None:
    while not stop_event.is_set():
        await asyncio.sleep(5)
