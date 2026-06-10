import asyncio
import getpass

import qrcode
from telethon.errors import PasswordHashInvalidError, SessionPasswordNeededError

from app.common.config import get_settings
from app.services.telegram_userbot_telethon import (
    create_telethon_client,
    get_telethon_session_name,
)


def print_ascii_qr(url: str) -> None:
    qr = qrcode.QRCode(border=1)
    qr.add_data(url)
    qr.make(fit=True)
    qr.print_ascii(invert=True)


async def complete_two_factor_auth(client: object, session_name: str) -> None:
    password = getpass.getpass("Telegram 2FA password: ")
    try:
        await client.sign_in(password=password)
    except PasswordHashInvalidError as exc:
        raise RuntimeError("Telegram 2FA password is invalid") from exc
    print(f"Telegram session authorized: {session_name}.session")


async def main(timeout_seconds: int = 180) -> None:
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

        qr_login = await client.qr_login()
        print("Scan this QR in Telegram: Settings -> Devices -> Link Desktop Device")
        print_ascii_qr(qr_login.url)
        print(qr_login.url)

        try:
            await qr_login.wait(timeout=timeout_seconds)
        except SessionPasswordNeededError:
            await complete_two_factor_auth(client, session_name)
            return

        print(f"Telegram session authorized: {session_name}.session")
    finally:
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
