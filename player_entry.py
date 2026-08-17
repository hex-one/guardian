"""
player_entry.py

Represents one player's tracked state in the instance list. Unlike the
earlier version of this app, a player who leaves doesn't just vanish from
the list -- they're marked "departed" and stick around (greyed out, with
how long ago they left) so a mod can still see/act on who was just here.
Nobody who mattered gets erased the instant they step out of the room.
main.py prunes departed entries once they're old enough (see
DEPARTED_RETENTION in main.py).
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class PlayerEntry:
    user_id: str
    display_name: str
    joined_at: datetime           # local time -- either from the log line's own timestamp, or now() if unknown
    status: str = "present"        # "present" or "departed"
    departed_at: Optional[datetime] = None
