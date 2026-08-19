"""
crasher_activity.py

Local-only record of "possible crasher activity" -- a Udon script
exception observed close in time to a player switching avatars nearby.
Circumstantial, not proof: a genuinely broken (not malicious) avatar
throws the exact same kind of exception a deliberately hostile one
does, and VRChat's log never says which one happened. Every flag here
is a correlation in time, nothing more.

Deliberately NOT synced to any shared list the way Watchlist and
VoteKicks are -- those track things VRChat itself confirms (a vote's
outcome, a submission a human reviews before it goes live). This
tracks a *guess*, and broadcasting an unverified "this player might be
a crasher" across a whole mod team risks putting a real accusation on
someone whose avatar just had a bug. Stays local, stays in this
Guardian's own AAR, and stays a mod's judgment call to escalate
further if they choose to.
"""

import hashlib
import json
from dataclasses import dataclass, asdict
from pathlib import Path

CRASHER_ACTIVITY_FILE = Path.home() / ".ascended_guardian" / "crasher_activity.json"


@dataclass
class CrasherCandidate:
    display_name: str
    user_id: str              # "" if we couldn't resolve them against the live player list
    avatar_name: str
    seconds_before_exception: float


@dataclass
class CrasherFlag:
    flag_id: str
    observed_at: str          # ISO 8601, local time -- when the triggering signal itself fired
    world_id: str
    instance_id: str
    observed_by: str
    candidates: list          # list of CrasherCandidate -- more than one means genuinely ambiguous, not "pick one"
    signal: str = "udon_exception"       # "udon_exception" | "model_validation_warning" | "crash_after_validation_warning"
    confidence: str = "circumstantial"   # "circumstantial" | "strong" -- see main.py's _flag_silent_crash for what earns "strong"


def _make_flag_id(observed_at: str, world_id: str, instance_id: str) -> str:
    raw = f"{observed_at}|{world_id}|{instance_id}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def load_flags() -> list[CrasherFlag]:
    if not CRASHER_ACTIVITY_FILE.exists():
        return []
    try:
        raw = json.loads(CRASHER_ACTIVITY_FILE.read_text())
    except (ValueError, OSError):
        return []
    flags = []
    for item in raw:
        candidates = [CrasherCandidate(**c) for c in item.get("candidates", [])]
        flags.append(CrasherFlag(
            flag_id=item["flag_id"], observed_at=item["observed_at"], world_id=item["world_id"],
            instance_id=item["instance_id"], observed_by=item["observed_by"], candidates=candidates,
            # .get() with defaults -- flags saved before these fields existed
            # just read back as ordinary circumstantial udon-exception flags,
            # which is exactly what they were at the time.
            signal=item.get("signal", "udon_exception"),
            confidence=item.get("confidence", "circumstantial"),
        ))
    return flags


def save_flags(flags: list[CrasherFlag]):
    CRASHER_ACTIVITY_FILE.parent.mkdir(parents=True, exist_ok=True)
    CRASHER_ACTIVITY_FILE.write_text(json.dumps([asdict(f) for f in flags], indent=2))


def record_flag(candidates: list, world_id: str, instance_id: str, observed_by: str, observed_at: str,
                 signal: str = "udon_exception", confidence: str = "circumstantial") -> CrasherFlag:
    """
    `candidates` is a list of CrasherCandidate -- every player who
    switched avatars inside the correlation window, not just the
    "likeliest" one. When there's more than one, that ambiguity is the
    honest finding: this doesn't get to guess which of them it actually
    was.
    """
    flag = CrasherFlag(
        flag_id=_make_flag_id(observed_at, world_id or "", instance_id or ""),
        observed_at=observed_at,
        world_id=world_id or "",
        instance_id=instance_id or "",
        observed_by=observed_by,
        candidates=candidates,
        signal=signal,
        confidence=confidence,
    )
    flags = [f for f in load_flags() if f.flag_id != flag.flag_id]
    flags.append(flag)
    save_flags(flags)
    return flag


def get_flags_for_target(user_id: str, display_name: str = "") -> list[CrasherFlag]:
    """Any flag where this player appears as ONE of the candidates --
    including ambiguous flags naming other people too. The caller's job
    is to show that ambiguity plainly, not hide it."""
    flags = load_flags()
    matches = []
    for flag in flags:
        for c in flag.candidates:
            if (user_id and c.user_id == user_id) or (not c.user_id and display_name and c.display_name == display_name):
                matches.append(flag)
                break
    return matches


def get_targets_with_flags() -> tuple:
    """Returns (user_ids, unresolved_display_names) across every
    candidate in every flag -- same two-set shape as vote_kicks.py's
    get_targets_with_events(), for the same reason: a resolved ID and a
    name-only fallback shouldn't get conflated."""
    flags = load_flags()
    user_ids = set()
    unresolved_names = set()
    for flag in flags:
        for c in flag.candidates:
            if c.user_id:
                user_ids.add(c.user_id)
            else:
                unresolved_names.add(c.display_name)
    return user_ids, unresolved_names
