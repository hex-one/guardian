"""
discord_api.py

Sends text (the AAR report, or a connection test message) to a Discord
channel via an Incoming Webhook. This is a completely separate, much
simpler API surface from vrchat_api.py -- no login, no session, just a
single POST to the webhook's own URL. Sometimes the simplest path is the
right one.

--------------------------------------------------------------------------
BEGINNER NOTES:

- Discord caps a single message's "content" field at 2000 characters. An
  AAR report can easily be longer than that once a mod team has been
  using Guardian a while. Rather than silently cutting the report off at
  2000 characters (which could hide real moderation history), this splits
  it into multiple sequential messages instead -- a few extra messages in
  the channel is a much smaller cost than losing information from a
  report.

- Discord replies with 429 ("Too Many Requests") if you send messages too
  fast, and tells you exactly how long to wait via `retry_after` in the
  response body. We surface that directly rather than silently retrying,
  since silently retrying in the middle of a multi-chunk send could
  reorder or duplicate parts of the report.
--------------------------------------------------------------------------
"""

from dataclasses import dataclass
from typing import Optional

import json
import requests

DISCORD_CONTENT_LIMIT = 2000  # Discord's hard limit on a message's "content" field


@dataclass
class DiscordSendResult:
    status: str  # "success" or "error"
    error_message: Optional[str] = None


def _chunk_text(text: str, limit: int = DISCORD_CONTENT_LIMIT) -> list[str]:
    """
    Splits text into <=limit-character pieces, breaking on line boundaries
    where possible so a report doesn't get cut mid-sentence. A single line
    longer than the limit (rare, but possible) gets hard-split as a last
    resort rather than dropped.
    """
    lines = text.split("\n")
    chunks = []
    current = ""

    for line in lines:
        candidate = f"{current}\n{line}" if current else line
        if len(candidate) <= limit:
            current = candidate
            continue

        if current:
            chunks.append(current)

        if len(line) <= limit:
            current = line
        else:
            for i in range(0, len(line), limit):
                chunks.append(line[i:i + limit])
            current = ""

    if current:
        chunks.append(current)

    return chunks or [""]


def send_report(webhook_url: str, content: str) -> DiscordSendResult:
    """
    Sends `content` to the given webhook, splitting into multiple messages
    if needed (see _chunk_text). Stops and reports the error at the first
    chunk that fails, rather than continuing to send a partial/out-of-order
    report.
    """
    for chunk in _chunk_text(content):
        try:
            response = requests.post(webhook_url, json={"content": chunk}, timeout=10)
        except requests.RequestException as e:
            return DiscordSendResult(status="error", error_message=str(e))

        if response.status_code == 429:
            try:
                retry_after = response.json().get("retry_after", "a few")
            except ValueError:
                retry_after = "a few"
            return DiscordSendResult(
                status="error",
                error_message=f"Discord rate-limited this webhook -- try again in {retry_after}s.",
            )

        if response.status_code not in (200, 204):
            return DiscordSendResult(status="error", error_message=f"Discord returned HTTP {response.status_code}")

    return DiscordSendResult(status="success")


def send_file(webhook_url: str, filename: str, file_bytes: bytes, content: str = "") -> DiscordSendResult:
    """
    Uploads a file to a Discord channel via the webhook -- used for
    posting the Watchlist as an attachment rather than pasted text.
    Discord requires multipart/form-data for this (not the plain JSON
    used by send_report): a "payload_json" part for the message content,
    and a "files[0]" part for the actual file bytes. Confirmed against
    Discord's own file-upload docs before building this.
    """
    payload = {"content": content} if content else {}
    files = {
        "payload_json": (None, json.dumps(payload), "application/json"),
        "files[0]": (filename, file_bytes),
    }

    try:
        response = requests.post(webhook_url, files=files, timeout=15)
    except requests.RequestException as e:
        return DiscordSendResult(status="error", error_message=str(e))

    if response.status_code == 429:
        try:
            retry_after = response.json().get("retry_after", "a few")
        except ValueError:
            retry_after = "a few"
        return DiscordSendResult(
            status="error",
            error_message=f"Discord rate-limited this webhook -- try again in {retry_after}s.",
        )

    if response.status_code not in (200, 204):
        return DiscordSendResult(status="error", error_message=f"Discord returned HTTP {response.status_code}")

    return DiscordSendResult(status="success")
