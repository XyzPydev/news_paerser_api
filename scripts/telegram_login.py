import asyncio
import getpass

from pyrogram.errors import BadRequest, PasswordHashInvalid, SessionPasswordNeeded

from app.common.config import get_settings
from app.services.telegram_userbot import create_userbot_client, get_pyrogram_session_name


async def main() -> None:
    settings = get_settings()
    if not settings.telegram_api_id or settings.telegram_api_hash == "replace-me":
        raise RuntimeError("Set TELEGRAM_API_ID and TELEGRAM_API_HASH in .env first")

    session_name = get_pyrogram_session_name(settings.telegram_session_name)
    client = create_userbot_client(settings)

    await client.connect()
    try:
        me = await client.get_me()
        if me is not None:
            print(f"Telegram session is already authorized: {session_name}.session")
            return
    except Exception:
        pass

    try:
        phone = input("Telegram phone number, international format: ").strip()
        sent_code = await client.send_code(phone)
        print(
            {
                "code_delivery": {
                    "type": sent_code.type.name,
                    "next_type": sent_code.next_type.name if sent_code.next_type else None,
                    "timeout": sent_code.timeout,
                }
            }
        )
        code = input("Telegram login code: ").strip()

        try:
            await client.sign_in(phone, sent_code.phone_code_hash, code)
        except SessionPasswordNeeded:
            password = getpass.getpass("Telegram 2FA password: ")
            try:
                await client.check_password(password)
            except PasswordHashInvalid as exc:
                raise RuntimeError("Telegram 2FA password is invalid") from exc
        except BadRequest as exc:
            raise RuntimeError(f"Telegram RPC error: {exc.__class__.__name__}: {exc}") from exc

        print(f"Telegram session authorized: {session_name}.session")
    finally:
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
