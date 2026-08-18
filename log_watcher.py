"""
log_watcher.py

This file's job: find VRChat's log file, read new lines as they get written,
and turn those lines into simple events our app can react to. Watch the
room. Don't miss who came in or who slipped out.

VRChat writes a fresh log file every time you launch the game. The file lives
in a folder that's the same on every Windows PC (just a different username),
and looks like:

    output_log_2026-08-04_20-15-03.txt

New lines get appended to this file constantly while the game runs -- every
time someone joins, leaves, chats, etc. We don't get a "live feed" from
VRChat itself; instead we just keep re-reading the file as it grows. This is
exactly what VRCX and similar tools do.

--------------------------------------------------------------------------
BEGINNER NOTES (since you're still learning):

- A "regex" (regular expression) is a pattern used to search text. Think of
  it like a much more powerful "find" that can match patterns, not just
  exact words. We use it below to pull the player name out of a log line.

- This file defines a *class* called LogWatcher. A class is a blueprint for
  an object that has both data (like "which file am I reading") and
  behavior (like "check for new lines"). We create ONE LogWatcher and keep
  calling methods on it.

- This module has NO GUI code in it at all, on purpose. It only cares about
  "read the log, produce events." The GUI (main.py) will ask this class
  "any new events?" and update the on-screen list. Keeping these separate
  makes both halves much easier to understand and to change later.
--------------------------------------------------------------------------
"""

import os
import re
import glob
from dataclasses import dataclass
from datetime import datetime
from typing import Optional


# ---------------------------------------------------------------------------
# STEP 1: Find the log file
# ---------------------------------------------------------------------------

def find_latest_log_file() -> Optional[str]:
    """
    Returns the path to the most recently modified VRChat log file, or None
    if we can't find one (e.g. VRChat has never been run on this PC, or
    we're not running on the machine that has VRChat installed).
    """
    # %USERPROFILE% is the Windows equivalent of "home folder". This
    # expands to something like C:\Users\Jasper
    appdata_low = os.path.expandvars(r"%USERPROFILE%\AppData\LocalLow")
    log_dir = os.path.join(appdata_low, "VRChat", "VRChat")

    if not os.path.isdir(log_dir):
        return None

    # Find every file that matches VRChat's log naming pattern
    candidates = glob.glob(os.path.join(log_dir, "output_log_*.txt"))
    if not candidates:
        return None

    # Sort by "last modified time" and return the newest one
    candidates.sort(key=os.path.getmtime, reverse=True)
    return candidates[0]


# ---------------------------------------------------------------------------
# STEP 2: Define the events we care about
# ---------------------------------------------------------------------------

@dataclass
class LogEvent:
    """
    A simple container for "something happened" -- we fill in `kind` and
    whichever other fields are relevant, and leave the rest as None.

    kind is one of: "instance_change", "player_join", "player_left",
    "vote_kick_initiated", "vote_kick_succeeded"
    """
    kind: str
    display_name: Optional[str] = None
    user_id: Optional[str] = None
    world_id: Optional[str] = None
    instance_id: Optional[str] = None
    timestamp: Optional[datetime] = None  # when VRChat itself logged this line (local time)


# ---------------------------------------------------------------------------
# STEP 3: The patterns that recognize each kind of log line
# ---------------------------------------------------------------------------
#
# Real VRChat log lines look roughly like this (timestamps/prefixes vary
# slightly by game version, so these patterns focus on the stable part):
#
#   ... [Behaviour] OnPlayerJoined SomeUsername (usr_11111111-2222-...)
#   ... [Behaviour] OnPlayerLeft SomeUsername
#   ... [Behaviour] Joining wrld_abcdef12-3456-...:12345~region(us)
#
# NOTE: exact formatting has changed between VRChat versions before, so once
# you're testing this against a REAL log file, we may need to tweak these
# patterns slightly. That's expected and normal -- not a sign anything is
# broken.

RE_PLAYER_JOIN = re.compile(r"OnPlayerJoined (?P<name>.+?)(?: \((?P<uid>usr_[a-f0-9\-]+)\))?$")
RE_PLAYER_LEFT = re.compile(r"OnPlayerLeft (?P<name>.+?)(?: \((?P<uid>usr_[a-f0-9\-]+)\))?$")
# NOTE: the instance ID is everything up to the next whitespace, INCLUDING
# any ~key(value) segments (~group(...), ~groupAccessType(...), ~region(...),
# etc) -- those matter a lot (they're what instance_info.py reads to figure
# out the friendly name/region/group). An earlier version of this pattern
# used [^\s~]+ here, which stopped at the FIRST tilde and silently threw
# those segments away -- \S+ (non-whitespace) is what actually captures
# the whole thing.
RE_INSTANCE_JOIN = re.compile(r"Joining (?P<world>wrld_[a-f0-9\-]+):(?P<instance>\S+)")

# Vote-kick lines, both under the [ModerationManager] tag:
#   [ModerationManager] A vote kick has been initiated against SomeName, do you agree?
#   [ModerationManager] Vote to kick SomeName succeeded
#
# Confirmed against VRCX's own open-source LogWatcher.cs (ParseVoteKick
# Initiation/ParseVoteKickSuccess), not guessed -- and confirmed there's
# NOTHING in VRChat's log anywhere that names who started a vote. Only
# the target and the outcome are ever written down. We track exactly
# that, nothing invented to fill the gap.
RE_VOTE_KICK_INITIATED = re.compile(r"A vote kick has been initiated against (?P<name>.+?), do you agree\?")
RE_VOTE_KICK_SUCCEEDED = re.compile(r"Vote to kick (?P<name>.+?) succeeded")

# Every line VRChat writes starts with its own timestamp, e.g.
# "2026.08.04 06:22:53 Debug      -  [Behaviour] OnPlayerJoined ...". This
# is what lets us know WHEN a player joined (their "connection time"), not
# just that they did -- captured separately from the rest of the line so
# it applies the same way to every event kind below.
RE_TIMESTAMP = re.compile(r"^(\d{4}\.\d{2}\.\d{2} \d{2}:\d{2}:\d{2})")


def _parse_timestamp(line: str) -> Optional[datetime]:
    match = RE_TIMESTAMP.match(line)
    if not match:
        return None
    try:
        return datetime.strptime(match.group(1), "%Y.%m.%d %H:%M:%S")
    except ValueError:
        return None


def parse_line(line: str) -> Optional[LogEvent]:
    """
    Looks at one line of the log file and, if it matches something we care
    about, returns a LogEvent describing it. Otherwise returns None (most
    lines are irrelevant chatter/debug info -- that's expected, we just
    skip them).
    """
    timestamp = _parse_timestamp(line)

    if "OnPlayerJoined" in line:
        m = RE_PLAYER_JOIN.search(line)
        if m:
            return LogEvent(kind="player_join", display_name=m.group("name"), user_id=m.group("uid"),
                             timestamp=timestamp)

    elif "OnPlayerLeft" in line:
        m = RE_PLAYER_LEFT.search(line)
        if m:
            return LogEvent(kind="player_left", display_name=m.group("name"), user_id=m.group("uid"),
                             timestamp=timestamp)

    elif "Joining wrld_" in line:
        m = RE_INSTANCE_JOIN.search(line)
        if m:
            return LogEvent(kind="instance_change", world_id=m.group("world"), instance_id=m.group("instance"),
                             timestamp=timestamp)

    elif "vote kick has been initiated" in line:
        m = RE_VOTE_KICK_INITIATED.search(line)
        if m:
            return LogEvent(kind="vote_kick_initiated", display_name=m.group("name"), timestamp=timestamp)

    elif "Vote to kick" in line and "succeeded" in line:
        m = RE_VOTE_KICK_SUCCEEDED.search(line)
        if m:
            return LogEvent(kind="vote_kick_succeeded", display_name=m.group("name"), timestamp=timestamp)

    return None


# ---------------------------------------------------------------------------
# STEP 4: The watcher itself -- keeps track of "how far have I read"
# ---------------------------------------------------------------------------

class LogWatcher:
    """
    Wraps a single log file and lets you repeatedly ask "any new events?"

    Usage:
        watcher = LogWatcher(find_latest_log_file())
        while True:
            for event in watcher.poll():
                handle(event)
            time.sleep(1)
    """

    def __init__(self, path: str):
        self.path = path
        self._file_position = 0  # how many bytes we've already read

        # If the file already has content when we start (e.g. you launch
        # QuickMOD after you're already in a world), jump to the end so we
        # don't replay the whole session's history as "new" events.
        if path and os.path.exists(path):
            self._file_position = os.path.getsize(path)

    def poll(self) -> list[LogEvent]:
        """
        Reads any lines added to the file since the last call, parses them,
        and returns a list of LogEvents (may be empty).
        """
        if not self.path or not os.path.exists(self.path):
            return []

        events: list[LogEvent] = []

        with open(self.path, "r", encoding="utf-8", errors="ignore") as f:
            f.seek(self._file_position)
            new_lines = f.readlines()
            self._file_position = f.tell()

        for line in new_lines:
            event = parse_line(line)
            if event:
                events.append(event)

        return events


@dataclass
class ActivePlayer:
    display_name: str
    joined_at: Optional[datetime] = None  # from the log line's own timestamp, when available


@dataclass
class InstanceState:
    """
    A snapshot of "what's true right now" -- who's here, and which world/
    instance we're in. Returned by compute_initial_state() so the app can
    start already caught up, instead of starting empty and waiting for the
    next join/leave to happen.
    """
    active_players: dict[str, ActivePlayer]  # user_id (or name) -> ActivePlayer
    world_id: Optional[str] = None
    instance_id: Optional[str] = None


def compute_initial_state(path: str) -> InstanceState:
    """
    Reads the WHOLE log file from the start, but only keeps what's needed to
    answer "as of right now, who is actually in the instance with me?"

    How: find the LAST "instance_change" event in the file (that's the
    instance we're currently in -- anything before it is a previous,
    irrelevant instance), then replay every player_join/player_left from
    that point onward to build the current roster.

    This is safe to call even on a large log file -- we're just reading
    text and doing simple dict updates, no VRChat/network calls involved.
    """
    state = InstanceState(active_players={})

    if not path or not os.path.exists(path):
        return state

    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        all_lines = f.readlines()

    # Parse every line up front once, remembering the index of the last
    # instance_change so we know where to start replaying from.
    events = [parse_line(line) for line in all_lines]
    last_instance_change_index = None
    for i, event in enumerate(events):
        if event and event.kind == "instance_change":
            last_instance_change_index = i

    if last_instance_change_index is None:
        # We've never seen a "Joining wrld_..." line in this whole log --
        # unusual, but just means we can't know the current instance yet.
        return state

    change_event = events[last_instance_change_index]
    state.world_id = change_event.world_id
    state.instance_id = change_event.instance_id

    # Replay everything AFTER that instance change to rebuild who's here.
    for event in events[last_instance_change_index + 1:]:
        if event is None:
            continue
        if event.kind == "player_join":
            key = event.user_id or event.display_name
            state.active_players[key] = ActivePlayer(display_name=event.display_name, joined_at=event.timestamp)
        elif event.kind == "player_left":
            key = event.user_id or event.display_name
            state.active_players.pop(key, None)

    return state
