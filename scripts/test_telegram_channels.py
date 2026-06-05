import asyncio

from telethon import TelegramClient

from app.common.config import get_settings


async def main() -> None:
    settings = get_settings()
    channels = settings.telegram_channel_list
    if not channels:
        raise RuntimeError("Set TELEGRAM_CHANNELS in .env first")

    client = TelegramClient(
        settings.telegram_session_name,
        settings.telegram_api_id,
        settings.telegram_api_hash,
    )

    await client.connect()
    try:
        if not await client.is_user_authorized():
            raise RuntimeError(
                "Telegram session is not authorized. Run scripts/telegram_login.py first"
            )

        print(f"Testing {len(channels)} channel(s)")
        for channel in channels:
            entity = await client.get_entity(channel)
            title = getattr(entity, "title", channel)
            messages = await client.get_messages(entity, limit=3)
            print(f"{channel}: resolved as {title!r}, latest_messages={len(messages)}")
    finally:
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
