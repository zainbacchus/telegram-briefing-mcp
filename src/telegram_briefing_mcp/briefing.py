"""Reading and shaping Telegram messages into briefing-ready data.

Everything here is read-only. The functions take a connected Telethon client and
a resolved :class:`~telegram_briefing_mcp.windows.Window`, fetch messages that
fall in that window, and return plain JSON-serializable dicts (so the MCP layer
can hand them straight to the model). Time-window math lives in windows.py; this
module only applies an already-resolved window.

The central entry point is :func:`build_briefing`, which sweeps the user's chats,
pulls in-window messages from each, and groups them by conversation — the shape
an executive briefing wants ("here's what happened, per person/group").
"""

from __future__ import annotations

from typing import Any

from telethon import TelegramClient

from .windows import Window

# Safety caps so a single call can't try to pull an unbounded history.
_DEFAULT_MAX_DIALOGS = 200
_DEFAULT_MAX_PER_CHAT = 50
_DEFAULT_TRUNCATE = 4000

# Which dialog kinds a briefing includes by default: the people and groups
# talking *to you*. Broadcast channels and bot feeds tend to be noise in an
# executive briefing, so they're opt-in.
DEFAULT_INCLUDE = {"dm": True, "group": True, "channel": False, "bot": False}


# --- entity / dialog helpers ------------------------------------------------
def _display_name(entity: Any) -> str | None:
    if entity is None:
        return None
    title = getattr(entity, "title", None)
    if title:
        return title
    first = getattr(entity, "first_name", None) or ""
    last = getattr(entity, "last_name", None) or ""
    name = f"{first} {last}".strip()
    if name:
        return name
    username = getattr(entity, "username", None)
    return f"@{username}" if username else None


def _dialog_kind(dialog: Any) -> str:
    entity = dialog.entity
    if dialog.is_user:
        return "bot" if getattr(entity, "bot", False) else "dm"
    if dialog.is_group:
        return "group"
    if dialog.is_channel:
        return "channel"
    return "other"


def summarize_dialog(dialog: Any) -> dict:
    """One chat's metadata (no messages), for list_chats and briefing headers."""
    entity = dialog.entity
    return {
        "id": getattr(entity, "id", None),
        "name": dialog.name or _display_name(entity) or "Unknown",
        "kind": _dialog_kind(dialog),
        "username": getattr(entity, "username", None),
        "unread": int(getattr(dialog, "unread_count", 0) or 0),
        "last_message_date": dialog.date.isoformat() if dialog.date else None,
        "pinned": bool(getattr(dialog, "pinned", False)),
        "archived": bool(getattr(dialog, "archived", False)),
    }


# --- message helpers --------------------------------------------------------
def _media_tag(msg: Any) -> str | None:
    """A short human label for non-text content, or None for plain text."""
    try:
        if msg.photo:
            return "[photo]"
        if getattr(msg, "voice", None):
            return "[voice message]"
        if getattr(msg, "video_note", None):
            return "[video note]"
        if getattr(msg, "gif", None):
            return "[gif]"
        if msg.video:
            return "[video]"
        if getattr(msg, "audio", None):
            return "[audio]"
        if getattr(msg, "sticker", None):
            emoji = getattr(getattr(msg, "file", None), "emoji", None)
            return f"[sticker {emoji}]" if emoji else "[sticker]"
        if getattr(msg, "poll", None):
            try:
                return f"[poll: {msg.poll.poll.question}]"
            except Exception:
                return "[poll]"
        if getattr(msg, "contact", None):
            return "[contact]"
        if getattr(msg, "geo", None):
            return "[location]"
        if msg.document:
            name = getattr(getattr(msg, "file", None), "name", None)
            return f"[file: {name}]" if name else "[document]"
        if msg.media:
            return "[media]"
    except Exception:
        return "[media]"
    return None


def _service_tag(msg: Any) -> str | None:
    action = getattr(msg, "action", None)
    if action is None:
        return None
    return f"[event: {type(action).__name__.replace('MessageAction', '')}]"


def extract_message(msg: Any, *, truncate: int = _DEFAULT_TRUNCATE) -> dict:
    """Convert one Telethon message to a compact, serializable dict."""
    sender = getattr(msg, "sender", None)
    sender_name = _display_name(sender)
    text = msg.message or ""
    truncated = False
    if truncate and len(text) > truncate:
        text = text[:truncate]
        truncated = True

    out: dict[str, Any] = {
        "id": msg.id,
        "date": msg.date.isoformat() if msg.date else None,
        "from": sender_name or (str(msg.sender_id) if msg.sender_id else "Unknown"),
        "outgoing": bool(getattr(msg, "out", False)),
    }
    if text:
        out["text"] = text
    if truncated:
        out["truncated"] = True
    media = _media_tag(msg)
    if media:
        out["media"] = media
    if not text and not media:
        service = _service_tag(msg)
        if service:
            out["media"] = service
    if getattr(msg, "reply_to_msg_id", None):
        out["reply_to_id"] = msg.reply_to_msg_id
    if getattr(msg, "edit_date", None):
        out["edited"] = True
    if getattr(msg, "forward", None):
        out["forwarded"] = True
    return out


async def _iter_window_messages(
    client: TelegramClient,
    entity: Any,
    window: Window,
    *,
    limit: int,
    dialog: Any | None = None,
) -> list[Any]:
    """Fetch up to `limit` messages from one chat that match the window.

    Messages are returned newest-first as Telethon objects; the caller reverses
    them for chronological display. The hard `limit` plus the early break keep
    this bounded even for 'all' windows or very active chats.
    """
    collected: list[Any] = []

    if window.kind == "unread":
        read_max = 0
        unread_count = 0
        if dialog is not None:
            unread_count = int(getattr(dialog, "unread_count", 0) or 0)
            inner = getattr(dialog, "dialog", None)
            read_max = int(getattr(inner, "read_inbox_max_id", 0) or 0)
        kwargs: dict[str, Any] = {}
        if read_max:
            kwargs["min_id"] = read_max
        else:
            # No read marker available; fall back to the reported unread count.
            kwargs["limit"] = min(unread_count or limit, limit)
        async for msg in client.iter_messages(entity, **kwargs):
            if getattr(msg, "out", False):
                continue  # only incoming messages count as "unread"
            collected.append(msg)
            if len(collected) >= limit:
                break
        return collected

    # "since" (optionally with an upper bound) or "all".
    offset_date = window.until if (window.kind == "since" and window.until) else None
    async for msg in client.iter_messages(entity, offset_date=offset_date):
        if window.kind == "since" and window.cutoff and msg.date and msg.date < window.cutoff:
            break
        collected.append(msg)
        if len(collected) >= limit:
            break
    return collected


async def resolve_chat(client: TelegramClient, ref: str) -> Any:
    """Resolve a chat reference to a Telethon entity.

    Accepts a numeric id, an @username, a phone number, a t.me link, or — as a
    fallback — a (case-insensitive) match against your chat titles.
    """
    ref = ref.strip()
    if not ref:
        raise ValueError("Empty chat reference.")

    if ref.lstrip("-").isdigit():
        return await client.get_entity(int(ref))

    try:
        return await client.get_entity(ref)
    except Exception:
        pass  # not a username/link/phone — try matching by title below

    needle = ref.lower()
    exact: list[Any] = []
    partial: list[Any] = []
    async for dialog in client.iter_dialogs(limit=_DEFAULT_MAX_DIALOGS):
        name = (dialog.name or "").lower()
        if name == needle:
            exact.append(dialog)
        elif needle in name:
            partial.append(dialog)
    if exact:
        return exact[0].entity
    if len(partial) == 1:
        return partial[0].entity
    if len(partial) > 1:
        names = ", ".join(repr(d.name) for d in partial[:8])
        raise ValueError(f"Ambiguous chat {ref!r}; matches: {names}. Use a username or id.")
    raise ValueError(f"No chat found matching {ref!r}.")


# --- public, briefing-shaped operations -------------------------------------
async def fetch_chat_messages(
    client: TelegramClient,
    chat_ref: str,
    window: Window,
    *,
    limit: int = _DEFAULT_MAX_PER_CHAT,
    truncate: int = _DEFAULT_TRUNCATE,
) -> dict:
    """All in-window messages from a single chat, chronological."""
    entity = await resolve_chat(client, chat_ref)
    dialog = None
    if window.kind == "unread":
        async for d in client.iter_dialogs(limit=_DEFAULT_MAX_DIALOGS):
            if getattr(d.entity, "id", None) == getattr(entity, "id", None):
                dialog = d
                break
    msgs = await _iter_window_messages(client, entity, window, limit=limit, dialog=dialog)
    messages = [extract_message(m, truncate=truncate) for m in reversed(msgs)]
    return {
        "chat": _display_name(entity) or str(getattr(entity, "id", "")),
        "chat_id": getattr(entity, "id", None),
        "window": window.label,
        "message_count": len(messages),
        "messages": messages,
    }


async def build_briefing(
    client: TelegramClient,
    window: Window,
    *,
    include: dict[str, bool] | None = None,
    include_archived: bool = False,
    max_chats: int = 50,
    max_messages_per_chat: int = _DEFAULT_MAX_PER_CHAT,
    max_dialogs_scanned: int = _DEFAULT_MAX_DIALOGS,
    truncate: int = _DEFAULT_TRUNCATE,
) -> dict:
    """Sweep chats and assemble in-window messages grouped by conversation.

    Cheap pre-filters skip chats that can't contribute (wrong kind, archived,
    no unread when window is 'unread', or last activity older than the window)
    before doing the per-chat message fetch.
    """
    flags = {**DEFAULT_INCLUDE, **(include or {})}
    chats: list[dict] = []
    total_messages = 0
    scanned = 0
    skipped_by_kind = 0

    async for dialog in client.iter_dialogs(limit=max_dialogs_scanned):
        scanned += 1
        kind = _dialog_kind(dialog)
        if not flags.get(kind, False):
            skipped_by_kind += 1
            continue
        if getattr(dialog, "archived", False) and not include_archived:
            continue
        if window.kind == "unread" and not int(getattr(dialog, "unread_count", 0) or 0):
            continue
        if (
            window.kind == "since"
            and window.cutoff
            and dialog.date
            and dialog.date < window.cutoff
        ):
            continue  # newest message predates the window -> nothing to pull

        msgs = await _iter_window_messages(
            client, dialog.entity, window, limit=max_messages_per_chat, dialog=dialog
        )
        if not msgs:
            continue
        summary = summarize_dialog(dialog)
        summary["messages"] = [extract_message(m, truncate=truncate) for m in reversed(msgs)]
        summary["message_count"] = len(msgs)
        chats.append(summary)
        total_messages += len(msgs)
        if len(chats) >= max_chats:
            break

    # Most relevant first: unread windows by unread volume, else by recency.
    if window.kind == "unread":
        chats.sort(key=lambda c: c.get("unread", 0), reverse=True)
    else:
        chats.sort(key=lambda c: c.get("last_message_date") or "", reverse=True)

    return {
        "window": window.label,
        "generated_for_kinds": [k for k, v in flags.items() if v],
        "chat_count": len(chats),
        "total_messages": total_messages,
        "dialogs_scanned": scanned,
        "hit_chat_cap": len(chats) >= max_chats,
        "chats": chats,
    }


async def search_messages(
    client: TelegramClient,
    query: str,
    *,
    chat_ref: str | None = None,
    limit: int = 50,
    truncate: int = _DEFAULT_TRUNCATE,
) -> dict:
    """Full-text search, either within one chat or globally across all chats."""
    entity = await resolve_chat(client, chat_ref) if chat_ref else None
    results: list[dict] = []
    async for msg in client.iter_messages(entity, search=query, limit=limit):
        item = extract_message(msg, truncate=truncate)
        chat = getattr(msg, "chat", None)
        item["chat"] = _display_name(chat) or (str(msg.chat_id) if msg.chat_id else None)
        results.append(item)
    return {
        "query": query,
        "scope": _display_name(entity) if entity else "all chats",
        "result_count": len(results),
        "results": results,
    }
