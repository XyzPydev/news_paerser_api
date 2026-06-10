import asyncio

from app.common.config import get_settings
from app.services.telegram_userbot_telethon import (
    create_telethon_client,
    get_telethon_session_name,
    normalize_channels,
)


async def main() -> None:
    settings = get_settings()
    channels = normalize_channels(settings.telegram_channel_list)
    if not channels:
        raise RuntimeError("Set TELEGRAM_CHANNELS in .env first")

    session_name = get_telethon_session_name(settings.telegram_session_name)
    client = create_telethon_client(settings)

    await client.connect()
    try:
        if not await client.is_user_authorized():
            raise RuntimeError(
                f"Telegram session {session_name}.session is not authorized. "
                "Run scripts/telethon_qr_login.py first"
            )

        print(f"Testing {len(channels)} channel(s)")
        for channel in channels:
            entity = await client.get_entity(channel)
            title = getattr(entity, "title", None) or getattr(entity, "username", channel)
            messages = await client.get_messages(entity, limit=3)
            print(f"{channel}: resolved as {title!r}, latest_messages={len(messages)}")
    finally:
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
