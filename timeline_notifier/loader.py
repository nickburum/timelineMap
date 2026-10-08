"""Load a timeline from Google Sheets, an Excel workbook, or a CSV file."""

from __future__ import annotations

import csv
import io
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
import requests

_GSHEET_RE = re.compile(r"docs\.google\.com/spreadsheets/d/([A-Za-z0-9_-]+)")
_GID_RE = re.compile(r"[#?&]gid=(\d+)")
SPREADSHEET_SUFFIXES = {".xlsx", ".xlsm", ".xls", ".csv", ".tsv"}


@dataclass
class Sheet:
    """A worksheet as a raw grid, plus the layout details a plain table loses."""

    rows: list[list]
    merges: list[tuple[int, int, int, int]] = field(default_factory=list)  # (row0, col0, row1, col1), inclusive
    hidden_rows: set[int] = field(default_factory=set)
    hidden_cols: set[int] = field(default_factory=set)
    name: str = ""

    def to_frame(self, header_row: int) -> pd.DataFrame:
        headers = [str(v).strip() if v is not None else "" for v in self.rows[header_row]]
        body = [r for i, r in enumerate(self.rows[header_row + 1:], start=header_row + 1) if i not in self.hidden_rows]
        width = len(headers)
        return pd.DataFrame([(list(r) + [None] * width)[:width] for r in body], columns=headers)


def google_sheet_export_url(url: str) -> str | None:
    """Turn any Google Sheets link into its CSV export URL (None if not a Sheets link)."""
    match = _GSHEET_RE.search(url)
    if not match:
        return None
    export = f"https://docs.google.com/spreadsheets/d/{match.group(1)}/export?format=csv"
    gid = _GID_RE.search(url)
    if gid:
        export += f"&gid={gid.group(1)}"
    return export


def load_sheets(source: str, sheet_name: str | None = None) -> list[Sheet]:
    """Read every visible worksheet (just one if ``sheet_name`` is given).

    ``source`` may be a Google Sheets link (shared as "anyone with the link can
    view"), an http(s) link to a .xlsx/.csv file, a local .xlsx/.xls/.csv path, or
    a folder (the newest spreadsheet in it is used).
    """
    source = source.strip()
    if Path(source).is_dir():
        source = str(newest_spreadsheet(Path(source)))

    if source.startswith(("http://", "https://")):
        export = google_sheet_export_url(source)
        resp = requests.get(export or source, timeout=60)
        resp.raise_for_status()
        if export or _looks_like_csv(resp):
            if "text/html" in resp.headers.get("Content-Type", ""):
                raise ValueError(
                    "Google returned a web page instead of CSV. Share the sheet as "
                    "'Anyone with the link can view' (or use File > Share > Publish to web)."
                )
            return [_csv_sheet(resp.content.decode("utf-8-sig"))]
        return _excel_sheets(io.BytesIO(resp.content), sheet_name, ".xlsx")

    path = Path(source)
    if not path.exists():
        raise FileNotFoundError(f"Timeline file not found: {source}")
    suffix = path.suffix.lower()
    if suffix in {".csv", ".tsv"}:
        return [_csv_sheet(path.read_text(encoding="utf-8-sig"), "\t" if suffix == ".tsv" else ",")]
    return _excel_sheets(path, sheet_name, suffix)


def load_timeline(source: str, sheet_name: str | None = None) -> pd.DataFrame:
    """First worksheet as a table whose first row is the header (simple list layouts)."""
    return load_sheets(source, sheet_name)[0].to_frame(0)


def _csv_sheet(text: str, delimiter: str = ",") -> Sheet:
    rows = [[cell if cell != "" else None for cell in row] for row in csv.reader(io.StringIO(text), delimiter=delimiter)]
    return Sheet(rows=rows)


def _excel_sheets(src, sheet_name: str | None, suffix: str) -> list[Sheet]:
    if suffix == ".xls":  # legacy format: openpyxl can't read it, so there's no merge/hidden info
        frames = pd.read_excel(src, sheet_name=sheet_name or None, header=None)
        if isinstance(frames, pd.DataFrame):
            frames = {sheet_name: frames}
        return [
            Sheet(rows=df.astype(object).where(df.notna(), None).values.tolist(), name=str(n))
            for n, df in frames.items()
        ]

    from openpyxl import load_workbook

    wb = load_workbook(src, data_only=True)
    worksheets = [wb[sheet_name]] if sheet_name else [ws for ws in wb.worksheets if ws.sheet_state == "visible"]
    sheets = []
    for ws in worksheets:
        rows = [list(r) for r in ws.iter_rows(values_only=True)]
        merges = [(m.min_row - 1, m.min_col - 1, m.max_row - 1, m.max_col - 1) for m in ws.merged_cells.ranges]
        hidden_cols: set[int] = set()
        for dim in ws.column_dimensions.values():
            if dim.hidden and dim.min:
                hidden_cols.update(range(dim.min - 1, dim.max or dim.min))
        hidden_rows = {i - 1 for i, dim in ws.row_dimensions.items() if dim.hidden}
        sheets.append(Sheet(rows, merges, hidden_rows, hidden_cols, ws.title))
    return sheets


def newest_spreadsheet(folder: Path) -> Path:
    """Pick the most recently committed (or, outside git, modified) spreadsheet in ``folder``."""
    files = [f for f in folder.iterdir() if f.is_file() and f.suffix.lower() in SPREADSHEET_SUFFIXES
             and not f.name.startswith(("~$", "."))]
    if not files:
        raise FileNotFoundError(f"No timeline spreadsheet in {folder}/ yet. Upload one with the Upload timeline page.")
    return max(files, key=lambda f: (_commit_time(f), f.stat().st_mtime, f.name))


def _commit_time(path: Path) -> int:
    try:
        out = subprocess.run(
            ["git", "log", "-1", "--format=%ct", "--", path.name],
            cwd=path.parent, capture_output=True, text=True, timeout=10,
        )
        return int(out.stdout.strip() or 0)
    except (OSError, ValueError, subprocess.SubprocessError):
        return 0


def _looks_like_csv(resp: requests.Response) -> bool:
    ctype = resp.headers.get("Content-Type", "")
    return "csv" in ctype or resp.url.lower().split("?")[0].endswith(".csv")
