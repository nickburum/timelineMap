"""Entry point: python -m timeline_notifier [--dry-run] [--today YYYY-MM-DD]

Configuration comes from environment variables (see README / .env.example).
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import date, datetime
from zoneinfo import ZoneInfo

from . import discord
from .events import build_digest, parse_events
from .formatter import render_plain
from .loader import load_timeline
from .summarizer import ai_summary


def _load_dotenv(path: str = ".env") -> None:
    """Minimal .env support for local runs (real env vars win)."""
    if not os.path.exists(path):
        return
    with open(path) as fh:
        for raw in fh:
            line = raw.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def main(argv: list[str] | None = None) -> int:
    _load_dotenv()
    parser = argparse.ArgumentParser(description="Post upcoming timeline events to Discord.")
    parser.add_argument("--source", default=os.environ.get("TIMELINE_SOURCE"), help="Sheets URL or .xlsx/.csv path")
    parser.add_argument("--dry-run", action="store_true", default=_env_flag("DRY_RUN"), help="Print instead of posting")
    parser.add_argument("--today", help="Override today's date (YYYY-MM-DD), useful for testing")
    parser.add_argument("--no-ai", action="store_true", default=_env_flag("DISABLE_AI"), help="Skip the Claude summary")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    if not args.source:
        parser.error("Set TIMELINE_SOURCE or pass --source")
    webhook = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
    if not webhook and not args.dry_run:
        parser.error("Set DISCORD_WEBHOOK_URL (or use --dry-run)")

    tz = ZoneInfo(os.environ.get("TIMEZONE", "UTC"))
    today = date.fromisoformat(args.today) if args.today else datetime.now(tz).date()
    lookahead = int(os.environ.get("LOOKAHEAD_DAYS", "14"))
    overdue_days = int(os.environ.get("OVERDUE_DAYS", "30"))
    project = os.environ.get("PROJECT_NAME", "").strip()

    df = load_timeline(args.source, sheet_name=os.environ.get("SHEET_NAME") or None)
    overrides = {
        fld: os.environ.get(f"{fld.upper()}_COLUMN", "")
        for fld in ("name", "date", "end", "status", "owner", "category", "notes")
    }
    events = parse_events(df, overrides, dayfirst=_env_flag("DAY_FIRST"))
    digest = build_digest(events, today, lookahead, overdue_days)
    logging.info(
        "%d events loaded; this week=%d, later=%d, in progress=%d, overdue=%d",
        len(events), len(digest.this_week), len(digest.later), len(digest.in_progress), len(digest.overdue),
    )

    if digest.is_empty and _env_flag("SKIP_IF_EMPTY"):
        logging.info("Nothing upcoming and SKIP_IF_EMPTY is set; not posting")
        return 0

    body = None if (args.no_ai or digest.is_empty) else ai_summary(digest, project)
    footer = "Summarised by Claude from the timeline" if body else "From the timeline spreadsheet"
    body = body or render_plain(digest)
    title = f"🗓️ {project + ' — ' if project else ''}Week of {today.strftime('%b %-d, %Y')}"
    payloads = discord.build_payloads(title, body, footer, os.environ.get("BOT_NAME", "Timeline Bot"))

    if args.dry_run:
        print(f"{title}\n\n{body}\n\n— {footer}  ({len(payloads)} message(s))")
        return 0
    discord.post(webhook, payloads)
    logging.info("Posted %d message(s) to Discord", len(payloads))
    return 0


if __name__ == "__main__":
    sys.exit(main())
