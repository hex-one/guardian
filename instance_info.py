"""
instance_info.py

Turns the raw instance string the log gives us (e.g.
"wrld_c16e4dee-...:15867~group(grp_3de3...)~groupAccessType(public)~region(use)")
into something a human can read at a glance, e.g. "Idle Home — Group Public
(US East) · Ascended". A gibberish string turned into "here's where you
actually are."

--------------------------------------------------------------------------
BEGINNER NOTES:

- This file does two very different jobs, kept separate on purpose:
    1. parse_instance_id() -- pure text parsing of the instance string.
       No network calls, can't fail, always instant.
    2. describe_instance() -- takes what parse_instance_id() figured out
       and asks VRChat's API for the actual WORLD NAME (and GROUP NAME, if
       it's a group instance) to fill in the human-readable parts. This
       needs network calls, so it can fail or be slow -- results get
       cached on the client so we're not re-asking VRChat for the same
       world's name every single time.

- The `~key(value)` segments after the numeric instance ID are how VRChat
  encodes instance type/region/group/etc into one string. `_SEGMENT_RE`
  just pulls all of those out into a dict so the rest of the code doesn't
  need to hand-parse them.
--------------------------------------------------------------------------
"""

import re
from dataclasses import dataclass
from typing import Optional

_SEGMENT_RE = re.compile(r"~(\w+)(?:\((.*?)\))?")

REGION_LABELS = {
    "us": "US West",
    "usw": "US West",
    "use": "US East",
    "eu": "Europe",
    "jp": "Japan",
}

TYPE_LABELS = {
    "public": "Public",
    "friends": "Friends",
    "invite": "Invite Only",
    "invite+": "Invite+",
    "group-public": "Group Public",
    "group-plus": "Group+",
    "group-members": "Group Members",
}


@dataclass
class ParsedInstance:
    instance_number: str
    instance_type: str   # one of the keys in TYPE_LABELS
    region_label: str
    group_id: Optional[str] = None


def parse_instance_id(instance_id: str) -> ParsedInstance:
    """
    Pure text parsing -- no network calls, always succeeds. Splits off the
    leading number and reads the ~key(value) segments that follow it.
    """
    parts = instance_id.split("~", 1)
    number = parts[0]
    tail = "~" + parts[1] if len(parts) > 1 else ""

    segments = dict(_SEGMENT_RE.findall(tail))

    region_code = segments.get("region", "").lower()
    region_label = REGION_LABELS.get(region_code, region_code.upper() or "Unknown region")

    group_id = segments.get("group")

    if group_id:
        access = segments.get("groupAccessType", "members")
        instance_type = f"group-{access}"
    elif "hidden" in segments:
        instance_type = "friends"
    elif "private" in segments:
        instance_type = "invite+" if "canRequestInvite" in segments else "invite"
    else:
        instance_type = "public"

    return ParsedInstance(
        instance_number=number,
        instance_type=instance_type,
        region_label=region_label,
        group_id=group_id,
    )


def describe_instance_base(client, world_id: str, parsed: ParsedInstance) -> str:
    """
    World name + type + region only, no group suffix -- lets main.py
    assemble the final label itself so it can insert the permission
    traffic-light dot right before the group name.
    """
    world_name = client.get_world_name(world_id) or world_id
    return f"{world_name} — {TYPE_LABELS.get(parsed.instance_type, parsed.instance_type)} ({parsed.region_label})"


def describe_instance(client, world_id: str, raw_instance_id: str) -> str:
    """
    The full human-friendly one-liner, including the group name (no
    permission dot -- that's main.py's job since it needs a rich-text
    label). Needs an authenticated VRChatClient (for the world/group name
    lookups) -- falls back gracefully to raw IDs for any piece that fails
    to resolve, rather than failing the whole label.
    """
    parsed = parse_instance_id(raw_instance_id)
    label = describe_instance_base(client, world_id, parsed)

    if parsed.group_id:
        group_name = client.get_group_name(parsed.group_id)
        if group_name:
            label += f" · {group_name}"

    return label
