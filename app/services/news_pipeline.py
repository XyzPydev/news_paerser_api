import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

import orjson
from deep_translator import GoogleTranslator
from langdetect import detect, DetectorFactory
from redis.exceptions import RedisError

from app.common.config import Settings
from app.common.database import async_session_factory
from app.common.redis import redis_client
from app.models.news import NewsArticle
from app.repositories.news import NewsRepository

logger = logging.getLogger(__name__)

# Set language detection seed for reproducibility
DetectorFactory.seed = 0


def _json_dumps(payload: dict[str, Any]) -> str:
    return orjson.dumps(payload).decode("utf-8")


async def translate_to_english(text: str) -> tuple[str, str | None]:
    if not text.strip():
        return "", None

    # Detect language using langdetect (run in thread because it is CPU-bound)
    try:
        detected_lang = await asyncio.to_thread(detect, text)
    except Exception:
        detected_lang = None

    # If it's already English, skip translation to save API call and latency
    if detected_lang == "en":
        return text, "en"

    # Translate using GoogleTranslator (run in thread because it's synchronous)
    try:
        translated_text = await asyncio.to_thread(
            lambda: GoogleTranslator(source="auto", target="en").translate(text)
        )
        return translated_text, detected_lang
    except Exception as exc:
        logger.warning("Translation failed: %s", exc)
        return text, detected_lang


async def publish_news_event(settings: Settings, event: dict[str, Any]) -> None:
    """
    Hot Path: publish raw event to Redis Pub/Sub for immediate WebSocket delivery.
    Also enqueue to Redis Stream for the Enrichment Worker (Warm Path).
    """
    payload = _json_dumps(event)
    try:
        await redis_client.publish(settings.redis_raw_news_channel, payload)
        await redis_client.xadd(
            settings.redis_enrichment_stream,
            {"event": payload},
            maxlen=10_000,
            approximate=True,
        )
    except RedisError as exc:
        logger.warning("Failed to publish news event to Redis: %s", exc)


async def cache_news_event(settings: Settings, event: dict[str, Any]) -> None:
    """
    Cache the news event in a Redis List (news.cache) for fast GET /news responses.
    Keeps only the last `redis_news_cache_size` entries (default: 200).

    Architecture note (plan section 4.B):
    - LPUSH prepends the new item (most-recent first)
    - LTRIM prunes the list to a fixed maximum length
    - LRANGE on GET /news responses is <2ms from RAM vs Postgres IOPS
    """
    payload = _json_dumps(event)
    try:
        pipe = redis_client.pipeline()
        pipe.lpush(settings.redis_news_cache_key, payload)
        pipe.ltrim(settings.redis_news_cache_key, 0, settings.redis_news_cache_size - 1)
        await pipe.execute()
    except RedisError as exc:
        logger.warning("Failed to cache news event in Redis: %s", exc)


async def save_news_to_db(event: dict[str, Any]) -> None:
    async with async_session_factory() as session:
        repo = NewsRepository(session)
        msg = event["message"]
        channel = event.get("channel") or {}

        # Check for duplicate telegram message (source, channel_id, message_id)
        existing = await repo.get_by_message(event["source"], channel.get("id"), msg["id"])
        if existing:
            logger.info(
                "News article already exists in DB: source=%s, channel_id=%s, message_id=%s",
                event["source"],
                channel.get("id"),
                msg["id"],
            )
            return

        published_at = datetime.fromisoformat(msg["published_at"])
        received_at = datetime.fromisoformat(msg["received_at"])

        article = NewsArticle(
            source=event["source"],
            provider=event["provider"],
            channel_id=channel.get("id"),
            channel_username=channel.get("username"),
            channel_title=channel.get("title"),
            message_id=msg["id"],
            url=msg["url"],
            published_at=published_at,
            received_at=received_at,
            has_media=msg["has_media"],
            raw_text=msg["raw_text"],
            translated_text=msg["translated_text"],
            detected_language=msg["detected_language"],
        )
        await repo.save(article)
        logger.info("News article saved to DB successfully: id=%s", msg["id"])


async def process_telegram_post(settings: Settings, post: dict[str, Any]) -> dict[str, Any]:
    translated_text, detected_language = await translate_to_english(post["raw_text"])
    provider = post.get("provider", "telethon")
    event = {
        "type": "telegram.news.raw",
        "source": "telegram",
        "provider": provider,
        "channel": post["channel"],
        "message": {
            "id": post["message_id"],
            "url": post["url"],
            "published_at": post["published_at"],
            "received_at": datetime.now(UTC).isoformat(),
            "has_media": post["has_media"],
            "raw_text": post["raw_text"],
            "translated_text": translated_text,
            "detected_language": detected_language,
        },
    }
    await publish_news_event(settings, event)
    # Cache in Redis for fast reads — fire and forget errors
    await cache_news_event(settings, event)
    try:
        await save_news_to_db(event)
    except Exception as exc:
        logger.exception("Failed to save news article to database: %s", exc)
    return event
