import asyncio
import sys

import orjson

from app.common.config import get_settings
from app.services.news_pipeline import process_telegram_post
from app.services.telegram_userbot_telethon import (
    create_telethon_client,
    get_telethon_session_name,
    normalize_channel,
)


async def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    settings = get_settings()
    channel = normalize_channel(settings.telegram_target_channel or "@Tasnimnews")
    session_name = get_telethon_session_name(settings.telegram_session_name)
    client = create_telethon_client(settings)

    await client.connect()
    try:
        if not await client.is_user_authorized():
            raise RuntimeError(
                f"Telegram session {session_name}.session is not authorized. "
                "Run scripts/telethon_qr_login.py first"
            )

        entity = await client.get_entity(channel)
        message = (await client.get_messages(entity, limit=1))[0]
        chat_username = getattr(entity, "username", None)
        post = {
            "channel": {
                "id": getattr(entity, "id", None),
                "username": chat_username,
                "title": getattr(entity, "title", None) or chat_username or channel,
            },
            "message_id": message.id,
            "url": f"https://t.me/{chat_username}/{message.id}" if chat_username else None,
            "published_at": message.date.isoformat(),
            "has_media": message.media is not None,
            "raw_text": message.raw_text or "",
        }

        event = await process_telegram_post(settings, post)
        print(orjson.dumps(event, option=orjson.OPT_INDENT_2).decode("utf-8"))
    finally:
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
