"""Plain (non-AI) Discord-markdown rendering of a digest."""

from __future__ import annotations

from datetime import date
from itertools import groupby

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


def _compact(ev: Event) -> str:
    who = f"**{ev.owner}**" + (f" ({ev.category})" if ev.category else "")
    return f"• {who}: {ev.name}" + (f" · {ev.status}" if ev.status else "")


def _section(items: list[Event], today: date) -> list[str]:
    """Events in date order; when 3+ people's tasks share the same dates, list them under one heading."""
    lines = []
    ordered = sorted(items, key=lambda e: (e.date, e.end or e.date))
    for _, group in groupby(ordered, key=lambda e: (e.date, e.end)):
        group = list(group)
        assigned = [e for e in group if e.owner]
        if len(assigned) < 3:
            lines += [_line(e, today) for e in group]
            continue
        lines += [_line(e, today) for e in group if not e.owner]
        lines.append(f"__{_when(assigned[0], today)}__")
        lines += [_compact(e) for e in assigned]
    return lines


def render_plain(digest: Digest) -> str:
    sections = [
        ("⏳ Happening now", digest.in_progress),
        ("📅 Next 7 days", digest.this_week),
        (f"🔭 Later (up to {digest.lookahead_days} days out)", digest.later),
        ("⚠️ Overdue / needs attention", digest.overdue),
    ]
    out = []
    for title, items in sections:
        if items:
            out.append(f"**{title}**\n" + "\n".join(_section(items, digest.today)))
    if not out:
        return f"Nothing scheduled in the next {digest.lookahead_days} days. 🎉"
    return "\n\n".join(out)
