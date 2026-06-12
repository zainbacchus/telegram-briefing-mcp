"""Time-window parsing: correctness and timezone behavior.

Pure logic only — no network, no auth. `now` is pinned so relative windows are
deterministic regardless of when/where the tests run.
"""

from datetime import datetime, timedelta, timezone

import pytest

from telegram_briefing_mcp.windows import Window, WindowError, resolve_window

NOW = datetime(2026, 6, 9, 12, 0, 0, tzinfo=timezone.utc)


def _cutoff(**kw):
    return resolve_window(now=NOW, **kw).cutoff


# --- named rolling windows --------------------------------------------------
def test_default_is_last_day():
    win = resolve_window(now=NOW)
    assert win.kind == "since"
    assert win.cutoff == NOW - timedelta(days=1)
    assert win.until is None


def test_bare_week_and_month_and_hour():
    assert _cutoff(window="week") == NOW - timedelta(days=7)
    assert _cutoff(window="month") == NOW - timedelta(days=30)
    assert _cutoff(window="hour") == NOW - timedelta(hours=1)


def test_numeric_unit_specs():
    assert _cutoff(window="36h") == NOW - timedelta(hours=36)
    assert _cutoff(window="3d") == NOW - timedelta(days=3)
    assert _cutoff(window="2w") == NOW - timedelta(weeks=2)


def test_spacing_and_case_insensitive():
    assert _cutoff(window=" 12 Hours ") == NOW - timedelta(hours=12)


# --- special windows --------------------------------------------------------
def test_unread_and_all():
    assert resolve_window("unread", now=NOW).kind == "unread"
    assert resolve_window("all", now=NOW).kind == "all"
    assert resolve_window("everything", now=NOW).kind == "all"
    assert resolve_window("all", now=NOW).cutoff is None


def test_today_is_since_local_midnight():
    win = resolve_window("today", now=NOW)
    assert win.kind == "since"
    assert win.cutoff is not None
    # Local midnight is in the recent past relative to noon-UTC now, for any tz.
    assert win.cutoff <= NOW
    assert NOW - win.cutoff < timedelta(days=2)


def test_yesterday_is_bounded():
    win = resolve_window("yesterday", now=NOW)
    assert win.kind == "since"
    assert win.cutoff is not None and win.until is not None
    assert win.until - win.cutoff == timedelta(days=1)


# --- explicit numeric + ISO bounds + precedence -----------------------------
def test_hours_and_days_params():
    assert _cutoff(days=3) == NOW - timedelta(days=3)
    assert _cutoff(hours=6) == NOW - timedelta(hours=6)
    assert _cutoff(days=1, hours=12) == NOW - timedelta(days=1, hours=12)


def test_since_until_iso_bounds():
    win = resolve_window(
        since="2026-06-01T00:00:00+00:00",
        until="2026-06-05T00:00:00+00:00",
        now=NOW,
    )
    assert win.kind == "since"
    assert win.cutoff == datetime(2026, 6, 1, tzinfo=timezone.utc)
    assert win.until == datetime(2026, 6, 5, tzinfo=timezone.utc)


def test_since_overrides_named_window():
    win = resolve_window("week", since="2026-06-08T00:00:00+00:00", now=NOW)
    assert win.cutoff == datetime(2026, 6, 8, tzinfo=timezone.utc)


def test_hours_overrides_named_window():
    win = resolve_window("week", hours=2, now=NOW)
    assert win.cutoff == NOW - timedelta(hours=2)


# --- errors -----------------------------------------------------------------
def test_until_before_since_raises():
    with pytest.raises(WindowError):
        resolve_window(
            since="2026-06-05T00:00:00+00:00",
            until="2026-06-01T00:00:00+00:00",
            now=NOW,
        )


def test_unparseable_window_raises():
    with pytest.raises(WindowError):
        resolve_window("whenever", now=NOW)


def test_zero_duration_raises():
    with pytest.raises(WindowError):
        resolve_window(hours=0, now=NOW)


def test_bad_iso_raises():
    with pytest.raises(WindowError):
        resolve_window(since="not-a-date", now=NOW)


# --- Window.contains --------------------------------------------------------
def test_contains_respects_bounds():
    win = resolve_window(
        since="2026-06-01T00:00:00+00:00",
        until="2026-06-05T00:00:00+00:00",
        now=NOW,
    )
    assert win.contains(datetime(2026, 6, 3, tzinfo=timezone.utc))
    assert not win.contains(datetime(2026, 5, 31, tzinfo=timezone.utc))
    assert not win.contains(datetime(2026, 6, 6, tzinfo=timezone.utc))


def test_contains_open_ended():
    win = resolve_window(window="day", now=NOW)
    assert win.contains(NOW)
    assert not win.contains(NOW - timedelta(days=2))
