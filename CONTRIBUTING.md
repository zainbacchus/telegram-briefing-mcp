# Contributing

Thanks for your interest in `telegram-briefing-mcp`.

## Project shape

```
src/telegram_briefing_mcp/
  config.py        # env -> Settings (api_id / api_hash), per-user state dir
  sessionstore.py  # secure storage for the Telethon session (keyring + Fernet fallback)
  auth.py          # `telegram-auth` CLI: interactive login / status / logout
  client.py        # connected_client(): async context manager, fails closed if unauthenticated
  windows.py       # pure time-window parsing ('day'/'week'/'unread'/'<n><unit>'/ISO)
  briefing.py      # read-only message fetch + briefing assembly + search
  server.py        # FastMCP tool surface (read-only)
tests/
  test_windows.py            # window logic (no network)
  test_briefing_helpers.py   # message/dialog serialization (no network)
```

## Dev setup

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
.venv/bin/python -m pytest
```

## Conventions

- **Read-only.** Do not add tools that send, edit, delete, mark-read, join, or
  leave. The value proposition is a safe, observe-only briefing connector; any
  write capability is a deliberate scope change, not a casual addition.
- **Never log or print the session string** (or any secret). It is a full
  account credential.
- **Login stays interactive and explicit** (`telegram-auth login`). Tools must
  never start a login mid-call — they report an actionable error instead.
- **Keep pure logic pure.** Time-window math (windows.py) and serialization
  helpers (briefing.py) are unit-tested without a network; preserve that.
- Every tool wraps its body and returns `{"error", "message"}` on failure
  rather than raising, so the model gets a usable result.

## Testing against a real account

The unit tests need no network. To exercise the live paths, set
`TELEGRAM_API_ID` / `TELEGRAM_API_HASH`, run `telegram-auth login`, then call the
tools through any MCP client. Use a throwaway `TELEGRAM_BRIEFING_HOME` to avoid
touching your primary stored session.
