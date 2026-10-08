"""Read week-by-week schedules: dates across the top, one row per person, tasks in the cells.

Typical layout (merged cells and hidden columns are understood):

            | Aug 23         | Aug 30       | ... | Oct 11      |
            | PRE PRODUCTION (merged across weeks) | ALPHA PHASE |   <- phase banner
            |                | Pitch Day!   | ... | Dev Begins  |   <- milestones
    Track   | Name | Week 1  | Week 2       | ... | Week 8      |   <- header row
    Art     | Ava  | Ideation| Art style    | ... | Fall Break! (merged down the column)
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta

from .events import Event, detect_columns, parse_events, to_date
from .loader import Sheet

MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}
_MONTH_DAY = re.compile(r"^(?P<mon>[a-z]{3,9})\.?\s+(?P<day>\d{1,2})(?:st|nd|rd|th)?(?:,?\s+(?P<year>\d{4}))?$", re.I)
_DAY_MONTH = re.compile(r"^(?P<day>\d{1,2})(?:st|nd|rd|th)?\s+(?P<mon>[a-z]{3,9})\.?(?:,?\s+(?P<year>\d{4}))?$", re.I)
_WEEK_LABEL = re.compile(r"^(week|wk|sprint)\s*#?\s*\d+$", re.I)
NAME_HEADERS = {"name", "names", "owner", "person", "assignee", "who", "member", "teammember", "people"}
TRACK_HEADERS = {"track", "focus", "trackfocus", "role", "team", "discipline", "department", "category", "group", "area"}


def _norm(value) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value).lower()) if value is not None else ""


def _text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value != value:  # NaN
        return ""
    return str(value).strip()


def _header_date(value, dayfirst: bool) -> tuple[int, int, int | None] | None:
    """(month, day, year-or-None) if the cell looks like a column date such as "August 23" or 2026-08-23."""
    if isinstance(value, (datetime, date)):
        return value.month, value.day, value.year
    text = _text(value)
    if not text:
        return None
    for pattern in (_MONTH_DAY, _DAY_MONTH):
        m = pattern.match(text)
        if m and m.group("mon")[:3].lower() in MONTHS:
            return MONTHS[m.group("mon")[:3].lower()], int(m.group("day")), int(m.group("year")) if m.group("year") else None
    if re.match(r"^\d{4}-\d{1,2}-\d{1,2}$|^\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}$", text) or isinstance(value, (int, float)):
        d = to_date(value, dayfirst)
        if d:
            return d.month, d.day, d.year
    return None


def _resolve_years(parts: list[tuple[int, int, int | None]], today: date) -> list[date | None]:
    """Give year-less dates the year that keeps the schedule continuous (and the first one nearest today)."""
    out: list[date | None] = []
    anchor = today
    for month, day, year in parts:
        options = [year] if year else [anchor.year - 1, anchor.year, anchor.year + 1]
        candidates = []
        for y in options:
            try:
                candidates.append(date(y, month, day))
            except ValueError:
                pass
        best = min(candidates, key=lambda d: abs((d - anchor).days)) if candidates else None
        out.append(best)
        if best:
            anchor = best
    return out


def parse_grid(sheet: Sheet, today: date, dayfirst: bool = False) -> list[Event]:
    rows = sheet.rows
    ncols = max((len(r) for r in rows), default=0)
    cell = lambda r, c: rows[r][c] if r < len(rows) and c < len(rows[r]) else None
    vis_cols = [c for c in range(ncols) if c not in sheet.hidden_cols]
    vis_rows = [r for r in range(len(rows)) if r not in sheet.hidden_rows]

    # 1. The date row: the row (near the top) with the most date-like cells.
    best = None
    for r in vis_rows[:25]:
        found = [(c, d) for c in vis_cols if (d := _header_date(cell(r, c), dayfirst))]
        if len(found) >= 3 and (best is None or len(found) > len(best[1])):
            best = (r, found)
    if best is None:
        raise ValueError("no row of dates found")
    date_row, found = best
    resolved = _resolve_years([d for _, d in found], today)
    col_date = {c: d for (c, _), d in zip(found, resolved) if d}
    date_cols = sorted(col_date)
    col_end = {}
    for i, c in enumerate(date_cols):
        nxt = col_date[date_cols[i + 1]] if i + 1 < len(date_cols) else None
        gap = (nxt - col_date[c]).days if nxt else 7
        col_end[c] = col_date[c] + timedelta(days=(gap - 1 if 1 <= gap <= 31 else 6))

    # 2. Label columns (left of the dates) and the header row that names them.
    label_cols = [c for c in vis_cols if c < date_cols[0]]
    header_row, name_col, track_col = None, None, None
    for r in vis_rows:
        if r <= date_row:
            continue
        labels = {c: _norm(cell(r, c)) for c in label_cols}
        if any(v in NAME_HEADERS or v in TRACK_HEADERS for v in labels.values()):
            header_row = r
            name_col = next((c for c, v in labels.items() if v in NAME_HEADERS), None)
            track_col = next((c for c, v in labels.items() if v in TRACK_HEADERS and c != name_col), None)
            break
    if label_cols and name_col is None:
        name_col = label_cols[-1]
        track_col = label_cols[0] if len(label_cols) > 1 else None

    merge_at = {}  # top-left (r, c) -> merge
    covered = set()  # every other cell inside a merge
    for m in sheet.merges:
        r0, c0, r1, c1 = m
        merge_at[(r0, c0)] = m
        covered.update((r, c) for r in range(r0, r1 + 1) for c in range(c0, c1 + 1) if (r, c) != (r0, c0))

    def label(r, c):
        """Label cell value, filling down vertically merged labels (e.g. one "Art" for three people)."""
        if c is None:
            return ""
        for (r0, c0, r1, c1) in sheet.merges:
            if r0 < r <= r1 and c0 <= c <= c1 and r0 > date_row:
                return _text(cell(r0, c0))
        return _text(cell(r, c))

    first_body = (header_row if header_row is not None else date_row) + 1
    person_rows = [r for r in vis_rows if r >= first_body and name_col is not None and label(r, name_col)]
    person_set = set(person_rows)
    banner_rows = [r for r in vis_rows if date_row < r < first_body or (r >= first_body and r not in person_set)]

    def span(r, c, allowed_rows):
        m = merge_at.get((r, c))
        cols = [dc for dc in date_cols if c <= dc <= (m[3] if m else c)]
        rws = [rr for rr in allowed_rows if r <= rr <= (m[2] if m else r)]
        return cols, rws

    events: list[Event] = []
    has_merges = bool(sheet.merges)

    # 3. Banner rows: phases (wide merged cells) and milestones.
    for i, r in enumerate(banner_rows):
        cells = [(c, _text(cell(r, c))) for c in date_cols if (r, c) not in covered and _text(cell(r, c))]
        cells = [(c, t) for c, t in cells if not _WEEK_LABEL.match(t)]
        if not cells:
            continue
        wide = any(len(span(r, c, [r])[0]) > 1 for c, _ in cells)
        # Without merge info (CSV), treat a sparse first banner row as phases that run until the next one.
        guess_phases = not has_merges and i == 0 and r < first_body and len(cells) <= len(date_cols) / 2
        for j, (c, t) in enumerate(cells):
            if wide or guess_phases:
                if has_merges:
                    cols = span(r, c, [r])[0]
                else:
                    nxt = cells[j + 1][0] if j + 1 < len(cells) else None
                    cols = [dc for dc in date_cols if c <= dc and (nxt is None or dc < nxt)]
                events.append(Event(name=t, date=col_date[c], end=col_end[cols[-1]], category="Phase"))
            else:
                events.append(Event(name=t, date=col_date[c], end=col_end[c], category="Milestone"))

    # 4. People rows: one event per filled cell; merged cells cover several weeks and/or people.
    for r in person_rows:
        for c in date_cols:
            t = _text(cell(r, c))
            if (r, c) in covered or not t:
                continue
            cols, rws = span(r, c, person_rows)
            names = [label(rr, name_col) for rr in rws]
            tracks = sorted({label(rr, track_col) for rr in rws} - {""})
            whole_team = len(rws) > 1 and len(rws) == len(person_rows)
            events.append(Event(
                name=t,
                date=col_date[c],
                end=col_end[cols[-1]],
                owner="Everyone" if whole_team else ", ".join(names),
                category="" if whole_team else " / ".join(tracks),
            ))

    return sorted(events, key=lambda e: e.date)


def parse_sheet(sheet: Sheet, today: date, overrides: dict[str, str] | None = None, dayfirst: bool = False) -> list[Event]:
    """Read either layout: a list (one event per row, with Name/Date headers) or a week-by-week grid."""
    for r in [r for r in range(len(sheet.rows)) if r not in sheet.hidden_rows][:10]:
        headers = [_text(v) for v in sheet.rows[r]]
        try:
            detect_columns(headers, overrides)
        except ValueError:
            continue
        return parse_events(sheet.to_frame(r), overrides, dayfirst)
    try:
        return parse_grid(sheet, today, dayfirst)
    except ValueError:
        raise ValueError(
            "Couldn't read this timeline. Use either a list (one event per row, with columns like "
            "\"Milestone\" and \"Date\") or a weekly grid (week dates across the top row, one row per person)."
        ) from None
