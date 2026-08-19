"""
temp_bans.py

Tracks temporary (N-day) group bans locally so Guardian can automatically
unban people once their time is up. Time keeps moving whether you're
watching it or not -- this makes sure something is.

This is separate from aar.py on purpose: the AAR is an append-only LOG of
actions taken (never edited after the fact). This file is a small, mutable
LIST of "who's still serving a temp ban and when it ends" -- entries get
removed from here once they're unbanned, which wouldn't make sense for an
audit log.

--------------------------------------------------------------------------
BEGINNER NOTES:

- Same JSON-file-as-a-list approach as aar.py, for the same reasons
  (simple, inspectable, easy to hand-fix if needed).

- due_for_unban() is the key function -- main.py calls this on a timer to
  find anyone whose ban has expired, so it can actually call VRChat's
  unban API and then remove them from this list.
--------------------------------------------------------------------------
"""

import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

TEMP_BAN_FILE = Path.home() / ".ascended_guardian" / "temp_bans.json"


@dataclass
class TempBan:
    user_id: str
    display_name: str
    group_id: str
    group_name: str
    reason: str
    banned_at: str    # ISO 8601, UTC
    expires_at: str   # ISO 8601, UTC


def expires_at_from(amount: int, unit: str) -> str:
    """
    unit is one of "minutes", "hours", "days". Returns an ISO 8601 UTC
    timestamp that many units from now.
    """
    delta_kwargs = {unit: amount}
    return (datetime.now(timezone.utc) + timedelta(**delta_kwargs)).isoformat(timespec="seconds")


def load_temp_bans() -> list[TempBan]:
    if not TEMP_BAN_FILE.exists():
        return []
    try:
        raw = json.loads(TEMP_BAN_FILE.read_text())
    except (ValueError, OSError):
        return []
    return [TempBan(**item) for item in raw]


def save_temp_bans(bans: list[TempBan]):
    TEMP_BAN_FILE.parent.mkdir(parents=True, exist_ok=True)
    TEMP_BAN_FILE.write_text(json.dumps([asdict(b) for b in bans], indent=2))


def add_temp_ban(ban: TempBan):
    bans = load_temp_bans()
    bans.append(ban)
    save_temp_bans(bans)


def remove_temp_ban(user_id: str, group_id: str):
    bans = load_temp_bans()
    bans = [b for b in bans if not (b.user_id == user_id and b.group_id == group_id)]
    save_temp_bans(bans)


def due_for_unban(now: Optional[datetime] = None) -> list[TempBan]:
    """Returns whichever temp bans have hit (or passed) their expiry time."""
    now = now or datetime.now(timezone.utc)
    due = []
    for ban in load_temp_bans():
        expires = datetime.fromisoformat(ban.expires_at)
        if expires <= now:
            due.append(ban)
    return due
