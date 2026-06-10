import asyncio

from app.common.config import get_settings
from app.services.telegram_userbot import (
    create_userbot_client,
    get_pyrogram_session_name,
    normalize_channels,
)


async def main() -> None:
    settings = get_settings()
    channels = settings.telegram_channel_list
    if not channels:
        raise RuntimeError("Set TELEGRAM_CHANNELS in .env first")

    channels = normalize_channels(channels)
    session_name = get_pyrogram_session_name(settings.telegram_session_name)
    client = create_userbot_client(settings)

    await client.connect()
    try:
        me = await client.get_me()
        if me is None:
            raise RuntimeError(
                f"Telegram session {session_name}.session is not authorized. "
                "Run scripts/telegram_login.py first"
            )

        print(f"Testing {len(channels)} channel(s)")
        for channel in channels:
            chat = await client.get_chat(channel)
            messages = [message async for message in client.get_chat_history(chat.id, limit=3)]
            print(f"{channel}: resolved as {chat.title!r}, latest_messages={len(messages)}")
    finally:
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
