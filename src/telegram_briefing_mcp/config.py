"""Configuration and constants.

Secrets are read from the environment (optionally a local .env). Nothing
sensitive is hard-coded.

The only required configuration is your Telegram *app* credentials — `api_id`
and `api_hash` from https://my.telegram.org. These identify the client app to
Telegram (the same kind of credential the official apps ship with); they are not
your login. The actual login (and the resulting session credential) is handled
separately and stored as a secret — see sessionstore.py.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# Load a local .env if present (never committed). Safe no-op if missing.
try:  # pragma: no cover - trivial
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover
    pass


def _state_dir() -> Path:
    """Per-user state dir, override with TELEGRAM_BRIEFING_HOME. Created mode 0700."""
    raw = os.environ.get("TELEGRAM_BRIEFING_HOME")
    base = Path(raw).expanduser() if raw else Path.home() / ".telegram-briefing-mcp"
    base.mkdir(parents=True, exist_ok=True)
    try:
        base.chmod(0o700)
    except OSError:  # pragma: no cover - non-posix
        pass
    return base


@dataclass(frozen=True)
class Settings:
    api_id: int
    api_hash: str
    phone: str | None
    state_dir: Path = field(default_factory=_state_dir)


def load_settings() -> Settings:
    """Read app credentials from the environment.

    Raises RuntimeError with actionable guidance if api_id / api_hash are missing
    or malformed, so misconfiguration fails loudly and locally rather than as an
    opaque Telegram error later.
    """
    raw_id = os.environ.get("TELEGRAM_API_ID", "").strip()
    api_hash = os.environ.get("TELEGRAM_API_HASH", "").strip()
    if not raw_id or not api_hash:
        raise RuntimeError(
            "TELEGRAM_API_ID and TELEGRAM_API_HASH are not set. Sign in at "
            "https://my.telegram.org, open 'API development tools', create an app, "
            "and set both values in your environment or a local .env file."
        )
    try:
        api_id = int(raw_id)
    except ValueError as e:
        raise RuntimeError(
            f"TELEGRAM_API_ID must be an integer; got {raw_id!r}."
        ) from e
    phone = os.environ.get("TELEGRAM_PHONE", "").strip() or None
    return Settings(api_id=api_id, api_hash=api_hash, phone=phone)
