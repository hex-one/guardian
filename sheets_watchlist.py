"""
sheets_watchlist.py

Talks to the shared Google Sheet that backs the cross-team Watchlist --
one memory, shared across the whole team, so nobody's carrying the
knowledge alone:
  - fetch_master(): read-only pull of approved entries via the sheet's
    published CSV export -- no auth, no write access needed for this half.
  - fetch_all(): a fresh full pull (any status) used right before
    submitting a new entry, specifically to catch "already pending" or
    "already cleared" before creating a duplicate.
  - submit_entry(): POSTs a new pending entry via the Apps Script Web App
    (see watchlist_sync.gs) -- CSV export is read-only, so any WRITE has
    to go through the script instead.
  - review_entry(): approve/reject/clear an existing entry, also via the
    script. The script itself enforces the approver allowlist server-side
    -- Guardian just sends the request and shows whatever the script says.

--------------------------------------------------------------------------
BEGINNER NOTES:

- The CSV pull and the Apps Script calls are two COMPLETELY separate
  URLs, doing very different things: one is a plain file download (the
  published sheet, read-only, no code involved), the other is hitting a
  small program you deployed (the Apps Script), which is what actually
  has permission to change the sheet.

- Google Apps Script Web Apps respond to a POST with a redirect before
  the real response -- `requests` follows that automatically, so nothing
  special is needed here for that part.
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


def _normalize_csv_url(url: str) -> str:
    """
    Auto-corrects the single most common setup mistake: pasting the
    normal Google Sheets share/edit link (what the Share dialog's "Copy
    link" button gives you, ending in /edit?usp=sharing) instead of the
    special CSV export URL. That link loads the full spreadsheet web
    app -- completely different from the raw CSV data Guardian needs --
    but it's a very natural thing to paste, since the Share dialog trains
    you to copy that link for everything.

    Already-correct CSV export URLs (containing tqx=out:csv, output=csv,
    or format=csv) pass through unchanged. Anything that doesn't look
    like a Google Sheets URL at all also passes through unchanged --
    better to let the request fail with a clear "here's what we got back"
    error than to silently mangle an unrelated URL.
    """
    if any(marker in url for marker in ("tqx=out:csv", "output=csv", "format=csv")):
        return url

    match = _SHEET_ID_RE.search(url)
    if not match:
        return url

    sheet_id = match.group(1)
    return f"https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq?tqx=out:csv&sheet=Watchlist"


@dataclass
class SheetEntry:
    user_id: str
    display_name: str
    reason: str
    submitted_by: str
    submitted_at: str
    status: str  # "pending", "approved", "cleared", "rejected"
    reviewed_by: str
    reviewed_at: str
    last_validated_at: str
    category: str = "other"


@dataclass
class SyncResult:
    status: str  # "success" or "error"
    error_message: Optional[str] = None
    entries: Optional[list] = None


def _parse_csv(text: str) -> list:
    reader = csv.DictReader(io.StringIO(text))
    entries = []
    for row in reader:
        # Tolerate a sheet that's missing optional columns, or has extra
        # ones -- .get(..., "") rather than assuming every column exists.
        entries.append(SheetEntry(
            user_id=row.get("user_id", "").strip(),
            display_name=row.get("display_name", "").strip(),
            reason=row.get("reason", "").strip(),
            submitted_by=row.get("submitted_by", "").strip(),
            submitted_at=row.get("submitted_at", "").strip(),
            status=row.get("status", "").strip().lower(),
            reviewed_by=row.get("reviewed_by", "").strip(),
            reviewed_at=row.get("reviewed_at", "").strip(),
            last_validated_at=row.get("last_validated_at", "").strip(),
            category=(row.get("category", "").strip().lower() or "other"),
        ))
    return entries


_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _snippet(text: str, length: int = 300) -> str:
    """
    First bit of whatever we actually got back, for error messages --
    turns 'something's wrong' into 'here's exactly what came back, go
    look.' Strips HTML tags first: an error page's real message text
    (the actually useful part) often sits well past a few hundred
    characters of <head>/<style> boilerplate, which would otherwise
    crowd it out of a short raw snippet.
    """
    stripped = _HTML_TAG_RE.sub(" ", text)
    flat = " ".join(stripped.split())  # collapse whitespace/newlines so it reads as one line
    return flat[:length] + ("..." if len(flat) > length else "")


def _looks_like_watchlist_csv(text: str) -> bool:
    """
    Sanity check on the response BEFORE trusting it as real sheet data.
    The classic failure mode here: the Sheet's sharing isn't actually set
    to "Anyone with the link" (a common miss -- easy to assume "publish
    to web" alone is enough, but the gviz CSV endpoint specifically needs
    link-sharing turned on), so an anonymous request gets Google's HTML
    sign-in/permission page back instead of CSV -- which still comes back
    with a normal 200 status, so a status-code check alone can't catch
    it. This just confirms the "user_id" header we expect is actually
    present in the first line.
    """
    first_line = text.splitlines()[0] if text.splitlines() else ""
    return "user_id" in first_line.lower()


def fetch_master(csv_url: str) -> SyncResult:
    """
    Rows still considered active/live -- 'approved' AND 'pending_removal'
    (a removal request doesn't take a player off the live list by
    itself; they stay visible/blinking until an approver actually
    confirms the removal, same as a brand-new entry isn't live until
    ITS approval goes through). This is what Guardian trusts for live
    blinking.
    """
    if not csv_url:
        return SyncResult(status="error", error_message="No Sheet CSV URL configured.")

    csv_url = _normalize_csv_url(csv_url)

    try:
        response = requests.get(csv_url, timeout=CSV_TIMEOUT)
    except requests.RequestException as e:
        return SyncResult(status="error", error_message=str(e))

    if response.status_code != 200:
        return SyncResult(status="error", error_message=f"HTTP {response.status_code}: {_snippet(response.text)}")

    if not _looks_like_watchlist_csv(response.text):
        return SyncResult(
            status="error",
            error_message=(
                "No 'user_id' column found in the response. Guardian actually received: "
                f"\"{_snippet(response.text)}\" -- likely the Sheet's sharing isn't set to "
                "\"Anyone with the link\" (Viewer), or the tab isn't named 'Watchlist'. See SETUP.md step 3."
            ),
        )

    all_entries = _parse_csv(response.text)
    active = [e for e in all_entries if e.status in ("approved", "pending_removal") and e.user_id]
    return SyncResult(status="success", entries=active)


def fetch_all(csv_url: str) -> SyncResult:
    """Every row regardless of status -- used for the pre-submit duplicate/cleared check and the Review Queue."""
    if not csv_url:
        return SyncResult(status="error", error_message="No Sheet CSV URL configured.")

    csv_url = _normalize_csv_url(csv_url)

    try:
        response = requests.get(csv_url, timeout=CSV_TIMEOUT)
    except requests.RequestException as e:
        return SyncResult(status="error", error_message=str(e))

    if response.status_code != 200:
        return SyncResult(status="error", error_message=f"HTTP {response.status_code}: {_snippet(response.text)}")

    if not _looks_like_watchlist_csv(response.text):
        return SyncResult(
            status="error",
            error_message=(
                "No 'user_id' column found in the response. Guardian actually received: "
                f"\"{_snippet(response.text)}\" -- likely the Sheet's sharing isn't set to "
                "\"Anyone with the link\" (Viewer), or the tab isn't named 'Watchlist'. See SETUP.md step 3."
            ),
        )

    return SyncResult(status="success", entries=_parse_csv(response.text))


def _call_script(script_url: str, payload: dict) -> SyncResult:
    if not script_url:
        return SyncResult(status="error", error_message="No Apps Script Web App URL configured.")

    if "script.google.com" in script_url and not script_url.rstrip("/").endswith(("/exec", "/dev")):
        return SyncResult(
            status="error",
            error_message=(
                "That doesn't look like a deployed Apps Script Web App URL (should end in "
                "/exec). If you copied this from the script editor's address bar, use the "
                "'Web app URL' shown after Deploy \u2192 New deployment instead. See SETUP.md step 2."
            ),
        )

    try:
        response = requests.post(script_url, json=payload, timeout=SCRIPT_TIMEOUT)
    except requests.RequestException as e:
        return SyncResult(status="error", error_message=str(e))

    if response.status_code != 200:
        return SyncResult(status="error", error_message=f"HTTP {response.status_code}: {_snippet(response.text)}")

    try:
        data = response.json()
    except ValueError:
        return SyncResult(
            status="error",
            error_message=(
                f"Unexpected response from the script (not JSON). Guardian actually received: "
                f"\"{_snippet(response.text)}\" -- if that mentions signing in, the deployment's "
                "\"Who has access\" setting probably isn't set to \"Anyone\". If it says \"Error\" with "
                "no sign-in mention, the script itself is throwing an exception when it runs -- open "
                "the Apps Script editor for this sheet and check View \u2192 Executions (or the clock "
                "icon in the left sidebar) for the exact error. Two common causes: the sheet tab isn't "
                "named EXACTLY \"Watchlist\" (case-sensitive), or the script was edited after the last "
                "deployment (editing/saving alone doesn't update the live URL -- use Deploy \u2192 "
                "Manage deployments \u2192 edit \u2192 New version \u2192 Deploy). See SETUP.md step 2."
            ),
        )

    if data.get("status") != "success":
        return SyncResult(status="error", error_message=data.get("message", "Unknown error from the script."))

    return SyncResult(status="success")


def submit_entry(script_url: str, user_id: str, display_name: str, reason: str, submitted_by: str,
                  category: str = "other", confirm_resubmit: bool = False) -> SyncResult:
    """
    confirm_resubmit=True is only meaningful when the existing row's
    status is "cleared" -- the script rejects any other duplicate outright
    regardless of this flag. Guardian should only ever set this to True
    after the mod has explicitly confirmed the soft-warning prompt.
    """
    return _call_script(script_url, {
        "action": "submit",
        "user_id": user_id,
        "display_name": display_name,
        "reason": reason,
        "submitted_by": submitted_by,
        "category": category,
        "confirm_resubmit": confirm_resubmit,
    })


def review_entry(script_url: str, user_id: str, new_status: str, reviewer_id: str) -> SyncResult:
    """
    new_status is one of 'approved', 'cleared', 'rejected', 'removed'.
    The script checks reviewer_id against its own allowlist. Also used to
    finalize a removal request: 'removed' confirms it, 'approved' denies
    it (keeps the player listed) -- same review action either way, no
    separate "finalize removal" endpoint needed.
    """
    return _call_script(script_url, {
        "action": "review",
        "user_id": user_id,
        "new_status": new_status,
        "reviewer_id": reviewer_id,
    })


def request_removal(script_url: str, user_id: str, requested_by: str) -> SyncResult:
    """
    Flips an 'approved' entry to 'pending_removal' -- does NOT delete or
    deactivate it by itself. The player stays live/blinking until an
    approver actually confirms the removal via review_entry(new_status=
    "removed"), same principle as a brand-new submission not being live
    until IT'S approved. The script rejects this if the entry's current
    status isn't 'approved' (can't request removal of something that
    isn't actually live).
    """
    return _call_script(script_url, {
        "action": "request_removal",
        "user_id": user_id,
        "requested_by": requested_by,
    })


def update_display_name(script_url: str, user_id: str, display_name: str) -> SyncResult:
    return _call_script(script_url, {
        "action": "update_name",
        "user_id": user_id,
        "display_name": display_name,
    })
