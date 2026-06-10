import asyncio
import logging
from collections.abc import Sequence

from pyrogram import Client, filters
from pyrogram.handlers import MessageHandler
from pyrogram.types import Message

from app.common.config import Settings
from app.services.news_pipeline import process_telegram_post

logger = logging.getLogger(__name__)


def get_pyrogram_session_name(base_session_name: str) -> str:
    return f"{base_session_name}-pyrogram"


def create_userbot_client(settings: Settings) -> Client:
    return Client(
        get_pyrogram_session_name(settings.telegram_session_name),
        api_id=settings.telegram_api_id,
        api_hash=settings.telegram_api_hash,
        workdir=".",
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


async def run_userbot(settings: Settings, stop_event: asyncio.Event) -> None:
    channels = normalize_channels(settings.telegram_channel_list)
    if not channels:
        logger.info("Telegram userbot started without configured channels")
        await stop_event.wait()
        return

    client = create_userbot_client(settings)
    channel_filter = filters.chat(channels)

    async def handle_channel_message(_: Client, message: Message) -> None:
        chat_title = message.chat.title or message.chat.username or str(message.chat.id)
        text = message.text or message.caption or ""
        preview = text.replace("\n", " ")[:240]
        chat_username = message.chat.username
        url = f"https://t.me/{chat_username}/{message.id}" if chat_username else None

        post = {
            "channel": {
                "id": message.chat.id,
                "username": chat_username,
                "title": chat_title,
            },
            "message_id": message.id,
            "url": url,
            "published_at": message.date.isoformat(),
            "has_media": (message.photo or message.video or message.document or message.animation)
            is not None,
            "raw_text": text,
            "provider": "pyrogram",
        }

        news_event = await process_telegram_post(settings, post)

        logger.info(
            "Telegram message chat=%s id=%s date=%s translated=%s preview=%r",
            chat_title,
            message.id,
            message.date,
            bool(news_event["message"]["translated_text"]),
            preview,
        )

    client.add_handler(MessageHandler(handle_channel_message, channel_filter))

    await client.start()
    try:
        me = await client.get_me()
        logger.info(
            "Telegram userbot started as %s for %d channel(s): %s",
            me.username or me.id,
            len(channels),
            channels,
        )
        await stop_event.wait()
    finally:
        await client.stop()
