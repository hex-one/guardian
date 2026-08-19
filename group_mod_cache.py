"""
group_mod_cache.py

Which of the logged-in user's groups they actually hold instance-
moderation, invite, or join-request-review permission in -- the
shortlist "Grp Ban From"/"Grp Kick From"/"Invite To..."/"Requests"
each draw from, filtering this same list down to whichever permission
it actually needs. Built once at startup on a background thread (so
the window opens right away, not after however long a full scan
takes), rebuildable on demand from the account menu's "Update Perms",
and kept on disk so a relaunch isn't a fully cold start either.

Two real costs shaped this:

- Checking a single group needs TWO network calls, and neither can be
  skipped or faked. get_group_details() is what actually says "do you
  hold this permission right now" -- deliberately never cached in
  vrchat_api.py, since a stale "yes" would be actively misleading for
  something this sensitive. get_group_permission_catalog() is needed
  alongside it because VRChat's permission NAMES genuinely aren't
  fixed across groups (see permission_check.py's own reasoning) -- so
  "which permission even means instance moderation here" is also a
  per-group question. A member of 200 groups is 400 calls, no way
  around either half of that.

- Nothing in this codebase talked to VRChat concurrently before this
  feature -- every existing call is a plain, one-at-a-time
  requests.Session.get() on the main thread. 400 of those back to back
  would take the better part of two minutes, which is exactly the
  "why does this feel broken" experience this whole feature exists to
  avoid. A bounded thread pool is what makes it practical -- and also
  the first place this app can realistically trip VRChat's rate
  limiting, so a basic backoff-and-retry sits underneath it. Neither
  MAX_CONCURRENT_CHECKS nor the backoff timing has been tuned against
  real-world limits -- they're reasonable starting guesses, not
  measured numbers.

This cache is a shortlist for a picker, not the last word on anything.
Whichever group actually gets chosen from it gets ONE more fresh check
right before the ban/kick dialog opens (see main.py's _on_action
handling for "KickFrom"/"BanFrom"), so a permission revoked since the
last refresh here can't slip through onto a real moderation action.

--------------------------------------------------------------------------
BEGINNER NOTES:

- get_user_group_ids() (in vrchat_api.py) is documented there as only
  seeing a player's PUBLIC group memberships. That caveat was written
  with OTHER players in mind, but it's called here on the logged-in
  user's own account too, since it's the only "list a user's groups"
  call this codebase has. Whether VRChat's API actually applies that
  same public/private restriction to your own account (as opposed to
  showing you everything about yourself regardless of what you've
  hidden from your profile) isn't something confirmed here -- worth
  keeping in mind if a group you know you're in and moderate never
  shows up in this list.
--------------------------------------------------------------------------
"""

import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Callable, Optional

import permission_check

CACHE_FILE = Path.home() / ".ascended_guardian" / "group_mod_cache.json"

MAX_CONCURRENT_CHECKS = 10    # bounded, not "all N groups at once" -- see module docstring
MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 2.0   # doubles each retry: 2s, 4s, 8s


@dataclass
class GroupPermissionEntry:
    group_id: str
    group_name: str
    can_moderate: bool
    icon_url: Optional[str] = None  # default keeps old cache files (written before this field existed) loading fine
    can_invite: bool = False  # same old-cache-file kindness as icon_url above
    can_review_join_requests: bool = False  # same kindness again -- see permission_check.has_group_join_request_permission


def load_cached() -> list[GroupPermissionEntry]:
    if not CACHE_FILE.exists():
        return []
    try:
        raw = json.loads(CACHE_FILE.read_text())
    except (ValueError, OSError):
        return []
    return [GroupPermissionEntry(**item) for item in raw]


def _save_cache(entries: list[GroupPermissionEntry]):
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    CACHE_FILE.write_text(json.dumps([asdict(e) for e in entries], indent=2))


def _check_one_group(client, group_id: str) -> Optional[GroupPermissionEntry]:
    """One group's worth of the two calls described in the module
    docstring, with a short retry/backoff if VRChat answers with
    something that looks like a rate limit. Returns None on any
    failure that isn't worth retrying -- a single group this couldn't
    resolve just gets left out of the picker, not treated as a reason
    to abandon the whole scan."""
    details = None
    for attempt in range(MAX_RETRIES):
        details = client.get_group_details(group_id)
        if details.status == "success":
            break
        looks_rate_limited = "429" in (details.error_message or "")
        if not looks_rate_limited:
            return None  # a real error (deleted group, no access, etc.) -- retrying won't fix it
        time.sleep(RETRY_BACKOFF_SECONDS * (2 ** attempt))
    else:
        return None

    if details.status != "success" or not details.name:
        return None

    catalog = client.get_group_permission_catalog(group_id)
    can_moderate = permission_check.has_instance_moderation_permission(details.my_permissions, catalog)
    # The same two calls already paid for above also answer "can invite"
    # and "can review join requests," free of charge -- nothing extra
    # spent to write both down right alongside can_moderate.
    can_invite = permission_check.has_group_invite_permission(details.my_permissions, catalog)
    can_review_join_requests = permission_check.has_group_join_request_permission(details.my_permissions, catalog)
    return GroupPermissionEntry(
        group_id=group_id, group_name=details.name, can_moderate=can_moderate,
        icon_url=details.icon_url, can_invite=can_invite,
        can_review_join_requests=can_review_join_requests,
    )


def refresh(client, on_progress: Optional[Callable[[int, int], None]] = None) -> list[GroupPermissionEntry]:
    """The full scan: every group the logged-in user belongs to,
    checked concurrently (bounded), kept only if they can actually
    moderate it, then persisted. Runs entirely on whatever thread
    calls it -- callers wanting this off the main/UI thread need to
    run it in a background thread themselves and marshal the result
    back (see main.py's _start_group_mod_cache_refresh for how this
    app does that with a Qt signal). on_progress(done, total), if
    given, is called from that same thread as results come in."""
    groups_result = client.get_user_group_ids(client.user_id)
    if groups_result.status != "success":
        return load_cached()  # couldn't even list groups -- keep whatever was already cached rather than wiping it out

    group_ids = groups_result.group_ids
    total = len(group_ids)
    entries: list[GroupPermissionEntry] = []

    with ThreadPoolExecutor(max_workers=MAX_CONCURRENT_CHECKS) as pool:
        futures = {pool.submit(_check_one_group, client, gid): gid for gid in group_ids}
        done = 0
        for future in as_completed(futures):
            done += 1
            entry = future.result()
            # Kept if it's worth something to ANY picker -- Grp Kick/Ban
            # From wants can_moderate, Invite To wants can_invite,
            # Requests wants can_review_join_requests, and a group can
            # hand you any mix of the three, independently of the others.
            if entry and (entry.can_moderate or entry.can_invite or entry.can_review_join_requests):
                entries.append(entry)
            if on_progress:
                on_progress(done, total)

    entries.sort(key=lambda e: e.group_name.lower())
    _save_cache(entries)
    return entries
