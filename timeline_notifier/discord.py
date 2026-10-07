"""Post a digest to a Discord channel through an incoming webhook."""

from __future__ import annotations

import time

import requests

EMBED_DESC_LIMIT = 4000  # Discord's hard limit is 4096
EMBED_COLOR = 0x5865F2


def chunk_text(text: str, limit: int = EMBED_DESC_LIMIT) -> list[str]:
    """Split on paragraph/line boundaries so no chunk exceeds ``limit`` characters."""
    chunks: list[str] = []
    current = ""
    for para in text.split("\n"):
        while len(para) > limit:  # pathological single line
            chunks.append(para[:limit])
            para = para[limit:]
        candidate = f"{current}\n{para}" if current else para
        if len(candidate) > limit:
            chunks.append(current)
            current = para
        else:
            current = candidate
    if current.strip():
        chunks.append(current)
    return chunks


def build_payloads(title: str, body: str, footer: str, username: str = "Timeline Bot") -> list[dict]:
    """One embed per message keeps every message well under Discord's 6000-char embed total."""
    chunks = chunk_text(body) or ["(empty)"]
    payloads = []
    for i, chunk in enumerate(chunks):
        embed = {"description": chunk, "color": EMBED_COLOR}
        if i == 0:
            embed["title"] = title[:256]
        if i == len(chunks) - 1:
            embed["footer"] = {"text": footer[:2048]}
        payloads.append({"username": username, "embeds": [embed], "allowed_mentions": {"parse": []}})
    return payloads


def post(webhook_url: str, payloads: list[dict]) -> None:
    for payload in payloads:
        for attempt in range(5):
            resp = requests.post(webhook_url, json=payload, timeout=30)
            if resp.status_code == 429:  # rate limited: Discord says how long to wait
                time.sleep(float(resp.json().get("retry_after", 1)))
                continue
            resp.raise_for_status()
            break
        else:
            raise RuntimeError("Discord kept rate-limiting the webhook; giving up")
