"""
permission_check.py

Figures out whether the logged-in Guardian user can moderate the current
group's instances -- shown as the green/red traffic-light dot next to the
group name. Know your own standing before you act on someone else's.

--------------------------------------------------------------------------
BEGINNER NOTES:

- VRChat doesn't publicly document a single fixed permission name we could
  just hardcode and check for. Instead, this looks up the group's own
  permission CATALOG (a list of {name, displayName, help} -- what
  permissions could possibly exist for this group) and matches against
  whichever entry's description actually describes instance moderation
  (kicking/managing/banning within instances), then checks whether that
  permission is in the logged-in user's own resolved permission list for
  this group.

- "*" in the user's permission list means full access (owner/admin) --
  that always counts as having every permission, instance moderation
  included.

- This is deliberately DATA-DRIVEN rather than a hardcoded guess. VRChat's
  internal permission name strings could differ across groups or change
  over time; matching against the catalog's own human-readable
  description is more reliable than assuming a fixed string is always
  correct -- getting this wrong (showing green when someone actually can't
  moderate, or vice versa) is worse than a hardcoded guess quietly going
  stale.
--------------------------------------------------------------------------
"""

# Keywords that, together, describe "this permission is about moderating
# players within instances" (kicking, banning, managing instances) as
# opposed to unrelated permissions like managing group posts or galleries.
_INSTANCE_KEYWORDS = ("instance",)
_MODERATION_KEYWORDS = ("moderate", "manage", "kick", "ban")


def has_group_invite_permission(my_permissions: list, catalog: list) -> bool:
    """Same approach as has_instance_moderation_permission, matched against 'invite'-related permissions."""
    my_permissions = my_permissions or []

    if "*" in my_permissions:
        return True

    for perm in catalog or []:
        name = perm.get("name") or ""
        display = (perm.get("displayName") or "").lower()
        help_text = (perm.get("help") or "").lower()
        if "invite" in f"{display} {help_text}" and name in my_permissions:
            return True

    return False


def has_group_join_request_permission(my_permissions: list, catalog: list) -> bool:
    """Same data-driven approach as the others, matched against whatever
    permission stands guard at a group's pending-join-request door. Less
    sure-footed than has_instance_moderation_permission/has_group_invite_
    permission above -- those two are already out in the world, tested
    by real use, while VRChat's never published a confirmed catalog
    entry name for this one anywhere this got checked against. Matches
    "member" (not the vaguer "request", which turns up in unrelated
    help text more often than it's worth) alongside a management verb.
    Same safety net as every permission check in this codebase carries
    regardless: this only decides what the picker SHOWS you -- the real
    gate is VRChat's own answer to the actual request, which turns you
    away with 401/403 no matter what this function happens to guess."""
    my_permissions = my_permissions or []

    if "*" in my_permissions:
        return True

    for perm in catalog or []:
        name = perm.get("name") or ""
        display = (perm.get("displayName") or "").lower()
        help_text = (perm.get("help") or "").lower()
        combined = f"{display} {help_text}"

        mentions_members = "member" in combined
        mentions_manage = "manage" in combined or "invite" in combined

        if mentions_members and mentions_manage and name in my_permissions:
            return True

    return False


def has_instance_moderation_permission(my_permissions: list, catalog: list) -> bool:
    """
    my_permissions is whatever VRChat's GET /groups/{id} returned in
    myMember.permissions for the logged-in user. Checked in priority
    order: "*" (full access) first, then any catalog entry whose
    description mentions both "instance" and a moderation-flavored word
    (moderate/manage/kick/ban).
    """
    my_permissions = my_permissions or []

    if "*" in my_permissions:
        return True

    for perm in catalog or []:
        name = perm.get("name") or ""
        display = (perm.get("displayName") or "").lower()
        help_text = (perm.get("help") or "").lower()
        combined = f"{display} {help_text}"

        mentions_instance = any(word in combined for word in _INSTANCE_KEYWORDS)
        mentions_moderation = any(word in combined for word in _MODERATION_KEYWORDS)

        if mentions_instance and mentions_moderation and name in my_permissions:
            return True

    return False
