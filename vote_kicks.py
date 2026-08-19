"""
vote_kicks.py

Local record of VRChat vote-kicks Guardian has personally witnessed in
the log -- who was targeted, in which world/instance, and whether the
vote succeeded. There's deliberately no "who started it" field: VRChat's
own log never exposes that to any client, including this one (confirmed
against VRCX's log-parsing source, not guessed) -- looks like a
deliberate anti-retaliation choice on VRChat's part. What's tracked here
is exactly what the log actually gives up: the target, the room, and the
outcome. Not everything worth knowing is a thing you're allowed to know.

Mirrors watchlist.py's local-JSON-file pattern, but events aren't
deduplicated per-player the way watchlist entries are -- the same player
can rack up more than one vote-kick event over time, and each one is its
own record.
"""

import hashlib
import json
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from pathlib import Path

VOTE_KICKS_FILE = Path.home() / ".ascended_guardian" / "vote_kicks.json"

# Separate from the events themselves on purpose -- this is just "when
# did a mod last actually look," not part of the record of what
# happened. Backs the Watchlist menu's unread-style "(##)" badge (see
# main.py's _update_menu_bar_counts) and the matching count on the
# VoteKicks tab label.
VOTE_KICKS_SEEN_FILE = Path.home() / ".ascended_guardian" / "vote_kicks_seen.json"

# How long after an "initiated" event we'll still match a following
# "succeeded" line back to it. VRChat's own kick-vote timer runs well
# under this in practice -- generous on purpose so a laggy log flush
# never splits one real event into two local records.
SUCCEEDED_MATCH_WINDOW = timedelta(minutes=10)


@dataclass
class VoteKickEvent:
    event_id: str
    target_user_id: str          # "" if we couldn't resolve it against the live player list
    target_display_name: str
    world_id: str
    instance_id: str
    status: str                  # "initiated" or "succeeded"
    initiated_at: str = ""       # ISO 8601, local time -- "" if we only ever caught the success line
    succeeded_at: str = ""       # ISO 8601, local time -- "" until/unless it succeeds
    observed_by: str = ""        # this Guardian's display name


def _make_event_id(world_id: str, instance_id: str, target_display_name: str, anchor_time: datetime) -> str:
    """
    A deterministic key, not a random one -- two different Guardians
    watching the SAME real-world vote-kick independently compute the
    SAME event_id from it (same world, same instance, same target, same
    minute), which is what makes the shared sheet's first-come-first-
    served duplicate rejection actually work without the two Guardians
    ever having to talk to each other about it directly.
    """
    rounded = anchor_time.replace(second=0, microsecond=0).isoformat()
    raw = f"{world_id}|{instance_id}|{target_display_name}|{rounded}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def load_events() -> list[VoteKickEvent]:
    if not VOTE_KICKS_FILE.exists():
        return []
    try:
        raw = json.loads(VOTE_KICKS_FILE.read_text())
    except (ValueError, OSError):
        return []
    return [VoteKickEvent(**item) for item in raw]


def save_events(events: list[VoteKickEvent]):
    VOTE_KICKS_FILE.parent.mkdir(parents=True, exist_ok=True)
    VOTE_KICKS_FILE.write_text(json.dumps([asdict(e) for e in events], indent=2))


def _upsert(event: VoteKickEvent):
    events = [e for e in load_events() if e.event_id != event.event_id]
    events.append(event)
    save_events(events)


def record_initiated(target_display_name: str, target_user_id: str, world_id: str, instance_id: str,
                      timestamp: datetime, observed_by: str) -> VoteKickEvent:
    event = VoteKickEvent(
        event_id=_make_event_id(world_id, instance_id, target_display_name, timestamp),
        target_user_id=target_user_id or "",
        target_display_name=target_display_name,
        world_id=world_id or "",
        instance_id=instance_id or "",
        status="initiated",
        initiated_at=timestamp.isoformat(),
        observed_by=observed_by,
    )
    _upsert(event)
    return event


def record_succeeded(target_display_name: str, target_user_id: str, world_id: str, instance_id: str,
                      timestamp: datetime, observed_by: str) -> VoteKickEvent:
    """
    Tries to find the "initiated" record this success belongs to (same
    target/instance, still open, within SUCCEEDED_MATCH_WINDOW) and
    upgrades it in place -- same event_id, so a shared-list submission
    of the success updates the SAME row the initiation submission
    created, rather than creating a second one. Falls back to a
    standalone "succeeded"-only record if no match is found (e.g.
    Guardian was started partway through the vote and never saw the
    initiation line in the first place).
    """
    for event in load_events():
        if (event.status == "initiated" and event.target_display_name == target_display_name
                and event.world_id == (world_id or "") and event.instance_id == (instance_id or "")):
            initiated_dt = datetime.fromisoformat(event.initiated_at)
            if timestamp - initiated_dt <= SUCCEEDED_MATCH_WINDOW:
                event.status = "succeeded"
                event.succeeded_at = timestamp.isoformat()
                if target_user_id and not event.target_user_id:
                    event.target_user_id = target_user_id
                _upsert(event)
                return event

    event = VoteKickEvent(
        event_id=_make_event_id(world_id, instance_id, target_display_name, timestamp),
        target_user_id=target_user_id or "",
        target_display_name=target_display_name,
        world_id=world_id or "",
        instance_id=instance_id or "",
        status="succeeded",
        succeeded_at=timestamp.isoformat(),
        observed_by=observed_by,
    )
    _upsert(event)
    return event


def get_events_for_target(user_id: str, display_name: str = "") -> list[VoteKickEvent]:
    """
    Matches by user_id when we have one; falls back to display_name for
    the rarer records where the target couldn't be resolved against the
    live player list at the time (they'd already left, or the name
    didn't line up against anyone present).
    """
    events = load_events()
    if user_id:
        matches = [e for e in events if e.target_user_id == user_id]
        if matches:
            return matches
    if display_name:
        return [e for e in events if not e.target_user_id and e.target_display_name == display_name]
    return []


def get_targets_with_events() -> tuple:
    """
    Returns (user_ids, unresolved_display_names) -- two sets so the
    player list can flag a match either way without conflating a
    properly-resolved ID with a name-only fallback.
    """
    events = load_events()
    user_ids = {e.target_user_id for e in events if e.target_user_id}
    unresolved_names = {e.target_display_name for e in events if not e.target_user_id}
    return user_ids, unresolved_names


def _event_activity_at(event: VoteKickEvent) -> str:
    """The most recent thing that actually happened to this event --
    succeeded_at once it exists, initiated_at otherwise. Comparing
    THIS against the last-seen marker (not just initiated_at) is what
    makes a vote's outcome land as a fresh notification even if its
    initiation was already seen and cleared -- the same event earns a
    second notification when there's genuinely new information."""
    return event.succeeded_at or event.initiated_at


def get_last_seen_at() -> str:
    """"" (sorts before every real timestamp) if a mod has never opened
    the Watchlist window this install has ever recorded a vote-kick --
    everything on record counts as unseen the first time, same as any
    notification inbox would treat its very first look."""
    if not VOTE_KICKS_SEEN_FILE.exists():
        return ""
    try:
        return json.loads(VOTE_KICKS_SEEN_FILE.read_text()).get("last_seen_at", "")
    except (ValueError, OSError):
        return ""


def mark_seen_now():
    VOTE_KICKS_SEEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    VOTE_KICKS_SEEN_FILE.write_text(json.dumps({"last_seen_at": datetime.now().isoformat()}))


def get_unseen_count() -> int:
    last_seen_at = get_last_seen_at()
    return sum(1 for e in load_events() if _event_activity_at(e) > last_seen_at)
