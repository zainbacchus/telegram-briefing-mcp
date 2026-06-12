"""Time-window parsing for message selection.

Pure, dependency-free, and timezone-correct so it can be unit-tested without any
network or auth. A :class:`Window` describes *which* messages a fetch should
keep, in one of three shapes:

  * ``since``  -> keep messages with date in [cutoff, until]; ``until`` may be
    ``None`` (open-ended, "up to now"). This covers "last day", "last week",
    "today", a custom rolling window, or an explicit date range.
  * ``unread`` -> keep messages newer than each chat's read marker (resolved
    per-chat later, since the boundary differs by conversation).
  * ``all``    -> no time bound (capped only by an explicit message limit).

All cutoffs are returned as timezone-aware UTC datetimes, because Telethon yields
aware UTC message dates and comparing aware-to-aware is unambiguous. Relative
windows are measured from ``now``; ``today`` is measured from local midnight.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

# Named windows that don't reduce to a simple <n><unit> rolling delta.
_SPECIAL = {"unread", "all", "everything", "today", "yesterday"}

# Unit -> seconds. Months are approximated as 30 days (calendar months are not a
# fixed length; for a briefing window this approximation is intended and fine).
_UNIT_SECONDS = {
    "h": 3600,
    "hour": 3600,
    "hours": 3600,
    "d": 86400,
    "day": 86400,
    "days": 86400,
    "w": 604800,
    "week": 604800,
    "weeks": 604800,
    "m": 2592000,
    "month": 2592000,
    "months": 2592000,
}

# Bare names that imply a count of 1 (e.g. "day" == "1d", "week" == "1w").
_BARE_DELTA = {
    "hour": "h",
    "day": "d",
    "week": "w",
    "month": "m",
}

_NUM_UNIT_RE = re.compile(r"^\s*(\d+)\s*([a-zA-Z]+)\s*$")


class WindowError(ValueError):
    """Raised when a window specification can't be understood."""


@dataclass(frozen=True)
class Window:
    kind: str  # "since" | "unread" | "all"
    cutoff: datetime | None  # aware UTC; lower bound for kind == "since"
    until: datetime | None  # aware UTC; optional upper bound for kind == "since"
    label: str  # human-readable description, surfaced in tool output

    def contains(self, when: datetime) -> bool:
        """Whether an aware datetime falls inside a 'since' window's bounds.

        Only meaningful for kind == 'since'; 'unread'/'all' are resolved elsewhere.
        """
        if self.cutoff is not None and when < self.cutoff:
            return False
        if self.until is not None and when > self.until:
            return False
        return True


def _now_utc(now: datetime | None) -> datetime:
    if now is None:
        return datetime.now(timezone.utc)
    if now.tzinfo is None:
        return now.replace(tzinfo=timezone.utc)
    return now.astimezone(timezone.utc)


def _parse_iso(value: str) -> datetime:
    """Parse an ISO-8601 date or datetime. Naive values are assumed local time
    and converted to UTC (a user typing '2026-06-01' means their local day)."""
    text = value.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError as e:
        raise WindowError(
            f"Could not parse {value!r} as a date/time. Use ISO-8601, e.g. "
            "'2026-06-01' or '2026-06-01T09:30'."
        ) from e
    if dt.tzinfo is None:
        dt = dt.astimezone()  # interpret as local time
    return dt.astimezone(timezone.utc)


def _rolling(spec: str, now_utc: datetime) -> tuple[datetime, str] | None:
    """Resolve a '<n><unit>' or bare-unit spec to (cutoff, label). None if not one."""
    bare = spec.strip().lower()
    if bare in _BARE_DELTA:
        n, unit_key = 1, _BARE_DELTA[bare]
    else:
        match = _NUM_UNIT_RE.match(bare)
        if not match:
            return None
        n = int(match.group(1))
        unit_key = match.group(2)
    seconds = _UNIT_SECONDS.get(unit_key)
    if seconds is None:
        return None
    cutoff = now_utc - timedelta(seconds=n * seconds)
    unit_name = {"h": "hour", "d": "day", "w": "week", "m": "month"}.get(unit_key[0], unit_key)
    plural = "" if n == 1 else "s"
    return cutoff, f"last {n} {unit_name}{plural}"


def resolve_window(
    window: str = "day",
    *,
    hours: int | None = None,
    days: int | None = None,
    since: str | None = None,
    until: str | None = None,
    now: datetime | None = None,
) -> Window:
    """Build a :class:`Window` from the various ways a caller can express one.

    Precedence (most explicit wins):
      1. ``since`` / ``until`` ISO bounds, if either is given.
      2. ``hours`` / ``days`` numeric rolling window, if either is given.
      3. the named ``window`` string (default 'day').

    Recognized ``window`` values: 'day'/'today'/'yesterday', 'week', 'month',
    'hour', any '<n><unit>' (e.g. '36h', '3d', '2w'), 'unread', 'all'.
    """
    now_utc = _now_utc(now)

    # 1. Explicit ISO bounds.
    if since is not None or until is not None:
        cutoff = _parse_iso(since) if since else None
        upper = _parse_iso(until) if until else None
        if cutoff and upper and upper < cutoff:
            raise WindowError("'until' is earlier than 'since'.")
        bits = []
        if cutoff:
            bits.append(f"since {cutoff.isoformat()}")
        if upper:
            bits.append(f"until {upper.isoformat()}")
        return Window("since", cutoff, upper, " ".join(bits) or "all time")

    # 2. Numeric rolling window.
    if hours is not None or days is not None:
        total = (hours or 0) * 3600 + (days or 0) * 86400
        if total <= 0:
            raise WindowError("hours/days must be positive.")
        cutoff = now_utc - timedelta(seconds=total)
        parts = []
        if days:
            parts.append(f"{days} day{'' if days == 1 else 's'}")
        if hours:
            parts.append(f"{hours} hour{'' if hours == 1 else 's'}")
        return Window("since", cutoff, None, "last " + " ".join(parts))

    # 3. Named window.
    spec = (window or "day").strip().lower()
    if spec in ("all", "everything"):
        return Window("all", None, None, "all messages")
    if spec == "unread":
        return Window("unread", None, None, "unread")
    if spec == "today":
        local_midnight = now_utc.astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
        return Window("since", local_midnight.astimezone(timezone.utc), None, "today")
    if spec == "yesterday":
        local_midnight = now_utc.astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
        start = (local_midnight - timedelta(days=1)).astimezone(timezone.utc)
        end = local_midnight.astimezone(timezone.utc)
        return Window("since", start, end, "yesterday")

    rolling = _rolling(spec, now_utc)
    if rolling is not None:
        cutoff, label = rolling
        return Window("since", cutoff, None, label)

    raise WindowError(
        f"Unrecognized window {window!r}. Try 'day', 'today', 'week', 'month', "
        "'unread', 'all', or a duration like '36h', '3d', '2w'."
    )
