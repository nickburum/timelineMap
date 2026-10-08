from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from timeline_notifier import discord
from timeline_notifier.__main__ import main
from timeline_notifier.events import build_digest, detect_columns, parse_events
from timeline_notifier.loader import google_sheet_export_url

SAMPLE = Path(__file__).parent.parent / "examples" / "sample_timeline.csv"


def test_google_sheet_url_conversion():
    url = "https://docs.google.com/spreadsheets/d/abc_123-XYZ/edit?usp=sharing#gid=987"
    assert google_sheet_export_url(url) == (
        "https://docs.google.com/spreadsheets/d/abc_123-XYZ/export?format=csv&gid=987"
    )
    assert google_sheet_export_url("https://example.com/file.xlsx") is None


def test_detect_columns_aliases_and_overrides():
    cols = ["Milestone", "Due Date", "Assigned To", "Notes"]
    assert detect_columns(cols) == {"date": "Due Date", "name": "Milestone", "owner": "Assigned To", "notes": "Notes"}
    assert detect_columns(["What", "Day"], {"name": "What", "date": "Day"}) == {"name": "What", "date": "Day"}
    with pytest.raises(ValueError):
        detect_columns(["Foo", "Bar"])


def test_parse_handles_mixed_date_formats_and_blank_rows():
    df = pd.DataFrame(
        {
            "Event": ["A", "B", None, "C", "D"],
            "Date": ["2026-10-08", "10/20/2026", None, 46300, "not a date"],
        }
    )
    events = parse_events(df)
    assert [(e.name, e.date) for e in events] == [
        ("C", date(2026, 10, 5)),  # Excel serial number
        ("A", date(2026, 10, 8)),
        ("B", date(2026, 10, 20)),
    ]


def test_digest_buckets():
    events = parse_events(pd.read_csv(SAMPLE))
    d = build_digest(events, today=date(2026, 10, 7), lookahead_days=14)
    assert [e.name for e in d.this_week] == ["Prototype demo", "Beta build freeze"]
    assert [e.name for e in d.later] == ["Marketing brief due"]
    assert [e.name for e in d.in_progress] == ["Design sprint"]
    # Kickoff is done, so only the unfinished past item is overdue
    assert [e.name for e in d.overdue] == ["Requirements sign-off"]


def test_chunking_respects_discord_limits():
    body = "\n".join(f"• line {i} " + "x" * 80 for i in range(200))
    payloads = discord.build_payloads("Title", body, "footer")
    assert len(payloads) > 1
    for p in payloads:
        assert len(p["embeds"]) == 1
        assert len(p["embeds"][0]["description"]) <= 4096
    assert "title" in payloads[0]["embeds"][0] and "footer" in payloads[-1]["embeds"][0]
    assert "\n".join(p["embeds"][0]["description"] for p in payloads) == body


def test_end_to_end_posts_to_webhook(monkeypatch):
    sent = []

    class Resp:
        status_code = 204

        def raise_for_status(self):
            pass

    monkeypatch.setattr(discord.requests, "post", lambda url, json, timeout: sent.append((url, json)) or Resp())
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://discord.test/webhook")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    assert main(["--source", str(SAMPLE), "--today", "2026-10-07"]) == 0
    assert len(sent) == 1
    desc = sent[0][1]["embeds"][0]["description"]
    assert "Prototype demo" in desc and "Requirements sign-off" in desc


def _sample_digest():
    return build_digest(parse_events(pd.read_csv(SAMPLE)), today=date(2026, 10, 7))


def test_resolve_provider(monkeypatch):
    from timeline_notifier.summarizer import resolve_provider

    for var in ("AI_PROVIDER", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "GEMINI_API_KEY", "GROQ_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    assert resolve_provider() == "none"
    monkeypatch.setenv("GROQ_API_KEY", "k")
    assert resolve_provider() == "groq"
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    assert resolve_provider() == "claude"
    assert resolve_provider("github") == "github"
    monkeypatch.setenv("AI_PROVIDER", "none")
    assert resolve_provider() == "none"


def test_free_provider_request_and_fallback(monkeypatch):
    from timeline_notifier import summarizer

    calls = []

    class Resp:
        status_code = 200

        def json(self):
            return {"choices": [{"message": {"content": "FREE AI DIGEST"}}]}

    monkeypatch.setattr(summarizer.requests, "post", lambda url, **kw: calls.append((url, kw)) or Resp())
    monkeypatch.setenv("GITHUB_TOKEN", "ghs_test")
    monkeypatch.delenv("AI_MODEL", raising=False)
    monkeypatch.delenv("AI_BASE_URL", raising=False)
    monkeypatch.delenv("AI_API_KEY", raising=False)
    text, label = summarizer.ai_summary(_sample_digest(), provider="github")
    assert text == "FREE AI DIGEST" and label == "GitHub Models (openai/gpt-4.1-mini)"
    url, kw = calls[0]
    assert url == "https://models.github.ai/inference/chat/completions"
    assert kw["headers"]["Authorization"] == "Bearer ghs_test"
    assert "Prototype demo" in kw["json"]["messages"][1]["content"]

    # Missing key or a failing API means code-only output, never a crash
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert summarizer.ai_summary(_sample_digest(), provider="gemini") is None
    monkeypatch.setattr(summarizer.requests, "post", lambda url, **kw: (_ for _ in ()).throw(ConnectionError("down")))
    assert summarizer.ai_summary(_sample_digest(), provider="github") is None


def test_folder_source_uses_newest_spreadsheet(tmp_path, monkeypatch):
    import os
    import shutil

    from timeline_notifier.loader import load_timeline, newest_spreadsheet

    old = tmp_path / "old.csv"
    old.write_text("Event,Date\nOld thing,2026-10-08\n")
    new = tmp_path / "new.xlsx"
    shutil.copy(Path(__file__).parent.parent / "examples" / "sample_timeline.xlsx", new)
    (tmp_path / "README.md").write_text("not a spreadsheet")
    os.utime(old, (1, 1))
    assert newest_spreadsheet(tmp_path) == new
    assert "Prototype demo" in set(load_timeline(str(tmp_path))["Milestone"])


def test_empty_folder_skips_without_posting(tmp_path, monkeypatch):
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://discord.test/webhook")
    monkeypatch.setattr(discord.requests, "post", lambda *a, **k: pytest.fail("should not post"))
    assert main(["--source", str(tmp_path)]) == 0


GRID = Path(__file__).parent.parent / "examples" / "sample_grid_timeline.xlsx"


def test_grid_timeline_xlsx():
    from timeline_notifier.grid import parse_sheet
    from timeline_notifier.loader import load_sheets

    events = parse_sheet(load_sheets(str(GRID))[0], today=date(2026, 10, 12))
    assert all(e.date.year == 2026 and e.date.month >= 8 for e in events)  # hidden "May" columns ignored
    phases = {e.name: (e.date, e.end) for e in events if e.category == "Phase"}
    assert phases["PRE PRODUCTION"] == (date(2026, 8, 23), date(2026, 10, 10))
    assert phases["ALPHA PHASE"] == (date(2026, 10, 11), date(2026, 12, 12))
    fall = [e for e in events if e.name == "Fall Break!"]
    assert len(fall) == 1 and fall[0].owner == "Everyone"  # merged down the column = one team event
    boss = next(e for e in events if e.name == "Boss Textures")
    assert (boss.owner, boss.category, boss.date, boss.end) == ("Ava", "Art", date(2026, 10, 18), date(2026, 10, 24))
    assert not any(e.name.startswith("Week ") for e in events)

    d = build_digest(events, today=date(2026, 10, 12))
    assert {e.name for e in d.in_progress} == {"ALPHA PHASE", "Dev Begins", "Fall Break!"}
    assert len(d.this_week) == 5


def test_grid_csv_without_merge_info_and_year_rollover():
    from timeline_notifier.grid import parse_sheet
    from timeline_notifier.loader import _csv_sheet

    csv_text = "\n".join([
        ",,Nov 29,Dec 6,Dec 13,Dec 20,Jan 3,Jan 10",
        ",,ALPHA,,,,BETA,",
        ",,,Playtest,,,,Launch",
        "Team,Name,Week 1,Week 2,Week 3,Week 4,Week 5,Week 6",
        "Art,Ava,Boss,Textures,,,Polish,",
        ",Ben,VFX,,,,,",
    ])
    events = parse_sheet(_csv_sheet(csv_text), today=date(2026, 12, 1))
    by_name = {e.name: e for e in events}
    assert by_name["ALPHA"].end == date(2027, 1, 2)  # phase runs until the next phase starts
    assert by_name["BETA"].date == date(2027, 1, 3)  # Dec -> Jan rolls into the next year
    assert by_name["Launch"].category == "Milestone"
    assert by_name["Polish"].owner == "Ava" and by_name["VFX"].owner == "Ben"
    assert by_name["Textures"].date == date(2026, 12, 6)


def test_list_layout_with_title_rows_above_header():
    from timeline_notifier.grid import parse_sheet
    from timeline_notifier.loader import _csv_sheet

    sheet = _csv_sheet("My Project Plan,,\n,,\nTask,Due Date,Owner\nShip it,2026-10-20,Sam\n")
    events = parse_sheet(sheet, today=date(2026, 10, 12))
    assert [(e.name, e.date, e.owner) for e in events] == [("Ship it", date(2026, 10, 20), "Sam")]


def test_unreadable_sheet_explains_both_layouts():
    from timeline_notifier.grid import parse_sheet
    from timeline_notifier.loader import _csv_sheet

    with pytest.raises(ValueError, match="weekly grid"):
        parse_sheet(_csv_sheet("foo,bar\n1,2\n"), today=date(2026, 10, 12))
