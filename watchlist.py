"""
watchlist.py

Local list of players flagged for extra attention. If a watchlisted
player shows up in the current instance, they blink (or, for
non-threatening categories, just show steadily) with a category-specific
icon in the live player list -- see watchlist_categories.py for what
each category looks like, and main.py for where it's drawn. Separate
from the AAR (a log of actions taken) and temp_bans (active enforcement)
-- this is just "keep an eye on this person," nothing automatic happens
to them. Awareness first. Action only if it's actually earned.
"""

import json
from dataclasses import dataclass, asdict
from pathlib import Path

WATCHLIST_FILE = Path.home() / ".ascended_quickmod" / "watchlist.json"


@dataclass
class WatchlistEntry:
    user_id: str
    display_name: str
    reason: str = ""
    added_at: str = ""
    category: str = "other"  # see watchlist_categories.py -- "other" keeps old entries (saved before categories existed) working


def load_entries() -> list[WatchlistEntry]:
    if not WATCHLIST_FILE.exists():
        return []
    try:
        raw = json.loads(WATCHLIST_FILE.read_text())
    except (ValueError, OSError):
        return []
    return [WatchlistEntry(**item) for item in raw]


def save_entries(entries: list[WatchlistEntry]):
    WATCHLIST_FILE.parent.mkdir(parents=True, exist_ok=True)
    WATCHLIST_FILE.write_text(json.dumps([asdict(e) for e in entries], indent=2))


def add_entry(entry: WatchlistEntry):
    entries = load_entries()
    if any(e.user_id == entry.user_id for e in entries):
        return  # already on the list -- don't duplicate
    entries.append(entry)
    save_entries(entries)


def upsert_entry(entry: WatchlistEntry):
    """
    Like add_entry(), but REPLACES an existing entry for the same user_id
    instead of silently no-op'ing. Used when syncing from the shared
    Sheet -- the sheet's data should always win for a synced entry (e.g.
    if a category got corrected there after the fact), whereas add_entry()
    intentionally protects a manually-added local entry from being
    clobbered by an accidental duplicate add.
    """
    entries = [e for e in load_entries() if e.user_id != entry.user_id]
    entries.append(entry)
    save_entries(entries)


def remove_entries(user_ids: list):
    entries = load_entries()
    entries = [e for e in entries if e.user_id not in user_ids]
    save_entries(entries)


def get_watched_ids() -> set:
    """
    Returns just the set of user_ids on the watchlist -- cheap to check
    "is this ID on the list, yes or no" without needing the full entries
    (reason/category/etc) that get_watched_entries() below returns.
    """
    return {e.user_id for e in load_entries()}


def get_watched_entries() -> dict:
    """
    user_id -> WatchlistEntry, for anywhere that needs the actual category/
    reason/etc for a watched player (not just whether they're on the
    list). Used by the player list to pick each watched player's icon and
    color based on their category.
    """
    return {e.user_id: e for e in load_entries()}
