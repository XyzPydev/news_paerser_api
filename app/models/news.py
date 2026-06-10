from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class NewsArticle(Base):
    __tablename__ = "news_articles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(50), nullable=False)  # e.g., "telegram"
    provider: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # e.g., "telethon", "pyrogram"
    channel_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    channel_username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    channel_title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
    has_media: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    translated_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    detected_language: Mapped[str | None] = mapped_column(String(10), nullable=True)
    sentiment: Mapped[str | None] = mapped_column(String(20), nullable=True)  # positive/negative/neutral
    entities: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON string of extracted entities

    __table_args__ = (
        UniqueConstraint("source", "channel_id", "message_id", name="uq_source_channel_message"),
    )
