from datetime import datetime

from pydantic import BaseModel, ConfigDict


class NewsArticleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source: str
    provider: str
    channel_id: int | None = None
    channel_username: str | None = None
    channel_title: str | None = None
    message_id: int | None = None
    url: str | None = None
    published_at: datetime
    received_at: datetime
    has_media: bool
    raw_text: str
    translated_text: str | None = None
    detected_language: str | None = None
    sentiment: str | None = None
    entities: str | None = None


class NewsArticleList(BaseModel):
    items: list[NewsArticleResponse]
    total: int
    limit: int
    offset: int


class StatsResponse(BaseModel):
    total_articles: int
    by_source: dict[str, int]
    by_language: dict[str, int]
    with_media: int
    without_media: int
