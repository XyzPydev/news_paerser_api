import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import orjson
from fastapi import FastAPI
from fastapi.responses import ORJSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.common.config import get_settings
from app.common.database import close_database, engine
from app.common.redis import close_redis, redis_client
from app.models.base import Base
from app.routers.news import router as news_router
from app.routers.ws import manager as ws_manager
from app.routers.ws import router as ws_router
from app.services.enrichment import run_enrichment_worker
from app.services.telegram_scraper import run_telegram_scraper
from app.services.truth_scraper import run_truth_scraper

logger = logging.getLogger(__name__)

# Configure logging based on settings
logging.basicConfig(
    level=get_settings().log_level.upper(),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)


async def redis_pubsub_listener(stop_event: asyncio.Event) -> None:
    """
    Hot Path listener: subscribes to Redis Pub/Sub and broadcasts every raw
    news event to all connected WebSocket clients in real-time (<50ms target).

    Also listens to the enriched channel and re-broadcasts enriched events so
    that clients can update existing cards with sentiment/entities.
    """
    settings = get_settings()
    # Use a dedicated Redis connection for blocking Pub/Sub operations
    pubsub = redis_client.pubsub()
    await pubsub.subscribe(settings.redis_raw_news_channel, settings.redis_enriched_channel)
    logger.info(
        "Redis Pub/Sub listener subscribed to: %s, %s",
        settings.redis_raw_news_channel,
        settings.redis_enriched_channel,
    )
    try:
        while not stop_event.is_set():
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.1)
            if message and message.get("type") == "message":
                raw_data = message.get("data", "")
                if isinstance(raw_data, bytes):
                    raw_data = raw_data.decode("utf-8")
                if raw_data and ws_manager.client_count > 0:
                    channel = message.get("channel", "")
                    if isinstance(channel, bytes):
                        channel = channel.decode("utf-8")
                    # Wrap with channel context so the frontend knows the event type
                    try:
                        payload = orjson.loads(raw_data)
                        payload["_channel"] = channel
                        await ws_manager.broadcast(orjson.dumps(payload).decode("utf-8"))
                    except Exception:
                        await ws_manager.broadcast(raw_data)
            else:
                await asyncio.sleep(0.01)
    except asyncio.CancelledError:
        pass
    finally:
        await pubsub.unsubscribe()
        await pubsub.aclose()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()

    # Automatically create database tables if they do not exist
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    stop_event = asyncio.Event()
    tasks = [
        asyncio.create_task(run_telegram_scraper(settings, stop_event)),
        asyncio.create_task(run_truth_scraper(settings, stop_event)),
        asyncio.create_task(run_enrichment_worker(settings, stop_event)),
        asyncio.create_task(redis_pubsub_listener(stop_event)),
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

# Include API Routers
app.include_router(news_router, prefix="/api/v1")
app.include_router(ws_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "ws_clients": str(ws_manager.client_count)}


@app.get("/")
async def root() -> RedirectResponse:
    return RedirectResponse(url="/dashboard/")


# Serve visual dashboard SPA
app.mount("/dashboard", StaticFiles(directory="app/static", html=True), name="static")
