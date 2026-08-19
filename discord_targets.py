"""
discord_targets.py

Local storage for Discord webhook targets that the AAR report can be sent
to. Each one is an Incoming Webhook -- Discord's lightweight, officially
supported way to post a message into ONE specific channel, without
running a full bot (which would need OAuth, guild/channel discovery, and
a bot token to manage). Small, direct tools beat heavy ones when heavy
isn't actually needed. You create a webhook from that channel's own
settings in Discord ("Edit Channel" -> "Integrations" -> "Webhooks" ->
"New Webhook"), copy the URL it gives you, and paste it in here.

Supporting more than one group's Discord is just multiple entries here,
each with its own name (e.g. "Ascended - #mod-reports") so they're
recognizable when picking one to send to.

--------------------------------------------------------------------------
BEGINNER NOTES:

- A webhook URL IS the credential -- anyone who has it can post messages
  into that channel as the webhook, no login required. Treat this file
  the same way as session.json: don't share it, don't paste it anywhere
  public, don't commit it to a repo.
--------------------------------------------------------------------------
"""

import json
from dataclasses import dataclass, asdict
from pathlib import Path

DISCORD_TARGETS_FILE = Path.home() / ".ascended_guardian" / "discord_targets.json"


@dataclass
class DiscordTarget:
    name: str          # whatever the team calls it, e.g. "Ascended - #mod-reports"
    webhook_url: str


def load_targets() -> list[DiscordTarget]:
    if not DISCORD_TARGETS_FILE.exists():
        return []
    try:
        raw = json.loads(DISCORD_TARGETS_FILE.read_text())
    except (ValueError, OSError):
        return []
    return [DiscordTarget(**item) for item in raw]


def save_targets(targets: list[DiscordTarget]):
    DISCORD_TARGETS_FILE.parent.mkdir(parents=True, exist_ok=True)
    DISCORD_TARGETS_FILE.write_text(json.dumps([asdict(t) for t in targets], indent=2))


def add_target(target: DiscordTarget):
    targets = load_targets()
    targets.append(target)
    save_targets(targets)


def remove_target(name: str):
    targets = load_targets()
    targets = [t for t in targets if t.name != name]
    save_targets(targets)
