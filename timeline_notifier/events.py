"""Turn spreadsheet rows into events and pick the ones worth announcing."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

import pandas as pd

# Header names we recognise for each field, in priority order. Matching is
# case-insensitive and ignores spaces, underscores and punctuation.
COLUMN_ALIASES: dict[str, list[str]] = {
    "name": ["event", "milestone", "name", "title", "task", "item", "deliverable", "activity", "description"],
    "date": ["date", "duedate", "due", "deadline", "startdate", "start", "when", "targetdate", "eventdate"],
    "end": ["enddate", "end", "finish", "finishdate", "until"],
    "status": ["status", "state", "progress"],
    "owner": ["owner", "assignee", "assignedto", "responsible", "lead", "who"],
    "category": ["type", "category", "phase", "workstream", "team", "stage"],
    "notes": ["notes", "details", "comments", "description", "location"],
}

DONE_STATUSES = {"done", "complete", "completed", "finished", "closed", "cancelled", "canceled", "shipped", "n/a"}


@dataclass
class Event:
    name: str
    date: date
    end: date | None = None
    status: str = ""
    owner: str = ""
    category: str = ""
    notes: str = ""

    @property
    def is_done(self) -> bool:
        return self.status.strip().lower() in DONE_STATUSES

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "date": self.date.isoformat(),
            "end": self.end.isoformat() if self.end else None,
            "status": self.status or None,
            "owner": self.owner or None,
            "category": self.category or None,
            "notes": self.notes or None,
        }


@dataclass
class Digest:
    today: date
    lookahead_days: int
    this_week: list[Event] = field(default_factory=list)
    later: list[Event] = field(default_factory=list)
    in_progress: list[Event] = field(default_factory=list)
    overdue: list[Event] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not (self.this_week or self.later or self.in_progress or self.overdue)


def _norm(header: str) -> str:
    return "".join(ch for ch in str(header).lower() if ch.isalnum())


def detect_columns(columns: list[str], overrides: dict[str, str] | None = None) -> dict[str, str]:
    """Map our field names to the spreadsheet's actual header names."""
    overrides = {k: v for k, v in (overrides or {}).items() if v}
    by_norm = {_norm(c): c for c in columns}
    mapping: dict[str, str] = {}
    used: set[str] = set()
    for fld in ["date", "end", "name", "status", "owner", "category", "notes"]:
        if fld in overrides:
            if overrides[fld] not in columns:
                raise ValueError(f"Column '{overrides[fld]}' (set for {fld}) not found. Columns: {columns}")
            mapping[fld] = overrides[fld]
            used.add(overrides[fld])
            continue
        for alias in COLUMN_ALIASES[fld]:
            col = by_norm.get(alias)
            if col and col not in used:
                mapping[fld] = col
                used.add(col)
                break
    missing = [f for f in ("date", "name") if f not in mapping]
    if missing:
        raise ValueError(
            f"Could not find a column for {missing} in headers {columns}. "
            "Rename the header or set DATE_COLUMN / NAME_COLUMN."
        )
    return mapping


def _to_date(value, dayfirst: bool) -> date | None:
    if value is None or (isinstance(value, float) and pd.isna(value)) or str(value).strip() == "":
        return None
    if isinstance(value, (int, float)) and 20000 < value < 80000:  # Excel serial date
        return (pd.Timestamp("1899-12-30") + pd.Timedelta(days=int(value))).date()
    try:
        ts = pd.to_datetime(value, dayfirst=dayfirst)
    except (ValueError, TypeError):
        return None
    return None if pd.isna(ts) else ts.date()


to_date = _to_date


def _text(value) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return str(value).strip()


def parse_events(df: pd.DataFrame, overrides: dict[str, str] | None = None, dayfirst: bool = False) -> list[Event]:
    df = df.dropna(how="all")
    df.columns = [str(c).strip() for c in df.columns]
    cols = detect_columns(list(df.columns), overrides)
    events = []
    for _, row in df.iterrows():
        name = _text(row[cols["name"]])
        when = _to_date(row[cols["date"]], dayfirst)
        if not name or when is None:
            continue
        events.append(
            Event(
                name=name,
                date=when,
                end=_to_date(row[cols["end"]], dayfirst) if "end" in cols else None,
                **{f: _text(row[cols[f]]) for f in ("status", "owner", "category", "notes") if f in cols},
            )
        )
    return sorted(events, key=lambda e: e.date)


def build_digest(events: list[Event], today: date, lookahead_days: int = 14, overdue_days: int = 30) -> Digest:
    """Bucket events relative to ``today``.

    - this_week: starts within the next 7 days (today included)
    - later: starts after that, up to ``lookahead_days`` out
    - in_progress: started earlier and has an end date that hasn't passed yet
    - overdue: date passed within ``overdue_days``, no end date, not marked done
    """
    digest = Digest(today=today, lookahead_days=lookahead_days)
    week_end = today + timedelta(days=7)
    horizon = today + timedelta(days=lookahead_days)
    for ev in events:
        if today <= ev.date < week_end:
            digest.this_week.append(ev)
        elif week_end <= ev.date <= horizon:
            digest.later.append(ev)
        elif ev.date < today and ev.end and ev.end >= today and not ev.is_done:
            digest.in_progress.append(ev)
        elif today - timedelta(days=overdue_days) <= ev.date < today and not ev.end and ev.status and not ev.is_done:
            digest.overdue.append(ev)
    return digest
