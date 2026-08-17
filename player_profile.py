"""
player_profile.py

Bundles the "how invested is this account" signals shown next to each
player in the list: trust rank (color), age verification, and VRC+
subscriber status. These matter to a mod because a throwaway/troll
account usually has NONE of them -- you can't be age-verified or paying
for VRC+ on an account made five minutes ago, so seeing those badges next
to a name is a quick signal this probably isn't a throwaway. History
leaves a trace, even a short one.

All three come from the same GET /users/{id} call, so they're bundled
into one cache entry per player rather than fetched separately.
"""

from dataclasses import dataclass

import trust_rank


@dataclass
class PlayerProfile:
    rank: "trust_rank.TrustRank"
    age_verified: bool
    is_supporter: bool  # active VRC+ subscription

    @property
    def badge_text(self) -> str:
        badges = []
        if self.age_verified:
            badges.append("🪪")  # age verified (18+)
        if self.is_supporter:
            badges.append("💎")  # active VRC+ subscriber
        return " ".join(badges)

    @property
    def tooltip(self) -> str:
        lines = [self.rank.label]
        if self.age_verified:
            lines.append("Age Verified (18+)")
        if self.is_supporter:
            lines.append("VRC+ Subscriber")
        return "\n".join(lines)


def build_profile(lookup_result) -> PlayerProfile:
    """lookup_result is a vrchat_api.UserLookupResult with status == 'success'."""
    tags = lookup_result.tags or []
    return PlayerProfile(
        rank=trust_rank.determine_trust_rank(tags),
        age_verified=lookup_result.age_verified,
        is_supporter="system_supporter" in tags,
    )
