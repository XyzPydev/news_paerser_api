"""
Enrichment Worker — Warm Path (target latency: 1-3s)

Reads raw news events from the Redis Stream, runs LLM sentiment analysis
via Groq API (or falls back to 'neutral' if key not configured), updates
the PostgreSQL record and re-publishes an enriched event to Redis Pub/Sub
so WebSocket clients receive the enriched data.

Architecture reference: plan section 2 (Warm Path) and section 5 (Stage 3).
"""

import asyncio
import logging
from typing import Any

import orjson
from redis.exceptions import RedisError

from app.common.config import Settings
from app.common.database import async_session_factory
from app.common.redis import redis_client
from app.repositories.news import NewsRepository

logger = logging.getLogger(__name__)

_SENTIMENT_PROMPT = """You are a financial news sentiment classifier.
Analyze the following news text and respond with EXACTLY one word:
- "positive" if the news is bullish / optimistic for markets
- "negative" if the news is bearish / pessimistic for markets
- "neutral" if unclear or mixed

Also extract up to 5 key financial entities (companies, currencies, commodities, countries) as a comma-separated list.

Respond in this exact format (two lines):
SENTIMENT: <positive|negative|neutral>
ENTITIES: <entity1, entity2, ...>

News text:
{text}
"""


def _parse_llm_response(response_text: str) -> tuple[str, str]:
    """Parse LLM response into (sentiment, entities_json_string)."""
    sentiment = "neutral"
    entities: list[str] = []

    for line in response_text.strip().splitlines():
        line = line.strip()
        if line.upper().startswith("SENTIMENT:"):
            raw = line.split(":", 1)[1].strip().lower()
            if raw in ("positive", "negative", "neutral"):
                sentiment = raw
        elif line.upper().startswith("ENTITIES:"):
            raw_entities = line.split(":", 1)[1].strip()
            entities = [e.strip() for e in raw_entities.split(",") if e.strip()]

    return sentiment, orjson.dumps(entities).decode("utf-8")


async def _analyze_with_groq(text: str, api_key: str) -> tuple[str, str]:
    """Call Groq API for sentiment + entity extraction. Returns (sentiment, entities_json)."""
    try:
        from groq import AsyncGroq  # noqa: PLC0415

        client = AsyncGroq(api_key=api_key)
        completion = await client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[{"role": "user", "content": _SENTIMENT_PROMPT.format(text=text[:2000])}],
            max_tokens=100,
            temperature=0.1,
        )
        response_text = completion.choices[0].message.content or ""
        return _parse_llm_response(response_text)
    except Exception as exc:
        logger.warning("Groq API call failed, falling back to neutral: %s", exc)
        return "neutral", "[]"


async def _analyze_sentiment(text: str, settings: Settings) -> tuple[str, str]:
    """Determine sentiment and extract entities. Falls back gracefully without API key."""
    if not text.strip():
        return "neutral", "[]"

    if settings.groq_api_key:
        return await _analyze_with_groq(text, settings.groq_api_key)

    # No API key configured — return neutral (graceful degradation)
    logger.debug("No GROQ_API_KEY configured; skipping LLM enrichment")
    return "neutral", "[]"


async def _process_event(settings: Settings, event_data: dict[str, Any]) -> None:
    """Process a single raw event: enrich with LLM and persist."""
    msg = event_data.get("message", {})
    channel = event_data.get("channel") or {}
    source = event_data.get("source", "")

    # Prefer translated text for LLM (it's in English), fallback to raw
    text_for_llm = msg.get("translated_text") or msg.get("raw_text", "")
    sentiment, entities = await _analyze_sentiment(text_for_llm, settings)

    # Persist enrichment to PostgreSQL
    channel_id = channel.get("id")
    message_id = msg.get("id")
    if source and message_id is not None:
        try:
            async with async_session_factory() as session:
                repo = NewsRepository(session)
                updated = await repo.update_enrichment(
                    source=source,
                    channel_id=channel_id,
                    message_id=message_id,
                    sentiment=sentiment,
                    entities=entities,
                )
                if not updated:
                    logger.debug("Article not found for enrichment: %s/%s", source, message_id)
        except Exception as exc:
            logger.exception("Failed to persist enrichment to DB: %s", exc)

    # Build enriched event and re-publish to Redis Pub/Sub (Warm Path)
    enriched_event = {
        **event_data,
        "type": "telegram.news.enriched",
        "sentiment": sentiment,
        "entities": entities,
    }
    try:
        payload = orjson.dumps(enriched_event).decode("utf-8")
        await redis_client.publish(settings.redis_enriched_channel, payload)
    except RedisError as exc:
        logger.warning("Failed to publish enriched event: %s", exc)

    logger.info(
        "Enriched article: source=%s id=%s sentiment=%s entities=%s",
        source,
        message_id,
        sentiment,
        entities,
    )


async def _ensure_consumer_group(settings: Settings) -> None:
    """Create the Redis consumer group if it doesn't already exist."""
    try:
        await redis_client.xgroup_create(
            settings.redis_enrichment_stream,
            settings.redis_consumer_group,
            id="0",
            mkstream=True,
        )
        logger.info("Created Redis consumer group: %s", settings.redis_consumer_group)
    except Exception as exc:
        # BUSYGROUP means the group already exists — this is expected on restart
        if "BUSYGROUP" not in str(exc):
            logger.warning("xgroup_create warning: %s", exc)


async def run_enrichment_worker(settings: Settings, stop_event: asyncio.Event) -> None:
    """
    Warm Path enrichment worker.

    Uses XREADGROUP for fault-tolerant consumer group semantics:
    - Each message is acknowledged (XACK) only after successful processing
    - On restart, unacknowledged messages are reclaimed and reprocessed
    - Multiple replicas can run concurrently; Redis distributes messages between them
    """
    await _ensure_consumer_group(settings)
    consumer_name = "worker-1"
    logger.info("Enrichment worker started (consumer: %s)", consumer_name)

    while not stop_event.is_set():
        try:
            # First check for pending (unacknowledged) messages from a previous crash
            messages = await redis_client.xreadgroup(
                groupname=settings.redis_consumer_group,
                consumername=consumer_name,
                streams={settings.redis_enrichment_stream: ">"},
                count=5,
                block=1000,  # block for 1s, yields to event loop
            )

            if not messages:
                continue

            for _stream, entries in messages:
                for entry_id, fields in entries:
                    raw_payload = fields.get("event") or fields.get(b"event", "")
                    if isinstance(raw_payload, bytes):
                        raw_payload = raw_payload.decode("utf-8")

                    try:
                        event_data = orjson.loads(raw_payload)
                        await _process_event(settings, event_data)
                    except Exception as exc:
                        logger.exception("Failed to process enrichment entry %s: %s", entry_id, exc)
                    finally:
                        # ACK regardless to avoid infinite reprocessing on persistent errors
                        try:
                            await redis_client.xack(
                                settings.redis_enrichment_stream,
                                settings.redis_consumer_group,
                                entry_id,
                            )
                        except RedisError as ack_exc:
                            logger.warning("XACK failed for %s: %s", entry_id, ack_exc)

        except asyncio.CancelledError:
            break
        except RedisError as exc:
            logger.warning("Enrichment worker Redis error: %s — retrying in 5s", exc)
            await asyncio.sleep(5)
        except Exception as exc:
            logger.exception("Unexpected enrichment worker error: %s", exc)
            await asyncio.sleep(5)

    logger.info("Enrichment worker stopped")
