# telegram-briefing-mcp

A **read-only Telegram connector** exposed as an [MCP](https://modelcontextprotocol.io) server. It pulls the messages you care about — **last day, last week, today, unread, or a custom range** — across your DMs, groups, and (optionally) channels, and hands them to Claude grouped by conversation, ready to fold into an executive briefing.

There's no native Telegram connector for Claude, so this fills the gap the same way the official Telegram apps do: it connects through Telegram's **MTProto user API** (via [Telethon](https://docs.telethon.dev)). That means it reads your *real* conversations — not just bot chats, which is all the Telegram Bot API can ever see.

> **Read-only by design.** There is no tool that sends, edits, deletes, marks-read, joins, or leaves anything. This connector observes; it never acts on your account.

---

## How it connects (and why not a bot)

| Approach | Can read your DMs/groups? | Notes |
|---|---|---|
| **Bot API** | ❌ | A bot only sees chats it's explicitly added to. Useless for "summarize *my* messages." |
| **MTProto user API** (this project) | ✅ | Authenticates as **you** — the same protocol Telegram Desktop / Web speak. Sees everything you see. |

You authorize once with your phone number; Telegram sends a login code to your existing app, exactly like signing in on a new device.

---

## Setup

### 1. Get your Telegram API credentials (one time, ~2 min)

1. Sign in at **https://my.telegram.org** with your phone number.
2. Open **API development tools** and create an app (any name; platform *Desktop*).
3. Copy the **`api_id`** and **`api_hash`** it shows you.

These identify the *client app* to Telegram (like the keys the official apps ship with). They are **not** your login.

### 2. Install

Requires Python ≥ 3.11.

```bash
cd telegram-briefing-mcp
python3 -m venv .venv
.venv/bin/python -m pip install -e .
```

### 3. Configure

```bash
cp .env.example .env
# edit .env and set TELEGRAM_API_ID and TELEGRAM_API_HASH
```

(Or export `TELEGRAM_API_ID` / `TELEGRAM_API_HASH` in your environment / the MCP `env` block — see below.)

### 4. Log in (one time, interactive)

```bash
.venv/bin/telegram-auth login
```

You'll enter your phone number, the login code Telegram sends to your app, and — if you use two-step verification — your 2FA password. On success the session is stored **encrypted in your OS keyring** (with a Fernet-encrypted file fallback) and is never printed.

```bash
.venv/bin/telegram-auth status    # who am I logged in as?
.venv/bin/telegram-auth logout    # revoke + clear the local session
```

### 5. Register the MCP server

Add it to your `.mcp.json` (project-level) or your Claude client's MCP config:

```json
{
  "mcpServers": {
    "telegram-briefing": {
      "command": "/absolute/path/to/telegram-briefing-mcp/.venv/bin/telegram-briefing-mcp",
      "args": [],
      "env": {
        "TELEGRAM_API_ID": "1234567",
        "TELEGRAM_API_HASH": "your_api_hash_here"
      }
    }
  }
}
```

Restart your client and the tools below appear.

---

## Tools

All tools are read-only and share the same **time-window vocabulary**.

| Tool | What it does |
|---|---|
| `telegram_auth_status` | Whether a session is stored & still authorized, and which account. Never triggers a login. |
| `list_chats` | Your conversations with metadata only (name, kind, **unread count**, last activity) — no message bodies. The map before you fetch. |
| **`get_briefing`** | **The centerpiece.** Pulls in-window messages across all relevant chats, grouped by conversation, sorted most-relevant-first. |
| `fetch_messages` | In-window messages from **one** chat (by @username, id, link, or title). |
| `search_messages` | Full-text search globally or within one chat. |

### The window vocabulary

Every read tool accepts these (precedence: `since`/`until` → `hours`/`days` → `window`):

- `window`: `"day"` (last 24h, **default**), `"today"` (since local midnight), `"yesterday"`, `"week"`, `"month"`, `"unread"` (only unread messages), `"all"`, or a duration like `"36h"`, `"3d"`, `"2w"`.
- `hours` / `days`: a custom rolling window, e.g. `days=3`.
- `since` / `until`: explicit ISO bounds, e.g. `since="2026-06-01"`.

### Scope defaults (for `get_briefing`)

By default a briefing includes your **DMs and groups** — the people and groups talking to you. Broadcast **channels** and **bot** chats are excluded as noise; enable them with `include_channels=True` / `include_bots=True`. Archived chats are excluded unless `include_archived=True`.

---

## The `telegram-brief` CLI

The same briefing, one shot, from any shell — no MCP client required:

```bash
.venv/bin/telegram-brief              # last 24h, text digest
.venv/bin/telegram-brief week         # last 7 days
.venv/bin/telegram-brief unread       # only unread messages
.venv/bin/telegram-brief 2d --json    # last 2 days, raw JSON
```

Flags: `--chats N`, `--per-chat N`, `--channels`, `--bots`, `--archived`.

---

## Using it for an executive briefing

Once registered, just ask Claude in natural language:

> *"Give me my Telegram briefing for the last day."*
> *"What's unread on Telegram right now? Group it by person and flag anything that needs a reply."*
> *"Summarize the last week of my work groups on Telegram, then add it to my morning brief."*
> *"Search my Telegram for anything about the Q3 launch this week."*

Claude calls `get_briefing` (or `search_messages`), gets the structured messages, and writes the summary. Pair it with a scheduled task to get the brief refreshed every morning — but if that task writes into a protected folder on macOS, read the scheduling note under [Limitations](#limitations) first.

---

## Security & privacy

- **Your messages stay between you, Telegram, and your MCP client.** This server makes no third-party network calls — only to Telegram's own servers.
- **The session is a credential.** A Telethon session string can act as your account until revoked. It's stored in your OS keyring (macOS Keychain / libsecret / Windows Credential Locker); if no keyring is available it falls back to a Fernet-encrypted file (`session.enc`) with the key itself kept in the keyring where possible. It is never printed or logged. `.gitignore` excludes all session/secret artifacts.
- **Revoke any time** with `telegram-auth logout`, or from Telegram → Settings → Devices.
- **Least privilege:** the tool surface is read-only on purpose. There is intentionally no send/delete/mark-read capability.

---

## Limitations

- Month windows approximate a month as 30 days (fine for briefing windows).
- Very large/active chats are bounded by `max_messages_per_chat` and a per-call `limit` so a single call can't pull unbounded history.
- Media is summarized as a tag (`[photo]`, `[file: report.pdf]`, `[voice message]`, …); the connector does not download media.
- A briefing scans up to `max_dialogs_scanned` (200) of your most recent conversations.
- **Scheduling on macOS:** if you automate a refresh with `launchd` or `cron` and it reads or writes a TCC-protected folder (`~/Documents`, `~/Desktop`, `~/Downloads`), the scheduled process needs **Full Disk Access** — otherwise it fails with `Operation not permitted` (or `exit 127` when even the script lives under a protected folder), *even though the exact same command works from your terminal*. Grant it under System Settings → Privacy & Security → Full Disk Access to the interpreter the job runs (e.g. `/bin/zsh`) or the app that launches it. Note that this grant requires admin rights and can be reset by a macOS update; if you can't grant it, run the pull on demand instead.

---

## Development

```bash
.venv/bin/python -m pip install -e ".[dev]"
.venv/bin/python -m pytest          # window-logic unit tests (no network/auth)
```

See [CONTRIBUTING.md](CONTRIBUTING.md). MIT licensed.
