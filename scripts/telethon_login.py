import asyncio
import getpass

from telethon.errors import PasswordHashInvalidError, RPCError, SessionPasswordNeededError

from app.common.config import get_settings
from app.services.telegram_userbot_telethon import (
    create_telethon_client,
    get_telethon_session_name,
)


def describe_code_delivery(sent_code: object) -> dict[str, object]:
    code_type = getattr(sent_code, "type", None)
    next_type = getattr(sent_code, "next_type", None)
    timeout = getattr(sent_code, "timeout", None)

    return {
        "type": code_type.__class__.__name__ if code_type else None,
        "next_type": next_type.__class__.__name__ if next_type else None,
        "timeout": timeout,
    }


async def main() -> None:
    settings = get_settings()
    if not settings.telegram_api_id or settings.telegram_api_hash == "replace-me":
        raise RuntimeError("Set TELEGRAM_API_ID and TELEGRAM_API_HASH in .env first")

    session_name = get_telethon_session_name(settings.telegram_session_name)
    client = create_telethon_client(settings)

    await client.connect()
    try:
        if await client.is_user_authorized():
            print(f"Telegram session is already authorized: {session_name}.session")
            return

        phone = input("Telegram phone number, international format: ").strip()
        sent_code = await client.send_code_request(phone)
        print({"code_delivery": describe_code_delivery(sent_code)})
        code = input("Telegram login code: ").strip()

        try:
            await client.sign_in(phone=phone, code=code)
        except SessionPasswordNeededError:
            password = getpass.getpass("Telegram 2FA password: ")
            try:
                await client.sign_in(password=password)
            except PasswordHashInvalidError as exc:
                raise RuntimeError("Telegram 2FA password is invalid") from exc
        except RPCError as exc:
            raise RuntimeError(f"Telegram RPC error: {exc.__class__.__name__}: {exc}") from exc

        print(f"Telegram session authorized: {session_name}.session")
    finally:
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
