"""
vrchat_api.py

Handles logging into VRChat's (unofficial but well-documented) web API and
keeping the resulting session so Guardian can make moderation calls later
(notes, kick, ban, mute) without needing you to log in every single time.
Trust, once earned, still has to be handled carefully -- that's the
whole design of this file.

--------------------------------------------------------------------------
BEGINNER NOTES:

- VRChat doesn't have an "official" public API, but the same API the game
  client and website use is well understood and documented by the community
  (the same API tools like VRCX use). We're using it the same way.

- Logging in with VRChat happens in up to two steps:
    1. Send your username + password. VRChat replies either "you're in" or
       "I need a 2FA code too."
    2. If it needs a 2FA code, you send that code in a second request.
  Once both steps succeed, VRChat gives your session cookies (auth and
  twoFactorAuth) -- these act like a temporary replacement for your
  password. As long as we hang onto them, we don't need your password
  again until they expire or you log out.

- We NEVER save your password to disk anywhere in this app. We only save
  those session cookies, in a file on your own PC (not sent anywhere else).
  Treat that file like you'd treat a saved login -- anyone with that file
  could act as your VRChat account until the session expires, so keep it
  private the same way you'd keep a password manager file private.

- `requests.Session()` is a nice feature of the `requests` library: once
  you make a request through a Session object, it automatically remembers
  and resends any cookies the server gave you on every future request made
  through that same Session. That's exactly the behavior we want here.
--------------------------------------------------------------------------
"""

import base64
import json
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import requests

API_BASE = "https://api.vrchat.cloud/api/1"

# VRChat requires a descriptive User-Agent identifying your app + a way to
# contact you, or it rejects requests with a 401 telling you so. The format
# VRChat expects is plain: "AppName/Version contact-info" -- NO parentheses,
# NO "contact:" label, just those two pieces separated by a space.
# If the app is renamed again or the version bumps, update this line --
# it's the only place this needs to change.
USER_AGENT = "Guardian/0.3.2 nullobserver@hexvr.net"

# Where we save session cookies so you're not re-logging-in every launch,
# and where we remember your username (NOT your password -- see
# remember_username() below) if you check "Remember me" on login.
# Named for the app's actual name now (Guardian, not the original
# QuickMOD) -- main.py's _migrate_data_dir() carries anyone's existing
# session/notes history over from the old folder name on first launch,
# so this rename doesn't quietly orphan it.
APP_DATA_DIR = Path.home() / ".ascended_guardian"
SESSION_FILE = APP_DATA_DIR / "session.json"
PREFS_FILE = APP_DATA_DIR / "prefs.json"


@dataclass
class LoginResult:
    status: str  # "success", "needs_2fa", or "error"
    two_factor_method: Optional[str] = None   # "totp" or "emailOtp"
    error_message: Optional[str] = None
    display_name: Optional[str] = None
    user_id: Optional[str] = None


@dataclass
class NoteResult:
    status: str  # "success" or "error"
    note_id: Optional[str] = None
    error_message: Optional[str] = None


# -- Remembering your username (never your password) -------------------
#
# "Remember me" on the login screen controls two independent things:
#   1. Your username, saved in plain text here (usernames aren't secret --
#      this just saves you re-typing it).
#   2. Whether we keep the session cookie around (see save_session() /
#      clear_saved_session() below) -- THAT'S what actually keeps you
#      logged in between launches. Your password itself is never saved
#      anywhere, checkbox or not.

def remember_username(username: str):
    APP_DATA_DIR.mkdir(parents=True, exist_ok=True)
    PREFS_FILE.write_text(json.dumps({"remembered_username": username}))


def get_remembered_username() -> Optional[str]:
    if not PREFS_FILE.exists():
        return None
    try:
        data = json.loads(PREFS_FILE.read_text())
    except (ValueError, OSError):
        return None
    return data.get("remembered_username")


def forget_username():
    if PREFS_FILE.exists():
        PREFS_FILE.unlink()


@dataclass
class UserLookupResult:
    status: str  # "success" or "error"
    note: Optional[str] = None
    display_name: Optional[str] = None
    tags: Optional[list] = None
    age_verified: bool = False
    bio: Optional[str] = None
    pronouns: Optional[str] = None
    status_text: Optional[str] = None
    status_description: Optional[str] = None
    date_joined: Optional[str] = None
    last_login: Optional[str] = None
    last_platform: Optional[str] = None
    avatar_thumbnail_url: Optional[str] = None
    user_icon_url: Optional[str] = None
    icon_url: Optional[str] = None
    profile_pic_override: Optional[str] = None
    is_friend: bool = False
    error_message: Optional[str] = None


@dataclass
class ModerationResult:
    status: str  # "success" or "error"
    error_message: Optional[str] = None


@dataclass
class GroupDetailsResult:
    status: str  # "success" or "error"
    name: Optional[str] = None
    icon_url: Optional[str] = None
    my_permissions: Optional[list] = None
    error_message: Optional[str] = None


@dataclass
class UserGroupsResult:
    status: str  # "success" or "error"
    group_ids: Optional[list] = None
    error_message: Optional[str] = None


@dataclass
class GroupJoinRequest:
    user_id: str
    display_name: str
    icon_url: Optional[str] = None
    requested_at: Optional[str] = None  # ISO 8601, per VRChat's createdAt


@dataclass
class GroupJoinRequestsResult:
    status: str  # "success" or "error"
    requests: Optional[list] = None  # list[GroupJoinRequest]
    error_message: Optional[str] = None


class VRChatClient:
    """
    Wraps a logged-in (or logging-in) VRChat session. Create one of these,
    call login(), possibly verify_2fa(), and then you have an authenticated
    `self.session` that future features (notes/kick/ban/mute) will reuse.
    """

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})
        self.display_name: Optional[str] = None
        self.user_id: Optional[str] = None

        # World name AND capacity essentially never change, so both get
        # cached together off the SAME /worlds/{id} response for the life
        # of this client instead of re-fetching on every instance change --
        # keeps the friendly-name feature (and the player-count display)
        # cheap even if you hop between the same few worlds all session.
        self._world_details_cache: dict[str, dict] = {}
        self._group_name_cache: dict[str, str] = {}
        self._group_permission_catalog_cache: dict[str, list] = {}

    # -- Logging in ------------------------------------------------------

    def login(self, username: str, password: str) -> LoginResult:
        """
        Step 1 of login: send username + password. VRChat's docs specify
        that both need to be individually URL-encoded before being joined
        with a colon and base64-encoded for the Authorization header --
        that's what's happening below.
        """
        credentials = f"{urllib.parse.quote(username)}:{urllib.parse.quote(password)}"
        encoded = base64.b64encode(credentials.encode()).decode()

        response = self.session.get(
            f"{API_BASE}/auth/user",
            headers={"Authorization": f"Basic {encoded}"},
        )

        return self._handle_user_response(response)

    def verify_2fa(self, code: str, method: str) -> LoginResult:
        """
        Step 2 of login (only needed if login() returned status="needs_2fa").
        `method` should be whatever login() told you: "totp" (authenticator
        app) or "emailOtp" (code emailed to you).
        """
        endpoint = "totp" if method == "totp" else "emailotp"
        response = self.session.post(
            f"{API_BASE}/auth/twofactorauth/{endpoint}/verify",
            json={"code": code},
        )

        if response.status_code != 200:
            return LoginResult(status="error", error_message=self._error_message(response))

        # The 2FA cookie is now set. Fetch the actual user info to confirm
        # we're really in (rather than just trusting the 200 status code).
        confirm_response = self.session.get(f"{API_BASE}/auth/user")
        return self._handle_user_response(confirm_response)

    def _handle_user_response(self, response: requests.Response) -> LoginResult:
        if response.status_code != 200:
            return LoginResult(status="error", error_message=self._error_message(response))

        data = response.json()

        needs_2fa = data.get("requiresTwoFactorAuth")
        if needs_2fa:
            return LoginResult(status="needs_2fa", two_factor_method=needs_2fa[0])

        self.display_name = data.get("displayName")
        self.user_id = data.get("id")
        return LoginResult(status="success", display_name=self.display_name, user_id=self.user_id)

    @staticmethod
    def _error_message(response: requests.Response) -> str:
        try:
            data = response.json()
            return data.get("error", {}).get("message", f"HTTP {response.status_code}")
        except ValueError:
            return f"HTTP {response.status_code}"

    # -- Moderation actions -----------------------------------------------

    def get_group_details(self, group_id: str) -> GroupDetailsResult:
        """
        Fetches the group AND, crucially, "myMember" -- VRChat's own
        resolved view of the logged-in user's membership in this group,
        including their combined permissions from all assigned roles.
        Deliberately NOT cached (unlike get_group_name()) -- this backs
        the permission traffic light, and a stale "yes you can moderate"
        after a role change would be actively misleading, so this always
        hits the network fresh. It does still warm the name cache as a
        side effect, so get_group_name() benefits too.
        """
        response = self.session.get(f"{API_BASE}/groups/{group_id}")
        if response.status_code != 200:
            return GroupDetailsResult(status="error", error_message=self._error_message(response))

        data = response.json()
        name = data.get("name")
        if name:
            self._group_name_cache[group_id] = name

        my_member = data.get("myMember") or {}
        return GroupDetailsResult(
            status="success",
            name=name,
            icon_url=data.get("iconUrl") or None,
            my_permissions=my_member.get("permissions", []),
        )

    def get_group_permission_catalog(self, group_id: str) -> list:
        """
        The group's full list of possible permissions (name + human-
        readable description of what it does). This is genuinely static
        content (what permissions COULD exist), unlike who currently HAS
        them, so this one is cached.
        """
        if group_id in self._group_permission_catalog_cache:
            return self._group_permission_catalog_cache[group_id]

        response = self.session.get(f"{API_BASE}/groups/{group_id}/permissions")
        if response.status_code != 200:
            return []

        catalog = response.json()
        self._group_permission_catalog_cache[group_id] = catalog
        return catalog

    def get_user_group_ids(self, user_id: str) -> UserGroupsResult:
        """
        A player's PUBLIC group memberships (GET /users/{id}/groups). Used
        to check "is this player a member of the group hosting this
        instance", for showing the group icon next to their name.

        Caveat worth knowing: this only sees groups a player hasn't hidden
        from their profile -- VRChat lets members obscure a group's
        affiliation from showing in their public list. A member who's done
        that for this group won't show the icon, even though they really
        are a member. There's no way to see past that from outside the
        group's own membership-management tools.
        """
        response = self.session.get(f"{API_BASE}/users/{user_id}/groups")
        if response.status_code != 200:
            return UserGroupsResult(status="error", error_message=self._error_message(response))

        data = response.json()
        group_ids = [g.get("groupId") for g in data if g.get("groupId")]
        return UserGroupsResult(status="success", group_ids=group_ids)

    def _get_world_details(self, world_id: str) -> dict:
        """Shared fetch behind get_world_name()/get_world_capacity() --
        one request per world, not two. Failures are deliberately NOT
        cached (unlike a real success) so a transient network hiccup
        gets retried next time instead of being stuck showing "unknown"
        for the rest of the session."""
        if world_id in self._world_details_cache:
            return self._world_details_cache[world_id]

        response = self.session.get(f"{API_BASE}/worlds/{world_id}")
        if response.status_code != 200:
            return {"name": None, "capacity": None}

        data = response.json()
        details = {"name": data.get("name"), "capacity": data.get("capacity")}
        if details["name"]:
            self._world_details_cache[world_id] = details
        return details

    def get_world_name(self, world_id: str) -> Optional[str]:
        """
        Resolves a world_id (e.g. "wrld_...") into its display name (e.g.
        "Idle Home"). Returns None on failure rather than raising -- a
        missing friendly name shouldn't ever crash anything, it should
        just fall back to showing the raw ID.
        """
        return self._get_world_details(world_id).get("name")

    def get_world_capacity(self, world_id: str) -> Optional[int]:
        """The world's recommended/max instance size, straight from the
        same world lookup get_world_name() already does -- used for the
        "N / capacity" player count in the main window. None if it
        couldn't be resolved; callers should just omit the "/ capacity"
        part rather than show a placeholder for unknown data."""
        return self._get_world_details(world_id).get("capacity")

    def get_group_name(self, group_id: str) -> Optional[str]:
        """Same idea as get_world_name(), for a group_id (e.g. "grp_...")."""
        if group_id in self._group_name_cache:
            return self._group_name_cache[group_id]

        response = self.session.get(f"{API_BASE}/groups/{group_id}")
        if response.status_code != 200:
            return None

        name = response.json().get("name")
        if name:
            self._group_name_cache[group_id] = name
        return name

    def invite_user_to_group(self, group_id: str, target_user_id: str) -> ModerationResult:
        """Invites a player to JOIN the group (membership invite, not an instance invite)."""
        response = self.session.post(f"{API_BASE}/groups/{group_id}/invites", json={"userId": target_user_id})
        if response.status_code != 200:
            return ModerationResult(status="error", error_message=self._error_message(response))
        return ModerationResult(status="success")

    def get_group_join_requests(self, group_id: str) -> GroupJoinRequestsResult:
        """GET /groups/{groupId}/requests -- pending membership join requests
        waiting at the door for a moderator to say yes or no (the "someone
        asked to join" queue, the opposite current from the group-membership
        invites this app sends via invite_user_to_group()/InviteDialog).
        Confirmed against VRChat's own published OpenAPI spec
        (vrchatapi/specification) rather than guessed at, since this touches
        a real moderation call against a real shared community -- some
        things you check twice before you speak."""
        response = self.session.get(f"{API_BASE}/groups/{group_id}/requests")
        if response.status_code != 200:
            return GroupJoinRequestsResult(status="error", error_message=self._error_message(response))

        join_requests = []
        for item in response.json():
            user = item.get("user") or {}
            user_id = item.get("userId") or user.get("id")
            if not user_id:
                continue  # can't act on a request with no user id -- skip rather than crash
            join_requests.append(GroupJoinRequest(
                user_id=user_id,
                display_name=user.get("displayName") or "(unknown)",
                icon_url=user.get("profilePicOverride") or user.get("iconUrl") or user.get("currentAvatarThumbnailImageUrl"),
                requested_at=item.get("createdAt"),
            ))
        return GroupJoinRequestsResult(status="success", requests=join_requests)

    def respond_to_group_join_request(self, group_id: str, target_user_id: str, accept: bool) -> ModerationResult:
        """PUT /groups/{groupId}/requests/{userId} -- say yes or no to a
        pending join request. VRChat's own action values are the words
        "accept"/"reject", not a boolean -- accept=False here just reaches
        for "reject" so callers never have to remember that string
        themselves."""
        action = "accept" if accept else "reject"
        response = self.session.put(
            f"{API_BASE}/groups/{group_id}/requests/{target_user_id}", json={"action": action}
        )
        if response.status_code != 200:
            return ModerationResult(status="error", error_message=self._error_message(response))
        return ModerationResult(status="success")

    def kick_from_group(self, group_id: str, target_user_id: str) -> ModerationResult:
        """
        Kicks a player from the GROUP (not the live instance). This removes
        their group membership -- they can rejoin later per the group's own
        join settings, unlike a ban. This is what VRCX's "Kick" button in
        its group moderation panel actually does; confirmed against the
        same endpoint VRChat's own docs describe as the way to reverse a
        group ban.
        """
        response = self.session.delete(f"{API_BASE}/groups/{group_id}/members/{target_user_id}")
        if response.status_code != 200:
            return ModerationResult(status="error", error_message=self._error_message(response))
        return ModerationResult(status="success")

    def ban_from_group(self, group_id: str, target_user_id: str) -> ModerationResult:
        """
        Bans a player from the group that owns the instance -- this is the
        real, REST-backed "Ban From Group" action (blocks them from any of
        that group's instances, and from the group itself). This is a
        genuinely destructive action; the caller is responsible for
        confirming with the mod before calling this.
        """
        response = self.session.post(f"{API_BASE}/groups/{group_id}/bans", json={"userId": target_user_id})
        if response.status_code != 200:
            return ModerationResult(status="error", error_message=self._error_message(response))
        return ModerationResult(status="success")

    def unban_from_group(self, group_id: str, target_user_id: str) -> ModerationResult:
        """Reverses ban_from_group() -- used for both manual unbans and temp-ban expiry."""
        response = self.session.delete(f"{API_BASE}/groups/{group_id}/bans/{target_user_id}")
        if response.status_code != 200:
            return ModerationResult(status="error", error_message=self._error_message(response))
        return ModerationResult(status="success")

    def get_user(self, target_user_id: str) -> UserLookupResult:
        """
        Fetches a player's public profile -- which conveniently also
        includes YOUR current note on them (if any) in the "note" field.
        This is what lets the Note dialog show what's actually on file
        right now, instead of only what we remember locally.
        """
        response = self.session.get(f"{API_BASE}/users/{target_user_id}")

        if response.status_code != 200:
            return UserLookupResult(status="error", error_message=self._error_message(response))

        data = response.json()
        # VRChat returns "" (empty string) rather than omitting the field
        # when there's no note -- normalize that to None so callers can
        # just check `if result.note:`.
        return UserLookupResult(
            status="success",
            note=data.get("note") or None,
            display_name=data.get("displayName"),
            tags=data.get("tags", []),
            age_verified=bool(data.get("ageVerified", False)),
            bio=data.get("bio") or None,
            pronouns=data.get("pronouns") or None,
            status_text=data.get("status") or None,
            status_description=data.get("statusDescription") or None,
            date_joined=data.get("date_joined") or None,
            last_login=data.get("last_login") or None,
            last_platform=data.get("last_platform") or None,
            avatar_thumbnail_url=data.get("currentAvatarThumbnailImageUrl") or None,
            user_icon_url=data.get("userIcon") or None,
            icon_url=data.get("iconUrl") or None,
            profile_pic_override=data.get("profilePicOverride") or None,
            is_friend=bool(data.get("isFriend", False)),
        )

    def set_user_note(self, target_user_id: str, note_text: str) -> NoteResult:
        """
        Creates OR updates your note on this player. VRChat uses the exact
        same endpoint for both -- there's only ever one note per player per
        account, so posting again just overwrites whatever was there before.
        That's what makes "editing" a note the same code path as "creating"
        one from our side.
        """
        response = self.session.post(
            f"{API_BASE}/userNotes",
            json={"note": note_text, "targetUserId": target_user_id},
        )

        if response.status_code != 200:
            return NoteResult(status="error", error_message=self._error_message(response))

        data = response.json()
        return NoteResult(status="success", note_id=data.get("id"))

    # -- Remembering the session so you don't re-login every launch ------

    def save_session(self):
        SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
        cookies = requests.utils.dict_from_cookiejar(self.session.cookies)
        SESSION_FILE.write_text(json.dumps(cookies))

    def try_load_session(self) -> bool:
        """
        Attempts to resume a previously saved session. Returns True if it
        worked (you're logged in), False if there was no saved session or
        it's expired/invalid (in which case, just log in normally).
        """
        if not SESSION_FILE.exists():
            return False

        try:
            cookies = json.loads(SESSION_FILE.read_text())
        except (ValueError, OSError):
            return False

        self.session.cookies.update(cookies)

        response = self.session.get(f"{API_BASE}/auth/user")
        result = self._handle_user_response(response)
        return result.status == "success"

    def clear_saved_session(self):
        if SESSION_FILE.exists():
            SESSION_FILE.unlink()
