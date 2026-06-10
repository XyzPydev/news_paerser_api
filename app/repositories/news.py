from typing import Any

from sqlalchemy import desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.news import NewsArticle
from app.repositories.base import BaseRepository


class NewsRepository(BaseRepository[NewsArticle]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    async def list_recent(
        self,
        limit: int = 50,
        offset: int = 0,
        source: str | None = None,
        search_query: str | None = None,
        language: str | None = None,
    ) -> list[NewsArticle]:
        stmt = select(NewsArticle)

        if source:
            stmt = stmt.where(NewsArticle.source == source)
        if language:
            stmt = stmt.where(NewsArticle.detected_language == language)
        if search_query:
            stmt = stmt.where(
                or_(
                    NewsArticle.raw_text.ilike(f"%{search_query}%"),
                    NewsArticle.translated_text.ilike(f"%{search_query}%"),
                    NewsArticle.channel_title.ilike(f"%{search_query}%"),
                    NewsArticle.channel_username.ilike(f"%{search_query}%"),
                )
            )

        stmt = stmt.order_by(desc(NewsArticle.published_at)).limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_id(self, article_id: int) -> NewsArticle | None:
        stmt = select(NewsArticle).where(NewsArticle.id == article_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_message(
        self, source: str, channel_id: int | None, message_id: int
    ) -> NewsArticle | None:
        stmt = select(NewsArticle).where(
            NewsArticle.source == source,
            NewsArticle.channel_id == channel_id,
            NewsArticle.message_id == message_id,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def save(self, article: NewsArticle) -> NewsArticle:
        self.session.add(article)
        await self.session.commit()
        await self.session.refresh(article)
        return article

    async def update_enrichment(
        self, source: str, channel_id: int | None, message_id: int, sentiment: str, entities: str
    ) -> bool:
        """Update sentiment and entities for an existing article. Returns True if found."""
        stmt = select(NewsArticle).where(
            NewsArticle.source == source,
            NewsArticle.channel_id == channel_id,
            NewsArticle.message_id == message_id,
        )
        result = await self.session.execute(stmt)
        article = result.scalar_one_or_none()
        if not article:
            return False
        article.sentiment = sentiment
        article.entities = entities
        await self.session.commit()
        return True

    async def get_stats(self) -> dict[str, Any]:
        # Total count
        total_stmt = select(func.count(NewsArticle.id))
        total_result = await self.session.execute(total_stmt)
        total_count = total_result.scalar_one() or 0

        # By source
        source_stmt = select(NewsArticle.source, func.count(NewsArticle.id)).group_by(
            NewsArticle.source
        )
        source_result = await self.session.execute(source_stmt)
        by_source = {row[0]: row[1] for row in source_result.all()}

        # By language
        lang_stmt = select(NewsArticle.detected_language, func.count(NewsArticle.id)).group_by(
            NewsArticle.detected_language
        )
        lang_result = await self.session.execute(lang_stmt)
        by_language = {row[0] or "unknown": row[1] for row in lang_result.all()}

        # Media percentage
        media_stmt = select(func.count(NewsArticle.id)).where(NewsArticle.has_media)
        media_result = await self.session.execute(media_stmt)
        media_count = media_result.scalar_one() or 0

        return {
            "total_articles": total_count,
            "by_source": by_source,
            "by_language": by_language,
            "with_media": media_count,
            "without_media": total_count - media_count,
        }
