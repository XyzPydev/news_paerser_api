import asyncio
import getpass
import re

from telethon import TelegramClient
from telethon.errors import (
    FloodWaitError,
    PasswordHashInvalidError,
    RPCError,
    SessionPasswordNeededError,
)

from app.common.config import get_settings


def describe_code_delivery(sent_code: object) -> dict[str, object]:
    code_type = getattr(sent_code, "type", None)
    next_type = getattr(sent_code, "next_type", None)
    timeout = getattr(sent_code, "timeout", None)

    return {
        "type": code_type.__class__.__name__ if code_type else None,
        "next_type": next_type.__class__.__name__ if next_type else None,
        "timeout": timeout,
    }


def normalize_phone(raw: str) -> str:
    """Strip everything except digits and leading '+'."""
    digits = re.sub(r"[^\d+]", "", raw)
    if not digits.startswith("+"):
        digits = "+" + digits
    return digits


async def main() -> None:
    settings = get_settings()
    if not settings.telegram_api_id or settings.telegram_api_hash == "replace-me":
        raise RuntimeError("Set TELEGRAM_API_ID and TELEGRAM_API_HASH in .env first")

    # Use default Telethon device parameters — custom ones can cause
    # Telegram to silently suppress code delivery.
    client = TelegramClient(
        settings.telegram_session_name,
        settings.telegram_api_id,
        settings.telegram_api_hash,
    )

    await client.connect()
    try:
        if await client.is_user_authorized():
            print("✅ Telegram session is already authorized")
            return

        raw_phone = input("Telegram phone number, international format: ").strip()
        phone = normalize_phone(raw_phone)
        print(f"Normalized phone: {phone}")

        try:
            sent_code = await client.send_code_request(phone)
        except FloodWaitError as exc:
            print(f"⛔ Flood wait: need to wait {exc.seconds} seconds before retrying")
            raise

        delivery = describe_code_delivery(sent_code)
        print(f"📨 Code delivery: {delivery}")

        if delivery["type"] == "SentCodeTypeApp":
            print(
                "\n⚠️  Code was sent IN-APP (not SMS).\n"
                "   Look for a message from 'Telegram' in your Telegram chats.\n"
                "   It might be in 'Service Notifications'.\n"
            )
            resend = input("Didn't receive it? Try resend via SMS? (y/n): ").strip().lower()
            if resend == "y":
                try:
                    sent_code = await client.send_code_request(phone, force_sms=True)
                    delivery = describe_code_delivery(sent_code)
                    print(f"📨 Resend delivery: {delivery}")
                except FloodWaitError as exc:
                    print(f"⛔ Flood wait: need to wait {exc.seconds} seconds")
                    raise
                except RPCError as exc:
                    print(f"⚠️  Resend failed: {exc.__class__.__name__}: {exc}")

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

        print("✅ Telegram session authorized")
    finally:
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
