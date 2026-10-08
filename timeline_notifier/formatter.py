"""Plain (non-AI) Discord-markdown rendering of a digest."""

from __future__ import annotations

from datetime import date

from .events import Digest, Event


def _when(ev: Event, today: date) -> str:
    label = ev.date.strftime("%a %b %-d")
    if ev.end and ev.end != ev.date:
        label += f" → {ev.end.strftime('%a %b %-d')}"
    delta = (ev.date - today).days
    if delta == 0:
        label += " (today)"
    elif delta == 1:
        label += " (tomorrow)"
    elif delta > 1:
        label += f" (in {delta} days)"
    elif delta < 0 and not ev.end:
        label += f" ({-delta} days ago)"
    return label


def _line(ev: Event, today: date) -> str:
    parts = [f"• **{ev.name}** — {_when(ev, today)}"]
    extras = [x for x in (ev.category, f"👤 {ev.owner}" if ev.owner else "", ev.status) if x]
    if extras:
        parts.append(" · ".join(extras))
    line = "\n   ".join(parts)
    if ev.notes:
        line += f"\n   _{ev.notes[:200]}_"
    return line


def render_plain(digest: Digest) -> str:
    sections = [
        ("📅 Next 7 days", digest.this_week),
        (f"🔭 Later (up to {digest.lookahead_days} days out)", digest.later),
        ("⏳ In progress", digest.in_progress),
        ("⚠️ Overdue / needs attention", digest.overdue),
    ]
    out = []
    for title, items in sections:
        if items:
            out.append(f"**{title}**\n" + "\n".join(_line(e, digest.today) for e in items))
    if not out:
        return f"Nothing scheduled in the next {digest.lookahead_days} days. 🎉"
    return "\n\n".join(out)
