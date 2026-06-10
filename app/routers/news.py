import logging
from typing import Any

import orjson
from fastapi import APIRouter, Depends, HTTPException, Query
from redis.exceptions import RedisError
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.config import get_settings
from app.common.database import get_session
from app.common.redis import redis_client
from app.models.news import NewsArticle
from app.repositories.news import NewsRepository
from app.schemas.news import NewsArticleList, NewsArticleResponse, StatsResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/news", tags=["news"])


def _parse_cached_items(raw_items: list[str]) -> list[dict[str, Any]]:
    """Deserialize cached JSON strings into dicts, skipping malformed entries."""
    parsed = []
    for raw in raw_items:
        try:
            data = orjson.loads(raw)
            msg = data.get("message", {})
            channel = data.get("channel") or {}
            parsed.append(
                {
                    "id": msg.get("id", 0),
                    "source": data.get("source", ""),
                    "provider": data.get("provider", ""),
                    "channel_id": channel.get("id"),
                    "channel_username": channel.get("username"),
                    "channel_title": channel.get("title"),
                    "message_id": msg.get("id"),
                    "url": msg.get("url"),
                    "published_at": msg.get("published_at", ""),
                    "received_at": msg.get("received_at", ""),
                    "has_media": msg.get("has_media", False),
                    "raw_text": msg.get("raw_text", ""),
                    "translated_text": msg.get("translated_text"),
                    "detected_language": msg.get("detected_language"),
                    "sentiment": data.get("sentiment"),
                    "entities": data.get("entities"),
                }
            )
        except Exception:
            logger.debug("Skipping malformed cached entry")
    return parsed


@router.get("", response_model=NewsArticleList)
async def list_news(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    source: str | None = Query(default=None),
    language: str | None = Query(default=None),
    search: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> NewsArticleList:
    settings = get_settings()

    # Fast path: serve from Redis cache when no filters are applied (plan section 4.B)
    if not source and not language and not search:
        try:
            start = offset
            end = offset + limit - 1
            raw_items = await redis_client.lrange(settings.redis_news_cache_key, start, end)
            total_cached = await redis_client.llen(settings.redis_news_cache_key)

            if raw_items:
                parsed = _parse_cached_items(raw_items)
                # Build lightweight response objects from cache dicts
                items = []
                for p in parsed:
                    try:
                        items.append(NewsArticleResponse(**p))
                    except Exception:
                        pass
                return NewsArticleList(
                    items=items,
                    total=int(total_cached),
                    limit=limit,
                    offset=offset,
                )
        except RedisError as exc:
            logger.warning("Redis cache miss, falling through to Postgres: %s", exc)

    # Slow path: query PostgreSQL (with or without filters)
    repo = NewsRepository(session)

    count_stmt = select(func.count(NewsArticle.id))
    if source:
        count_stmt = count_stmt.where(NewsArticle.source == source)
    if language:
        count_stmt = count_stmt.where(NewsArticle.detected_language == language)
    if search:
        count_stmt = count_stmt.where(
            or_(
                NewsArticle.raw_text.ilike(f"%{search}%"),
                NewsArticle.translated_text.ilike(f"%{search}%"),
                NewsArticle.channel_title.ilike(f"%{search}%"),
                NewsArticle.channel_username.ilike(f"%{search}%"),
            )
        )

    total_result = await session.execute(count_stmt)
    total = total_result.scalar_one() or 0

    items = await repo.list_recent(
        limit=limit,
        offset=offset,
        source=source,
        search_query=search,
        language=language,
    )

    return NewsArticleList(
        items=[NewsArticleResponse.model_validate(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/stats", response_model=StatsResponse)
async def get_stats(session: AsyncSession = Depends(get_session)) -> StatsResponse:
    repo = NewsRepository(session)
    stats = await repo.get_stats()
    return StatsResponse(**stats)


@router.get("/{article_id}", response_model=NewsArticleResponse)
async def get_article(
    article_id: int,
    session: AsyncSession = Depends(get_session),
) -> NewsArticleResponse:
    repo = NewsRepository(session)
    article = await repo.get_by_id(article_id)
    if not article:
        raise HTTPException(status_code=404, detail="News article not found")
    return NewsArticleResponse.model_validate(article)
