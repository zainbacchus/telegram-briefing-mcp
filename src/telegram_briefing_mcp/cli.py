"""One-shot briefing from the command line (the `telegram-brief` console script).

This is the universal access path: any shell — a cron job, another agent
session, a terminal — can pull a briefing with one command, no MCP client
required. It reuses the exact same window vocabulary and fetch code as the MCP
tools and is just as read-only.

    telegram-brief                 # last 24h, text digest
    telegram-brief week            # last 7 days
    telegram-brief unread          # only unread
    telegram-brief 2d --json      # last 2 days, raw JSON
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime

from .briefing import build_briefing
from .client import NotAuthenticatedError, connected_client
from .windows import WindowError, resolve_window


def _local_stamp(iso: str | None) -> str:
    if not iso:
        return "--- --:--"
    return datetime.fromisoformat(iso).astimezone().strftime("%a %H:%M")


def _print_text(out: dict) -> None:
    print(
        f"Telegram briefing — {out['window']}  "
        f"({out['chat_count']} chats, {out['total_messages']} messages)"
    )
    for c in out["chats"]:
        unread = f", unread={c['unread']}" if c.get("unread") else ""
        print(f"\n## {c['name']}  ({c['kind']}{unread})")
        for m in c["messages"]:
            who = "me" if m.get("outgoing") else m.get("from", "?")
            body = (m.get("text") or m.get("media") or "").replace("\n", " ⏎ ")
            print(f"  [{_local_stamp(m.get('date'))}] {who}: {body}")
    if out.get("hit_chat_cap"):
        print("\n(note: chat cap reached — raise --chats to see more)")


def cli_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="telegram-brief",
        description="Pull a read-only Telegram briefing for a time window.",
    )
    parser.add_argument(
        "window",
        nargs="?",
        default="day",
        help="'day' (default), 'today', 'yesterday', 'week', 'month', 'unread', "
        "'all', or a duration like '36h', '2d', '2w'",
    )
    parser.add_argument("--json", action="store_true", help="emit raw JSON instead of a text digest")
    parser.add_argument("--chats", type=int, default=25, help="max chats to include (default 25)")
    parser.add_argument("--per-chat", dest="per_chat", type=int, default=30,
                        help="max messages per chat (default 30)")
    parser.add_argument("--channels", action="store_true", help="include broadcast channels")
    parser.add_argument("--bots", action="store_true", help="include bot chats")
    parser.add_argument("--archived", action="store_true", help="include archived chats")
    args = parser.parse_args(argv)

    try:
        window = resolve_window(args.window)
    except WindowError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    async def run() -> dict:
        async with connected_client() as client:
            return await build_briefing(
                client,
                window,
                include={"dm": True, "group": True, "channel": args.channels, "bot": args.bots},
                include_archived=args.archived,
                max_chats=args.chats,
                max_messages_per_chat=args.per_chat,
            )

    try:
        out = asyncio.run(run())
    except (NotAuthenticatedError, RuntimeError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    if args.json:
        json.dump(out, sys.stdout, ensure_ascii=False, indent=2)
        print()
    else:
        _print_text(out)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(cli_main())
