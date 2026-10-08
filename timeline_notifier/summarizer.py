"""Optional AI-written digest. Falls back to plain formatting (code only) on any problem.

Pick the writer with AI_PROVIDER:
  none    - code only, no AI at all
  github  - GitHub Models (free; uses GITHUB_TOKEN, works out of the box in GitHub Actions)
  gemini  - Google Gemini free tier (GEMINI_API_KEY)
  groq    - Groq free tier (GROQ_API_KEY)
  ollama  - a local model via Ollama (free, runs on your machine)
  openai  - any other OpenAI-compatible endpoint (AI_BASE_URL + AI_API_KEY)
  claude  - Anthropic Claude (ANTHROPIC_API_KEY, paid)
  auto    - (default) Claude if ANTHROPIC_API_KEY is set, else the first free provider with a key, else none
"""

from __future__ import annotations

import json
import logging
import os

import requests

from .events import Digest

log = logging.getLogger(__name__)

CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-opus-5-5")

# OpenAI-compatible providers: (base URL, env var holding the key, default model, display name)
FREE_PROVIDERS: dict[str, tuple[str, str, str, str]] = {
    "github": ("https://models.github.ai/inference", "GITHUB_TOKEN", "openai/gpt-4.1-mini", "GitHub Models"),
    "gemini": ("https://generativelanguage.googleapis.com/v1beta/openai", "GEMINI_API_KEY", "gemini-2.5-flash", "Gemini"),
    "groq": ("https://api.groq.com/openai/v1", "GROQ_API_KEY", "llama-3.3-70b-versatile", "Groq"),
    "ollama": ("http://localhost:11434/v1", "", "llama3.2", "Ollama"),
}

SYSTEM_PROMPT = """You write the weekly timeline update for a team's Discord channel.
You receive today's date and the relevant events from the team's timeline spreadsheet as JSON,
already grouped into: this_week (next 7 days), later (rest of the lookahead window), in_progress, and overdue.

Write a short, friendly digest in Discord markdown:
- Open with one or two sentences on what matters most this week (biggest deadline, anything at risk).
- Then list events by group using bold group headings and bullet points. For each event give the
  name in bold, the day and date (e.g. "Tue Oct 14"), and owner/status when present.
- Call out overdue items and tight clusters of deadlines plainly; don't invent risk that isn't there.
- Only use facts from the JSON. Never invent events, dates, owners or details.
- Skip empty groups. No title line (the message already has one). Keep it under 3000 characters."""


def _payload(digest: Digest, project_name: str) -> str:
    return json.dumps(
        {
            "project": project_name or None,
            "today": digest.today.strftime("%A %Y-%m-%d"),
            "lookahead_days": digest.lookahead_days,
            "this_week": [e.to_dict() for e in digest.this_week],
            "later": [e.to_dict() for e in digest.later],
            "in_progress": [e.to_dict() for e in digest.in_progress],
            "overdue": [e.to_dict() for e in digest.overdue],
        },
        indent=1,
    )


def resolve_provider(name: str | None = None) -> str:
    name = (name or os.environ.get("AI_PROVIDER") or "auto").strip().lower()
    if name != "auto":
        return name
    if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        return "claude"
    for key in ("gemini", "groq"):
        if os.environ.get(FREE_PROVIDERS[key][1]):
            return key
    return "none"


def ai_summary(digest: Digest, project_name: str = "", provider: str | None = None) -> tuple[str, str] | None:
    """Return (digest text, writer label), or None to fall back to code-only formatting."""
    provider = resolve_provider(provider)
    if provider in ("none", "off", "code", "false", ""):
        return None
    try:
        if provider == "claude":
            text = _claude(_payload(digest, project_name))
            label = "Claude"
        elif provider in FREE_PROVIDERS or provider == "openai":
            text, label = _openai_compatible(provider, _payload(digest, project_name))
        else:
            log.warning("Unknown AI_PROVIDER %r; using plain formatting", provider)
            return None
    except Exception as exc:  # any AI failure must never block the weekly post
        log.warning("%s summary failed (%s); using plain formatting", provider, exc)
        return None
    return (text, label) if text else None


def _openai_compatible(provider: str, payload: str) -> tuple[str | None, str]:
    if provider == "openai":
        base, key_env, model, label = os.environ.get("AI_BASE_URL", ""), "AI_API_KEY", "", "AI"
        if not base:
            raise ValueError("AI_PROVIDER=openai needs AI_BASE_URL")
    else:
        base, key_env, model, label = FREE_PROVIDERS[provider]
    base = os.environ.get("AI_BASE_URL") or base
    model = os.environ.get("AI_MODEL") or model
    if not model:
        raise ValueError("set AI_MODEL")
    key = os.environ.get("AI_API_KEY") or (os.environ.get(key_env) if key_env else "")
    if key_env and not key:
        raise ValueError(f"{key_env} is not set")

    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    resp = requests.post(
        f"{base.rstrip('/')}/chat/completions",
        headers=headers,
        json={
            "model": model,
            "messages": [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": payload}],
            "temperature": 0.3,
        },
        timeout=120,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:300]}")
    text = (resp.json()["choices"][0]["message"].get("content") or "").strip()
    return text or None, f"{label} ({model})"


def _claude(payload: str) -> str | None:
    import anthropic

    client = anthropic.Anthropic()
    response = client.beta.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=16000,
        system=SYSTEM_PROMPT,
        output_config={"effort": "low"},
        # If a safety classifier declines, let the API retry on its recommended fallback model.
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        messages=[{"role": "user", "content": payload}],
    )
    if response.stop_reason == "refusal":
        raise RuntimeError("request declined")
    return "".join(b.text for b in response.content if b.type == "text").strip() or None
