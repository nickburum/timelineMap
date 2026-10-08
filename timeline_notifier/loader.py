"""Load a timeline from Google Sheets, an Excel workbook, or a CSV file."""

from __future__ import annotations

import io
import re
import subprocess
from pathlib import Path

import pandas as pd
import requests

_GSHEET_RE = re.compile(r"docs\.google\.com/spreadsheets/d/([A-Za-z0-9_-]+)")
_GID_RE = re.compile(r"[#?&]gid=(\d+)")
SPREADSHEET_SUFFIXES = {".xlsx", ".xlsm", ".xls", ".csv", ".tsv"}


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


def load_timeline(source: str, sheet_name: str | None = None) -> pd.DataFrame:
    """Read the timeline into a DataFrame with every cell as raw values.

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
            return pd.read_csv(io.StringIO(resp.content.decode("utf-8-sig")))
        return pd.read_excel(io.BytesIO(resp.content), sheet_name=sheet_name or 0)

    path = Path(source)
    if not path.exists():
        raise FileNotFoundError(f"Timeline file not found: {source}")
    if path.suffix.lower() in {".csv", ".tsv"}:
        return pd.read_csv(path, sep="\t" if path.suffix.lower() == ".tsv" else ",")
    return pd.read_excel(path, sheet_name=sheet_name or 0)


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
