import asyncio
import base64
import getpass
import time

import qrcode
from pyrogram.errors import PasswordHashInvalid, SessionPasswordNeeded
from pyrogram.raw.functions.auth import ExportLoginToken
from pyrogram.raw.types.auth import LoginToken, LoginTokenMigrateTo, LoginTokenSuccess

from app.common.config import get_settings
from app.services.telegram_userbot import create_userbot_client, get_pyrogram_session_name


def build_qr_url(token: bytes) -> str:
    encoded_token = base64.urlsafe_b64encode(token).decode("ascii").rstrip("=")
    return f"tg://login?token={encoded_token}"


def print_ascii_qr(url: str) -> None:
    qr = qrcode.QRCode(border=1)
    qr.add_data(url)
    qr.make(fit=True)
    qr.print_ascii(invert=True)


async def complete_two_factor_auth(client: object, session_name: str) -> None:
    password = getpass.getpass("Telegram 2FA password: ")
    try:
        await client.check_password(password)
    except PasswordHashInvalid as exc:
        raise RuntimeError("Telegram 2FA password is invalid") from exc
    print(f"Telegram session authorized: {session_name}.session")


async def export_login_token(settings: object, client: object) -> object:
    return await client.invoke(
        ExportLoginToken(
            api_id=settings.telegram_api_id,
            api_hash=settings.telegram_api_hash,
            except_ids=[],
        )
    )


async def wait_for_qr_login(timeout_seconds: int = 180) -> None:
    settings = get_settings()
    if not settings.telegram_api_id or settings.telegram_api_hash == "replace-me":
        raise RuntimeError("Set TELEGRAM_API_ID and TELEGRAM_API_HASH in .env first")

    session_name = get_pyrogram_session_name(settings.telegram_session_name)
    client = create_userbot_client(settings)

    await client.connect()
    try:
        try:
            me = await client.get_me()
            if me is not None:
                print(f"Telegram session is already authorized: {session_name}.session")
                return
        except Exception:
            pass

        exported = await export_login_token(settings, client)
        if isinstance(exported, LoginTokenMigrateTo):
            raise RuntimeError(
                "Telegram requested DC migration for QR login. "
                "Use scripts/telegram_login.py for this account."
            )
        if not isinstance(exported, LoginToken):
            raise RuntimeError(f"Unexpected Telegram QR response: {exported.__class__.__name__}")

        url = build_qr_url(exported.token)
        print("Scan this QR in Telegram: Settings -> Devices -> Link Desktop Device")
        print_ascii_qr(url)
        print(url)

        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            await asyncio.sleep(3)
            try:
                result = await export_login_token(settings, client)
            except SessionPasswordNeeded:
                await complete_two_factor_auth(client, session_name)
                return
            if isinstance(result, LoginTokenSuccess):
                print(f"Telegram session authorized: {session_name}.session")
                return
            if isinstance(result, LoginToken) and result.token != exported.token:
                exported = result
                url = build_qr_url(exported.token)
                print("QR refreshed. Scan the latest QR:")
                print_ascii_qr(url)
                print(url)

        raise TimeoutError("QR login timeout. Run the script again to generate a fresh QR.")
    finally:
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(wait_for_qr_login())
