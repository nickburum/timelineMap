"""Optional AI-written digest using Claude. Falls back to plain formatting on any problem."""

from __future__ import annotations

import json
import logging
import os

from .events import Digest

log = logging.getLogger(__name__)

MODEL = os.environ.get("CLAUDE_MODEL", "claude-opus-5-5")

SYSTEM_PROMPT = """You write the weekly timeline update for a team's Discord channel.
You receive today's date and the relevant events from the team's timeline spreadsheet as JSON,
already grouped into: this_week, later (rest of the lookahead window), in_progress, and overdue.

Write a short, friendly digest in Discord markdown:
- Open with one or two sentences on what matters most this week (biggest deadline, anything at risk).
- Then list events by group using bold group headings and bullet points. For each event give the
  name in bold, the day and date (e.g. "Tue Oct 14"), and owner/status when present.
- Call out overdue items and tight clusters of deadlines plainly; don't invent risk that isn't there.
- Only use facts from the JSON. Never invent events, dates, owners or details.
- Skip empty groups. No title line (the message already has one). Keep it under 3000 characters."""


def ai_summary(digest: Digest, project_name: str = "") -> str | None:
    """Return Claude's digest text, or None if AI is disabled/unavailable."""
    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        return None
    try:
        import anthropic
    except ImportError:
        log.warning("anthropic package not installed; using plain formatting")
        return None

    payload = {
        "project": project_name or None,
        "today": digest.today.strftime("%A %Y-%m-%d"),
        "lookahead_days": digest.lookahead_days,
        "this_week": [e.to_dict() for e in digest.this_week],
        "later": [e.to_dict() for e in digest.later],
        "in_progress": [e.to_dict() for e in digest.in_progress],
        "overdue": [e.to_dict() for e in digest.overdue],
    }
    client = anthropic.Anthropic()
    try:
        response = client.beta.messages.create(
            model=MODEL,
            max_tokens=16000,
            system=SYSTEM_PROMPT,
            output_config={"effort": "low"},
            # If a safety classifier declines, let the API retry on its recommended fallback model.
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            messages=[{"role": "user", "content": json.dumps(payload, indent=1)}],
        )
    except anthropic.APIStatusError as exc:
        log.warning("Claude API error %s: %s; using plain formatting", exc.status_code, exc.message)
        return None
    except anthropic.APIConnectionError as exc:
        log.warning("Could not reach Claude API (%s); using plain formatting", exc)
        return None

    if response.stop_reason == "refusal":
        log.warning("Claude declined the request; using plain formatting")
        return None
    text = "".join(b.text for b in response.content if b.type == "text").strip()
    return text or None
