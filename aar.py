"""
aar.py

AAR = "After Action Report" -- a local log of every moderation action
Guardian takes (starting with notes; kick/ban/mute will log here too once
they're wired up). This is separate from VRChat's own note history: it's
YOUR team's local record, in a format built to be pulled later and posted
to your moderation Discord channel. A campaign log nobody else can edit
out from under you.

--------------------------------------------------------------------------
BEGINNER NOTES:

- We store this as a JSON file (a list of entries) rather than a database.
  For a moderation team's activity log, that's plenty -- easy to inspect,
  easy to back up, easy to hand-edit if something ever needs fixing. If
  this ever needs to be shared live across your whole mod team (rather
  than living on whoever's PC ran the action), that'd be the point to
  swap this for a small shared database or a webhook -- flag it if/when
  you want that, it's a natural next step.

- Each entry is a "dataclass" (AAREntry) -- just a clean way to describe
  "what fields does one log entry have" without writing a full class by
  hand. `asdict()` turns one into a plain dict for JSON saving.
--------------------------------------------------------------------------
"""

import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

AAR_FILE = Path.home() / ".ascended_guardian" / "aar_log.json"

# What "Show Bans"/"Show Kicks"/"Show Notes" in the Reports menu each
# filter down to -- Bans includes "unban" alongside "ban", since both
# are the same ban's lifecycle and a mod reviewing bans almost always
# wants to see whether one was later lifted too, not just half the
# story. "mute" exists as a possible AAREntry.action value (see below)
# but isn't wired up to anything yet, so it has no category of its own
# here -- nothing to show would just be an empty report.
ACTION_CATEGORIES = {
    "bans": {"ban", "unban"},
    "kicks": {"kick"},
    "notes": {"note"},
    "watchlist": {
        "watchlist_add", "watchlist_remove", "watchlist_removal_request",
        "watchlist_approved", "watchlist_rejected", "watchlist_cleared", "watchlist_removed",
    },
    "vote_kicks": {"vote_kick_initiated", "vote_kick_succeeded"},
    "crasher_activity": {"crasher_activity_flag"},
}


@dataclass
class AAREntry:
    timestamp: str                 # ISO 8601, UTC
    moderator: str                  # display name of whoever took the action
    action: str                     # "note", "kick", "ban", "mute", "unban"
    target_display_name: str
    target_user_id: str
    details: str                    # the note text, ban reason, etc.
    success: bool
    error_message: Optional[str] = None
    limited: bool = False           # True for a temp ban
    expires_at: Optional[str] = None  # ISO 8601, only set for temp bans


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_entries() -> list[AAREntry]:
    if not AAR_FILE.exists():
        return []
    try:
        raw = json.loads(AAR_FILE.read_text())
    except (ValueError, OSError):
        return []
    return [AAREntry(**item) for item in raw]


def save_entry(entry: AAREntry):
    AAR_FILE.parent.mkdir(parents=True, exist_ok=True)
    entries = load_entries()
    entries.append(entry)
    AAR_FILE.write_text(json.dumps([asdict(e) for e in entries], indent=2))


def clear_entries(actions: Optional[set] = None):
    """
    Wipes the local AAR log -- entirely if `actions` is omitted, or just
    the entries whose .action is IN that set otherwise (what "Clear"
    does on one of the filtered Bans/Kicks/Notes reports -- removes
    only that category from the overall AAR, leaving everything else
    exactly as it was). Destructive either way, can't be undone -- the
    caller (aar_dialog.py) is responsible for confirming with the user
    first. Note this only ever touches the LOCAL log; it has no effect
    on the actual notes/kicks/bans already applied on VRChat itself.
    """
    if actions is None:
        if AAR_FILE.exists():
            AAR_FILE.unlink()
        return

    remaining = [e for e in load_entries() if e.action not in actions]
    AAR_FILE.parent.mkdir(parents=True, exist_ok=True)
    AAR_FILE.write_text(json.dumps([asdict(e) for e in remaining], indent=2))


def latest_note_for_user(target_user_id: str) -> Optional[str]:
    """
    Looks back through the local AAR log for the most recent SUCCESSFUL
    "note" action on this player, so the Note dialog can pre-fill with
    whatever was last sent -- this is what makes "edit and update" feel
    natural even though, underneath, it's the same API call as creating
    a fresh note.
    """
    for entry in reversed(load_entries()):
        if entry.action == "note" and entry.target_user_id == target_user_id and entry.success:
            return entry.details
    return None


def export_markdown(entries: Optional[list[AAREntry]] = None) -> str:
    """
    Formats the AAR log as Markdown, suitable for pasting straight into a
    Discord channel (Discord renders basic Markdown natively). A proper
    "send to Discord automatically" button is a natural next step once
    you're ready for it (needs a webhook URL) -- this gives you the
    formatted text to paste manually in the meantime.
    """
    if entries is None:
        entries = load_entries()

    if not entries:
        return "*No moderation actions logged yet.*"

    lines = ["# Ascended Guardian — After Action Report", ""]
    for e in entries:
        status = "✅" if e.success else "❌"
        lines.append(f"**{e.timestamp}** — {status} `{e.action.upper()}` by **{e.moderator}**")
        lines.append(f"> Target: {e.target_display_name} (`{e.target_user_id}`)")
        lines.append(f"> {e.details}")
        if e.limited and e.expires_at:
            lines.append(f"> Temporary — expires {e.expires_at}")
        if not e.success and e.error_message:
            lines.append(f"> Error: {e.error_message}")
        lines.append("")

    return "\n".join(lines)
