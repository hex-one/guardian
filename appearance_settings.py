"""
appearance_settings.py

Local storage for the app's look-and-feel settings (wallpaper, font,
font color -- deliberately NOT player trust-rank colors, which stay tied
to VRChat's own rank colors regardless of these settings, since that
coding is a moderation signal, not decoration) plus one general behavior
setting, the player-list poll interval. Kept in the same file/dialog
section as everything else user-adjustable about how the app runs. Make
it feel like yours; just don't repaint the parts that mean something.
"""

import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

APPEARANCE_FILE = Path.home() / ".ascended_guardian" / "appearance.json"


@dataclass
class AppearanceSettings:
    wallpaper_path: Optional[str] = None
    wallpaper_mode: str = "fill"      # "fill" | "stretch" | "center" | "tile" -- see wallpaper_utils.WALLPAPER_MODES
    font_family: Optional[str] = None
    font_color: Optional[str] = None  # hex, e.g. "#EEEEEE"
    poll_interval_ms: int = 1000      # how often the player list re-checks the log file
    overlay_mode: bool = False        # skip the wallpaper, borders follow font_color -- see main.py


def load_settings() -> AppearanceSettings:
    if not APPEARANCE_FILE.exists():
        return AppearanceSettings()
    try:
        raw = json.loads(APPEARANCE_FILE.read_text())
    except (ValueError, OSError):
        return AppearanceSettings()
    return AppearanceSettings(**raw)


def save_settings(settings: AppearanceSettings):
    APPEARANCE_FILE.parent.mkdir(parents=True, exist_ok=True)
    APPEARANCE_FILE.write_text(json.dumps(asdict(settings), indent=2))
