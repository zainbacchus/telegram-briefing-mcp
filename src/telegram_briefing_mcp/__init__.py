"""Read-only Telegram briefing connector as an MCP server.

Connects to Telegram through the MTProto user API (via Telethon) — the same
protocol the official Telegram Desktop / Web clients speak — so it can read your
real conversations (DMs, groups, channels), not just bot chats. The tool surface
is deliberately READ-ONLY: it pulls messages by time window (last day / last
week / today / unread / a custom range) across your chats and assembles them into
an executive briefing. It never sends, edits, deletes, or marks anything read.

Auth is a one-time interactive step (`telegram-auth login`): phone number ->
login code -> optional 2FA password. The resulting Telethon session string is a
full account credential and is stored exactly like a secret — in the OS keyring,
with an encrypted file fallback. It is never printed or logged. See sessionstore.py.
"""

__version__ = "0.1.0"
