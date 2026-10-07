"""Load a timeline from Google Sheets, an Excel workbook, or a CSV file."""

from __future__ import annotations

import io
import re
from pathlib import Path

import pandas as pd
import requests

_GSHEET_RE = re.compile(r"docs\.google\.com/spreadsheets/d/([A-Za-z0-9_-]+)")
_GID_RE = re.compile(r"[#?&]gid=(\d+)")


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
    view"), an http(s) link to a .xlsx/.csv file, or a local .xlsx/.xls/.csv path.
    """
    source = source.strip()
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


def _looks_like_csv(resp: requests.Response) -> bool:
    ctype = resp.headers.get("Content-Type", "")
    return "csv" in ctype or resp.url.lower().split("?")[0].endswith(".csv")
