"""
watchlist_categories.py

Different reasons someone ends up on the watchlist deserve different
visual treatment -- a predator and a VIP shouldn't both just get a
generic caution triangle. Each category has its own icon, color, and
whether it blinks (blinking is reserved for genuine threats; a VIP or
Creator tag is informational, not an alarm). Not every glow means
danger.

--------------------------------------------------------------------------
BEGINNER NOTES:

- `blinking=True` categories alternate between `color` (bright) and an
  automatically-darkened version of it (see `dim()`) every tick, same
  mechanism as before. `blinking=False` categories just show `color`
  steadily -- there's nothing to alarm about, so nothing flashes.

- "other" is the fallback for any entry that doesn't match a known
  category (including old entries saved before categories existed) --
  keeps the app from crashing on unrecognized/missing data, just shows a
  plain caution icon like the original behavior.
--------------------------------------------------------------------------
"""

from dataclasses import dataclass


@dataclass
class WatchlistCategory:
    key: str
    label: str
    icon: str
    color: str        # hex
    blinking: bool     # True = genuine threat, alternates bright/dim; False = informational, steady color


CATEGORIES = {
    "predator":  WatchlistCategory("predator", "Predator", "\U0001F6A8", "#FF3333", True),   # 🚨
    "stalker":   WatchlistCategory("stalker", "Stalker", "\U0001F441", "#FF6633", True),      # 👁
    "troll":     WatchlistCategory("troll", "Troll", "\U0001F3AD", "#FFB300", True),          # 🎭
    "poi":       WatchlistCategory("poi", "Person of Interest", "\U0001F50D", "#6C93C7", False),  # 🔍
    "vip":       WatchlistCategory("vip", "VIP", "\u2B50", "#FFD700", False),                  # ⭐
    "creator":   WatchlistCategory("creator", "Creator", "\U0001F3A8", "#29ABE2", False),      # 🎨
    "other":     WatchlistCategory("other", "Other", "\u26A0", "#CCCCCC", False),              # ⚠ fallback
}

# Order used when populating the category picker dropdown. "other" is
# DELIBERATELY first (the default selection) since it's the safest
# possible accidental pick -- an unintentional "Other" is just a vague
# flag to fix later, whereas an unintentional "Predator" as the default
# is a serious mislabel that could follow someone. Categories are then
# grouped mild-to-severe: neutral/positive first, escalating at the end.
CATEGORY_ORDER = ["other", "poi", "vip", "creator", "troll", "stalker", "predator"]


def get_category(key: str) -> WatchlistCategory:
    return CATEGORIES.get(key, CATEGORIES["other"])


def dim(hex_color: str, factor: float = 0.4) -> str:
    """Scales a hex color toward black by `factor` -- used for the 'dim' half of a blinking category's flash."""
    hex_color = hex_color.lstrip("#")
    r, g, b = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
    r, g, b = int(r * factor), int(g * factor), int(b * factor)
    return f"#{r:02X}{g:02X}{b:02X}"
