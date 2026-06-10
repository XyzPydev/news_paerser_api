import asyncio
import logging
from collections.abc import Sequence

from telethon import TelegramClient, events
from telethon.events import NewMessage

from app.common.config import Settings
from app.services.news_pipeline import process_telegram_post

logger = logging.getLogger(__name__)


def get_telethon_session_name(base_session_name: str) -> str:
    return f"{base_session_name}-telethon"


import os

def create_telethon_client(settings: Settings) -> TelegramClient:
    os.makedirs("app/sessions", exist_ok=True)
    session_path = os.path.join("app/sessions", get_telethon_session_name(settings.telegram_session_name))
    return TelegramClient(
        session_path,
        settings.telegram_api_id,
        settings.telegram_api_hash,
        device_model="Windows PC",
        system_version="Windows",
        app_version="1.0",
    )


def normalize_channel(channel: str) -> str:
    channel = channel.strip()
    if channel.startswith("https://t.me/"):
        channel = channel.removeprefix("https://t.me/")
    if channel.startswith("http://t.me/"):
        channel = channel.removeprefix("http://t.me/")
    return channel.strip("/")


def normalize_channels(channels: Sequence[str]) -> list[str]:
    return [normalize_channel(channel) for channel in channels if channel.strip()]


async def run_telethon_userbot(settings: Settings, stop_event: asyncio.Event) -> None:
    configured_channels = settings.telegram_channel_list
    if settings.telegram_target_channel:
        configured_channels = [settings.telegram_target_channel]
    channels = normalize_channels(configured_channels)
    if not channels:
        logger.info("Telethon userbot started without configured channels")
        await stop_event.wait()
        return

    client = create_telethon_client(settings)
    await client.start()
    try:
        me = await client.get_me()
        logger.info(
            "Telethon userbot started as %s for %d channel(s): %s",
            me.username or me.id,
            len(channels),
            channels,
        )

        @client.on(events.NewMessage(chats=channels))
        async def handle_channel_message(event: NewMessage.Event) -> None:
            chat = await event.get_chat()
            chat_id = getattr(chat, "id", None)
            chat_username = getattr(chat, "username", None)
            chat_title = getattr(chat, "title", None) or chat_username or chat_id
            text = event.raw_text or ""
            preview = text.replace("\n", " ")[:240]
            url = f"https://t.me/{chat_username}/{event.message.id}" if chat_username else None
            post = {
                "channel": {
                    "id": chat_id,
                    "username": chat_username,
                    "title": chat_title,
                },
                "message_id": event.message.id,
                "url": url,
                "published_at": event.message.date.isoformat(),
                "has_media": event.message.media is not None,
                "raw_text": text,
            }
            news_event = await process_telegram_post(settings, post)
            logger.info(
                "Telegram post parsed chat=%s id=%s date=%s translated=%s preview=%r",
                chat_title,
                event.message.id,
                event.message.date,
                bool(news_event["message"]["translated_text"]),
                preview,
            )

        await stop_event.wait()
    finally:
        await client.disconnect()
