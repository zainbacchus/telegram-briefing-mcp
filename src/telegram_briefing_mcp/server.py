"""MCP server exposing a read-only Telegram briefing toolkit.

Design principles encoded in the tool surface:
  * READ-ONLY. There is no tool that sends, edits, deletes, marks-read, joins,
    or leaves anything. The connector observes; it never acts on your account.
  * Time windows are first-class. Every read tool accepts the same window
    vocabulary ('day', 'today', 'week', 'month', 'unread', 'all', or a custom
    '<n><unit>' / ISO date range) so "pull the last day / week / unread" is one
    consistent idea across tools. Window math lives in windows.py.
  * Login is never implicit. Tools report an actionable error pointing at
    `telegram-auth login` rather than starting an interactive login mid-call.

Run with: `telegram-briefing-mcp` (stdio transport, for Claude Desktop / clients).
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from . import briefing as briefing_mod
from .auth import _account_label
from .client import connected_client
from .config import load_settings
from .sessionstore import SessionStore
from .windows import resolve_window

mcp = FastMCP("telegram-briefing")


def _err(e: Exception) -> dict:
    return {"error": type(e).__name__, "message": str(e)}


def _include_flags(dms: bool, groups: bool, channels: bool, bots: bool) -> dict[str, bool]:
    return {"dm": dms, "group": groups, "channel": channels, "bot": bots}


# --- auth / status ----------------------------------------------------------
@mcp.tool()
async def telegram_auth_status() -> dict:
    """Report whether a Telegram session is stored and still authorized, and which
    account it belongs to. Does NOT trigger a login — signing in is a one-time
    terminal step (`telegram-auth login`)."""
    try:
        settings = load_settings()
    except Exception as e:
        return _err(e)
    if not SessionStore(settings.state_dir).exists():
        return {
            "authenticated": False,
            "how_to_fix": "Run `telegram-auth login` once in a terminal to sign in.",
        }
    try:
        async with connected_client(settings) as client:
            me = await client.get_me()
            return {"authenticated": True, "account": _account_label(me)}
    except Exception as e:
        return _err(e)


# --- chat listing -----------------------------------------------------------
@mcp.tool()
async def list_chats(
    limit: int = 50,
    only_unread: bool = False,
    include_archived: bool = False,
    kinds: list[str] | None = None,
) -> dict:
    """List your chats (conversations) with metadata only — no message bodies.

    Each entry has: name, id, kind ('dm' | 'group' | 'channel' | 'bot'), username,
    unread count, last-message timestamp, pinned/archived flags. Use this to see
    what exists and where the unread volume is before pulling messages. Sorted by
    most recent activity. `kinds` optionally filters (e.g. ['dm','group'])."""
    try:
        wanted = set(kinds) if kinds else None
        async with connected_client() as client:
            chats = []
            async for dialog in client.iter_dialogs(limit=max(limit * 3, limit)):
                summary = briefing_mod.summarize_dialog(dialog)
                if only_unread and not summary["unread"]:
                    continue
                if not include_archived and summary["archived"]:
                    continue
                if wanted and summary["kind"] not in wanted:
                    continue
                chats.append(summary)
                if len(chats) >= limit:
                    break
        chats.sort(key=lambda c: c.get("last_message_date") or "", reverse=True)
        return {"chat_count": len(chats), "chats": chats}
    except Exception as e:
        return _err(e)


# --- the briefing centerpiece ----------------------------------------------
@mcp.tool()
async def get_briefing(
    window: str = "day",
    hours: int | None = None,
    days: int | None = None,
    since: str | None = None,
    until: str | None = None,
    include_dms: bool = True,
    include_groups: bool = True,
    include_channels: bool = False,
    include_bots: bool = False,
    include_archived: bool = False,
    max_chats: int = 50,
    max_messages_per_chat: int = 50,
) -> dict:
    """Pull all relevant messages across your chats for a time window and group
    them by conversation — the raw material for an executive briefing.

    WINDOW (pick the most convenient; precedence: since/until > hours/days > window):
      * window: 'day' (last 24h, default), 'today' (since local midnight),
        'yesterday', 'week', 'month', 'unread' (only unread messages), 'all', or a
        duration like '36h', '3d', '2w'.
      * hours / days: a custom rolling window (e.g. days=3).
      * since / until: explicit ISO bounds (e.g. since='2026-06-01').

    SCOPE: by default includes your DMs and groups. Broadcast channels and bot
    chats are excluded as noise — set include_channels / include_bots to add them.
    Archived chats are excluded unless include_archived=True.

    Returns one block per chat (name, kind, unread, messages in chronological
    order), sorted most-relevant-first. Chats with no messages in the window are
    omitted. `max_chats` and `max_messages_per_chat` bound the payload size."""
    try:
        win = resolve_window(window, hours=hours, days=days, since=since, until=until)
        include = _include_flags(include_dms, include_groups, include_channels, include_bots)
        async with connected_client() as client:
            return await briefing_mod.build_briefing(
                client,
                win,
                include=include,
                include_archived=include_archived,
                max_chats=max_chats,
                max_messages_per_chat=max_messages_per_chat,
            )
    except Exception as e:
        return _err(e)


# --- single-chat fetch ------------------------------------------------------
@mcp.tool()
async def fetch_messages(
    chat: str,
    window: str = "day",
    hours: int | None = None,
    days: int | None = None,
    since: str | None = None,
    until: str | None = None,
    limit: int = 50,
) -> dict:
    """Pull in-window messages from ONE chat, in chronological order.

    `chat` accepts a @username, numeric id, phone number, t.me link, or a
    (case-insensitive) match against your chat titles. The window vocabulary is
    identical to get_briefing ('day', 'today', 'week', 'unread', 'all', '<n><unit>',
    or since/until ISO bounds). `limit` caps how many messages are returned."""
    try:
        win = resolve_window(window, hours=hours, days=days, since=since, until=until)
        async with connected_client() as client:
            return await briefing_mod.fetch_chat_messages(client, chat, win, limit=limit)
    except Exception as e:
        return _err(e)


# --- search -----------------------------------------------------------------
@mcp.tool()
async def search_messages(query: str, chat: str | None = None, limit: int = 50) -> dict:
    """Full-text search your message history for `query`. With no `chat`, searches
    globally across all your chats; with a `chat` (username / id / link / title),
    searches only that conversation. Each result includes which chat it came from.
    Useful for briefings like "anything about the Q3 launch this week?"."""
    try:
        async with connected_client() as client:
            return await briefing_mod.search_messages(client, query, chat_ref=chat, limit=limit)
    except Exception as e:
        return _err(e)


def main() -> None:
    mcp.run()


if __name__ == "__main__":  # pragma: no cover
    main()
