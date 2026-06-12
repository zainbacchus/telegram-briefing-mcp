"""Telethon client construction and connection lifecycle.

The MCP server is read-only and short-lived per call, so we connect, do the work,
and disconnect inside an async context manager (mirroring the sibling project's
``_client()`` pattern). The session is loaded from the secure store as a Telethon
``StringSession`` — an in-memory session, so nothing sensitive is written to a
SQLite session file on disk.

``NotAuthenticatedError`` is raised (rather than triggering an interactive login)
if no valid session exists, because login must happen in a terminal via
``telegram-auth login``, never implicitly during a tool call.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from telethon import TelegramClient
from telethon.sessions import StringSession

from .config import Settings, load_settings
from .sessionstore import SessionStore


class NotAuthenticatedError(RuntimeError):
    """No usable Telegram session is stored."""


def _login_hint() -> str:
    return (
        "Not authenticated. Run `telegram-auth login` once in a terminal to sign "
        "in (phone number -> login code -> optional 2FA password)."
    )


@asynccontextmanager
async def connected_client(settings: Settings | None = None):
    """Yield a connected, authorized Telethon client; disconnect on exit.

    Raises NotAuthenticatedError if there is no stored session or the stored
    session is no longer authorized (e.g. it was revoked from another device).
    """
    settings = settings or load_settings()
    session_string = SessionStore(settings.state_dir).load()
    if not session_string:
        raise NotAuthenticatedError(_login_hint())

    client = TelegramClient(
        StringSession(session_string), settings.api_id, settings.api_hash
    )
    await client.connect()
    try:
        if not await client.is_user_authorized():
            raise NotAuthenticatedError(
                "Stored Telegram session is no longer authorized (it may have been "
                "revoked). Run `telegram-auth login` again to re-authenticate."
            )
        yield client
    finally:
        await client.disconnect()
