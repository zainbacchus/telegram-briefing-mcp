"""One-time interactive login + session management (the `telegram-auth` CLI).

Telegram user-account login is interactive by nature: you enter your phone
number, Telegram sends a login code to your existing Telegram apps, you type it
back, and — if you have two-step verification enabled — your 2FA password. This
must happen in a terminal, never implicitly during an MCP tool call, so it lives
here as its own console script.

On success we persist the Telethon ``StringSession`` via the secure
:class:`~telegram_briefing_mcp.sessionstore.SessionStore`. The session string is
a full account credential: it is stored encrypted (OS keyring / Fernet fallback)
and is *never* printed or logged.

    telegram-auth login     # sign in (or re-sign-in)
    telegram-auth status    # show whether/who is logged in
    telegram-auth logout     # revoke locally and clear the stored session
"""

from __future__ import annotations

import asyncio
import getpass
import sys

from telethon import TelegramClient
from telethon.errors import (
    FloodWaitError,
    PhoneCodeExpiredError,
    PhoneCodeInvalidError,
    PhoneNumberInvalidError,
    SessionPasswordNeededError,
)
from telethon.sessions import StringSession

from .config import Settings, load_settings
from .sessionstore import SessionStore

_MAX_CODE_ATTEMPTS = 3
_MAX_PASSWORD_ATTEMPTS = 3


class AuthError(RuntimeError):
    """Raised when login fails."""


def _account_label(me) -> str:
    first = getattr(me, "first_name", None) or ""
    last = getattr(me, "last_name", None) or ""
    name = f"{first} {last}".strip() or "(no name)"
    username = getattr(me, "username", None)
    handle = f" @{username}" if username else ""
    return f"{name}{handle}"


async def _login(settings: Settings) -> str:
    """Run the interactive login; return the saved account label. The session is
    persisted as a side effect. Never returns or prints the session string."""
    client = TelegramClient(StringSession(), settings.api_id, settings.api_hash)
    await client.connect()
    try:
        phone = settings.phone or input("Phone number (international, e.g. +14155550123): ").strip()
        if not phone:
            raise AuthError("No phone number provided.")

        try:
            await client.send_code_request(phone)
        except PhoneNumberInvalidError as e:
            raise AuthError(f"Telegram rejected the phone number {phone!r} as invalid.") from e
        except FloodWaitError as e:
            raise AuthError(f"Rate-limited by Telegram; try again in {e.seconds}s.") from e

        print("\nA login code was sent to your Telegram app (check your other devices).")

        for attempt in range(1, _MAX_CODE_ATTEMPTS + 1):
            code = input("Login code: ").strip()
            try:
                await client.sign_in(phone=phone, code=code)
                break
            except SessionPasswordNeededError:
                # Two-step verification is on; ask for the password (never echoed).
                for pw_attempt in range(1, _MAX_PASSWORD_ATTEMPTS + 1):
                    password = getpass.getpass("Two-step verification password: ")
                    try:
                        await client.sign_in(password=password)
                        break
                    except Exception:
                        if pw_attempt == _MAX_PASSWORD_ATTEMPTS:
                            raise AuthError("Incorrect 2FA password.")
                        print("Incorrect password, try again.")
                break
            except PhoneCodeInvalidError:
                if attempt == _MAX_CODE_ATTEMPTS:
                    raise AuthError("Login code was invalid too many times.")
                print("Invalid code, try again.")
            except PhoneCodeExpiredError as e:
                raise AuthError("Login code expired. Run `telegram-auth login` again.") from e

        if not await client.is_user_authorized():
            raise AuthError("Login did not complete (not authorized).")

        session_string = client.session.save()
        SessionStore(settings.state_dir).save(session_string)
        me = await client.get_me()
        return _account_label(me)
    finally:
        await client.disconnect()


async def _status(settings: Settings) -> int:
    store = SessionStore(settings.state_dir)
    session_string = store.load()
    if not session_string:
        print("Not authenticated. Run `telegram-auth login`.")
        return 1
    client = TelegramClient(StringSession(session_string), settings.api_id, settings.api_hash)
    await client.connect()
    try:
        if not await client.is_user_authorized():
            print("Stored session exists but is no longer authorized (revoked?). Run `telegram-auth login`.")
            return 1
        me = await client.get_me()
        print(f"Authenticated as {_account_label(me)}.")
        return 0
    finally:
        await client.disconnect()


async def _logout(settings: Settings) -> None:
    """Revoke the session server-side (best effort), then clear it locally."""
    store = SessionStore(settings.state_dir)
    session_string = store.load()
    if session_string:
        client = TelegramClient(StringSession(session_string), settings.api_id, settings.api_hash)
        try:
            await client.connect()
            if await client.is_user_authorized():
                await client.log_out()
        except Exception:
            pass  # even if the server-side revoke fails, still clear locally
        finally:
            await client.disconnect()
    store.clear()


def cli_main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    cmd = args[0] if args else "login"
    if cmd in ("-h", "--help", "help"):
        print("Usage: telegram-auth [login|status|logout]")
        return 0
    try:
        settings = load_settings()
    except RuntimeError as e:
        print(f"Configuration error: {e}", file=sys.stderr)
        return 1

    try:
        if cmd == "login":
            label = asyncio.run(_login(settings))
            print(
                f"\nLogged in as {label}.\n"
                "Session stored securely in your OS keyring (or encrypted fallback). "
                "It was not printed anywhere."
            )
            return 0
        if cmd == "status":
            return asyncio.run(_status(settings))
        if cmd == "logout":
            asyncio.run(_logout(settings))
            print("Logged out; stored session cleared.")
            return 0
    except AuthError as e:
        print(f"Login failed: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:  # pragma: no cover
        print("\nAborted.", file=sys.stderr)
        return 130

    print(f"Unknown command: {cmd!r}. Use one of: login, status, logout.")
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(cli_main())
