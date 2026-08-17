"""
watchlist_sync_settings.py

Local storage for the two URLs the Watchlist sync needs: the Sheet's
published CSV export (read-only pulls) and the Apps Script Web App
(submissions and reviews). Two small keys that open the shared record.
See watchlist_sync.gs and SETUP.md for how to get these two URLs in the
first place.
"""

import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

SYNC_SETTINGS_FILE = Path.home() / ".ascended_quickmod" / "watchlist_sync.json"


@dataclass
class WatchlistSyncSettings:
    csv_url: Optional[str] = None
    script_url: Optional[str] = None
    sync_interval_minutes: int = 10


def load_settings() -> WatchlistSyncSettings:
    if not SYNC_SETTINGS_FILE.exists():
        return WatchlistSyncSettings()
    try:
        raw = json.loads(SYNC_SETTINGS_FILE.read_text())
    except (ValueError, OSError):
        return WatchlistSyncSettings()
    return WatchlistSyncSettings(**raw)


def save_settings(settings: WatchlistSyncSettings):
    SYNC_SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    SYNC_SETTINGS_FILE.write_text(json.dumps(asdict(settings), indent=2))


def is_configured() -> bool:
    settings = load_settings()
    return bool(settings.csv_url and settings.script_url)
