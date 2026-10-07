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
