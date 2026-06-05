import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import ORJSONResponse

from app.common.config import get_settings
from app.common.database import close_database
from app.common.redis import close_redis
from app.services.enrichment import run_enrichment_worker
from app.services.telegram_scraper import run_telegram_scraper
from app.services.truth_scraper import run_truth_scraper


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    stop_event = asyncio.Event()
    tasks = [
        asyncio.create_task(run_telegram_scraper(settings, stop_event)),
        asyncio.create_task(run_truth_scraper(settings, stop_event)),
        asyncio.create_task(run_enrichment_worker(settings, stop_event)),
    ]

    app.state.stop_event = stop_event
    app.state.background_tasks = tasks

    try:
        yield
    finally:
        stop_event.set()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await close_redis()
        await close_database()


app = FastAPI(
    title=get_settings().app_name,
    default_response_class=ORJSONResponse,
    lifespan=lifespan,
)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
