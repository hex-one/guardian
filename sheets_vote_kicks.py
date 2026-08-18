"""
sheets_vote_kicks.py

Talks to the same Google Apps Script Web App the Watchlist already uses
(see watchlist_sync.gs) -- just a different sheet tab ("VoteKicks") and
a different action ("submit_vote_kick"). Same spreadsheet, same
deployed script, same two URLs already sitting in Config -- Vote Kicks
doesn't need its own separate setup, it rides along with whatever's
already wired up for the Watchlist. One shared memory, a second room
in the same house.

--------------------------------------------------------------------------
BEGINNER NOTES:

- fetch_events() derives the VoteKicks tab's CSV export URL straight
  from the already-configured Watchlist CSV URL, by swapping which
  sheet tab gets exported -- same spreadsheet ID, same "Anyone with the
  link" sharing already set up for it. No second URL to paste anywhere.

- submit_event() can come back "duplicate" as well as "success"/"error"
  -- that's the shared script telling us another Guardian already beat
  us to reporting this exact event (see watchlist_sync.gs's
  handleSubmitVoteKick for the first-come-first-served logic). Not a
  failure, just someone else already covered it.
--------------------------------------------------------------------------
"""

import csv
import io
import re
from dataclasses import dataclass
from typing import Optional

import requests

CSV_TIMEOUT = 10
SCRIPT_TIMEOUT = 15

_SHEET_ID_RE = re.compile(r"/spreadsheets/d/([a-zA-Z0-9_-]+)")


def _votekicks_csv_url(watchlist_csv_url: str) -> Optional[str]:
    """
    Pulls the spreadsheet ID out of whatever Watchlist CSV URL is
    already configured and rebuilds it pointed at the "VoteKicks" tab
    instead of "Watchlist" -- same sheet, same sharing settings,
    different room. Returns None if the configured URL doesn't look
    like a Google Sheets URL at all (nothing sensible to derive from).
    """
    match = _SHEET_ID_RE.search(watchlist_csv_url or "")
    if not match:
        return None
    return f"https://docs.google.com/spreadsheets/d/{match.group(1)}/gviz/tq?tqx=out:csv&sheet=VoteKicks"


@dataclass
class SheetVoteKickEvent:
    event_id: str
    target_user_id: str
    target_display_name: str
    world_id: str
    instance_id: str
    status: str
    initiated_at: str
    succeeded_at: str
    submitted_by: str
    submitted_at: str


@dataclass
class SyncResult:
    status: str  # "success", "duplicate", or "error"
    error_message: Optional[str] = None
    entries: Optional[list] = None


def _snippet(text: str, length: int = 300) -> str:
    flat = " ".join(text.split())
    return flat[:length] + ("..." if len(flat) > length else "")


def fetch_events(watchlist_csv_url: str) -> SyncResult:
    """
    Every known VoteKicks row -- used by the "Votes" viewer and the
    red-checkmark check in the player list. Unlike the Watchlist, there's
    no local-cache-first path here; vote-kick history is a look-back,
    not a live blink, so it's always worth a fresh pull when asked.
    """
    csv_url = _votekicks_csv_url(watchlist_csv_url)
    if not csv_url:
        return SyncResult(status="error", error_message="No Sheet CSV URL configured.")

    try:
        response = requests.get(csv_url, timeout=CSV_TIMEOUT)
    except requests.RequestException as e:
        return SyncResult(status="error", error_message=str(e))

    if response.status_code != 200:
        return SyncResult(status="error", error_message=f"HTTP {response.status_code}: {_snippet(response.text)}")

    first_line = response.text.splitlines()[0] if response.text.splitlines() else ""
    if "event_id" not in first_line.lower():
        return SyncResult(
            status="error",
            error_message=(
                "No 'event_id' column found in the response. Guardian actually received: "
                f"\"{_snippet(response.text)}\" -- likely the VoteKicks tab doesn't exist yet on "
                "the shared sheet, or isn't named exactly \"VoteKicks\". See SETUP.md."
            ),
        )

    reader = csv.DictReader(io.StringIO(response.text))
    entries = []
    for row in reader:
        entries.append(SheetVoteKickEvent(
            event_id=row.get("event_id", "").strip(),
            target_user_id=row.get("target_user_id", "").strip(),
            target_display_name=row.get("target_display_name", "").strip(),
            world_id=row.get("world_id", "").strip(),
            instance_id=row.get("instance_id", "").strip(),
            status=row.get("status", "").strip().lower(),
            initiated_at=row.get("initiated_at", "").strip(),
            succeeded_at=row.get("succeeded_at", "").strip(),
            submitted_by=row.get("submitted_by", "").strip(),
            submitted_at=row.get("submitted_at", "").strip(),
        ))
    return SyncResult(status="success", entries=entries)


def submit_event(script_url: str, event_id: str, target_user_id: str, target_display_name: str,
                  world_id: str, instance_id: str, status: str, initiated_at: str, succeeded_at: str,
                  submitted_by: str) -> SyncResult:
    if not script_url:
        return SyncResult(status="error", error_message="No Apps Script Web App URL configured.")

    try:
        response = requests.post(script_url, json={
            "action": "submit_vote_kick",
            "event_id": event_id,
            "target_user_id": target_user_id,
            "target_display_name": target_display_name,
            "world_id": world_id,
            "instance_id": instance_id,
            "status": status,
            "initiated_at": initiated_at,
            "succeeded_at": succeeded_at,
            "submitted_by": submitted_by,
        }, timeout=SCRIPT_TIMEOUT)
    except requests.RequestException as e:
        return SyncResult(status="error", error_message=str(e))

    if response.status_code != 200:
        return SyncResult(status="error", error_message=f"HTTP {response.status_code}: {_snippet(response.text)}")

    try:
        data = response.json()
    except ValueError:
        return SyncResult(
            status="error",
            error_message=f"Unexpected response from the script (not JSON): \"{_snippet(response.text)}\"",
        )

    status_out = data.get("status")
    if status_out == "success":
        return SyncResult(status="success")
    if status_out == "duplicate":
        return SyncResult(status="duplicate", error_message=data.get("message", "Another Guardian already submitted this event."))
    return SyncResult(status="error", error_message=data.get("message", "Unknown error from the script."))
