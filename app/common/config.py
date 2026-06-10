from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "news-parser-api"
    environment: str = "local"
    log_level: str = "INFO"

    database_url: str = "postgresql+asyncpg://news_parser:news_parser@localhost:5432/news_parser"
    redis_url: str = "redis://localhost:6379/0"
    redis_raw_news_channel: str = "news.raw"
    redis_enrichment_stream: str = "news.enrichment"
    redis_enriched_channel: str = "news.enriched"
    redis_news_cache_key: str = "news.cache"
    redis_consumer_group: str = "enrichment-workers"
    redis_news_cache_size: int = 200

    groq_api_key: str = ""

    telegram_api_id: int = Field(default=0)
    telegram_api_hash: str = "replace-me"
    telegram_session_name: str = "news-parser"
    telegram_client: str = "pyrogram"
    telegram_channels: str = ""
    telegram_target_channel: str = "@Tasnimnews"

    truth_social_access_token: str = "replace-me"

    @property
    def telegram_channel_list(self) -> list[str]:
        return [channel.strip() for channel in self.telegram_channels.split(",") if channel.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
