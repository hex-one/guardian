"""
trust_rank.py

Maps a VRChat user's tags to their Trust Rank and a color for the player
list, so at a glance you can see who's more established vs brand new.
Purple for Trusted User, obviously -- some things are just correct.

--------------------------------------------------------------------------
BEGINNER NOTES:

- VRChat encodes trust rank as one of several tags on a user's profile
  (the "tags" field from GET /users/{id}). Confusingly, VRChat's own tag
  NAMES are offset by one level from what they actually mean --
  "system_trust_trusted" tag really means "Known User" rank, and
  "system_trust_veteran" really means "Trusted User" (the top rank a
  normal player can reach; there's no tag literally called
  "system_trust_trusted_user"). This is VRChat's own naming quirk, not a
  bug here -- we just have to know about it. Confirmed against VRChat's
  own tag documentation, not guessed.

- Colors below match VRChat's own in-game nameplate colors, so what you
  see in Guardian lines up with what you'd see in-game.

- Moderation flags (confirmed troll, VRChat staff) are checked FIRST,
  before the normal trust ladder -- those are more useful to a mod at a
  glance than "they're also technically a User rank".
--------------------------------------------------------------------------
"""

from dataclasses import dataclass


@dataclass
class TrustRank:
    key: str
    label: str
    color: str  # hex, matches VRChat's own nameplate colors


RANKS = {
    "visitor":      TrustRank("visitor", "Visitor", "#CCCCCC"),
    "new_user":     TrustRank("new_user", "New User", "#1778FF"),
    "user":         TrustRank("user", "User", "#2BCF5C"),
    "known_user":   TrustRank("known_user", "Known User", "#FF7B42"),
    "trusted_user": TrustRank("trusted_user", "Trusted User", "#B18FFF"),
    "troll":        TrustRank("troll", "Flagged / Troll", "#E85C5C"),
    "moderator":    TrustRank("moderator", "VRChat Team", "#FF2626"),
}

# Sort priority for "sort by rank" in the player list -- lower number sorts
# first. Roughly "most established/notable account first": VRChat staff,
# then the normal trust ladder from highest to lowest, with flagged
# accounts pushed to the very end regardless of any trust tag they also carry.
RANK_SORT_ORDER = {
    "moderator": 0,
    "trusted_user": 1,
    "known_user": 2,
    "user": 3,
    "new_user": 4,
    "visitor": 5,
    "troll": 6,
}


def determine_trust_rank(tags: list[str]) -> TrustRank:
    """
    tags is whatever VRChat's GET /users/{id} returned in its "tags" field.
    Checked in priority order: moderation flags first, then the trust
    ladder from highest to lowest (a user only ever carries their current
    rank's tag, but checking top-down is a harmless safety net).
    """
    tags = tags or []

    if "admin_moderator" in tags:
        return RANKS["moderator"]
    if "system_troll" in tags:
        return RANKS["troll"]
    if "system_trust_veteran" in tags:
        return RANKS["trusted_user"]
    if "system_trust_trusted" in tags:
        return RANKS["known_user"]
    if "system_trust_known" in tags:
        return RANKS["user"]
    if "system_trust_basic" in tags:
        return RANKS["new_user"]
    return RANKS["visitor"]
