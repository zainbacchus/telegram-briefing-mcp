"""Serialization helpers in briefing.py: message/dialog -> JSON-ready dicts.

These exercise the pure shaping logic with lightweight duck-typed fakes (the
project talks to Telethon objects via getattr/attribute access), so no network
or auth is needed. The live fetch/iterate paths are intentionally not covered
here — they require a real Telegram connection.
"""

from datetime import datetime, timezone

from telegram_briefing_mcp.briefing import (
    _dialog_kind,
    _display_name,
    _media_tag,
    extract_message,
    summarize_dialog,
)

DT = datetime(2026, 6, 9, 9, 30, tzinfo=timezone.utc)


class Fake:
    """Attribute bag; any unset attribute reads as None (like an absent field)."""

    def __init__(self, **kw):
        self.__dict__.update(kw)

    def __getattr__(self, name):  # only called for unset attributes
        return None


class MessageActionPinMessage:  # name mirrors a real Telethon action type
    pass


# --- _display_name ----------------------------------------------------------
def test_display_name_variants():
    assert _display_name(Fake(first_name="Ada", last_name="Lovelace")) == "Ada Lovelace"
    assert _display_name(Fake(first_name="Ada")) == "Ada"
    assert _display_name(Fake(username="ada")) == "@ada"
    assert _display_name(Fake(title="Eng Team")) == "Eng Team"
    assert _display_name(None) is None


# --- _dialog_kind -----------------------------------------------------------
def test_dialog_kind_detection():
    assert _dialog_kind(Fake(entity=Fake(), is_user=True)) == "dm"
    assert _dialog_kind(Fake(entity=Fake(bot=True), is_user=True)) == "bot"
    assert _dialog_kind(Fake(entity=Fake(), is_group=True)) == "group"
    assert _dialog_kind(Fake(entity=Fake(), is_channel=True)) == "channel"


# --- _media_tag -------------------------------------------------------------
def test_media_tag_types():
    assert _media_tag(Fake(photo=True)) == "[photo]"
    assert _media_tag(Fake(voice=True)) == "[voice message]"
    assert _media_tag(Fake(document=True, file=Fake(name="report.pdf"))) == "[file: report.pdf]"
    assert _media_tag(Fake(sticker=True, file=Fake(emoji="🔥"))) == "[sticker 🔥]"
    assert _media_tag(Fake()) is None  # plain text -> no tag


# --- extract_message --------------------------------------------------------
def test_extract_message_basic():
    msg = Fake(id=42, date=DT, sender=Fake(first_name="Ada"), sender_id=1, message="ship it", out=False)
    out = extract_message(msg)
    assert out["id"] == 42
    assert out["from"] == "Ada"
    assert out["text"] == "ship it"
    assert out["date"] == DT.isoformat()
    assert out["outgoing"] is False
    assert "media" not in out and "truncated" not in out


def test_extract_message_outgoing_reply_edited_forwarded():
    msg = Fake(
        id=7, date=DT, sender=None, sender_id=99, message="re: that",
        out=True, reply_to_msg_id=3, edit_date=DT, forward=Fake(),
    )
    out = extract_message(msg)
    assert out["outgoing"] is True
    assert out["from"] == "99"  # falls back to sender_id when no sender entity
    assert out["reply_to_id"] == 3
    assert out["edited"] is True
    assert out["forwarded"] is True


def test_extract_message_truncates_long_text():
    msg = Fake(id=1, date=DT, sender=Fake(first_name="A"), sender_id=1, message="x" * 50, out=False)
    out = extract_message(msg, truncate=10)
    assert out["truncated"] is True
    assert len(out["text"]) == 10


def test_extract_message_media_only():
    msg = Fake(id=2, date=DT, sender=Fake(first_name="A"), sender_id=1, message="", out=False, photo=True)
    out = extract_message(msg)
    assert "text" not in out
    assert out["media"] == "[photo]"


def test_extract_message_service_event():
    msg = Fake(id=3, date=DT, sender=None, sender_id=1, message="", out=False,
               action=MessageActionPinMessage())
    out = extract_message(msg)
    assert out["media"].startswith("[event:")
    assert "PinMessage" in out["media"]


# --- summarize_dialog -------------------------------------------------------
def test_summarize_dialog():
    dialog = Fake(
        entity=Fake(id=500, username="adacorp"),
        name="AdaCorp", is_group=True, unread_count=4, date=DT,
        pinned=True, archived=False,
        dialog=Fake(read_inbox_max_id=120),
    )
    out = summarize_dialog(dialog)
    assert out == {
        "id": 500,
        "name": "AdaCorp",
        "kind": "group",
        "username": "adacorp",
        "unread": 4,
        "last_message_date": DT.isoformat(),
        "pinned": True,
        "archived": False,
    }
