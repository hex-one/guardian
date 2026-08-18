"""
vote_kick_submit.py

Shared logic for handing a locally-observed vote-kick event off to the
rest of the app -- called from main.py right after log_watcher.py hands
back a "vote_kick_initiated" or "vote_kick_succeeded" event, and vote_
kicks.py has already saved the local record.

If Sheets sync is configured, this also submits the event to the shared
VoteKicks tab so the whole team sees it, not just whoever's Guardian
happened to be running. Per spec: if another Guardian already reported
the SAME event first, that's not an error, it's just how "first come,
first served" is supposed to work -- and either way, win or lose the
race, the LOCAL AAR gets an entry. These are just apps talking to each
other; what actually matters is that your own log stays honest.
"""

import aar
import vote_kicks
import watchlist_sync_settings
import sheets_vote_kicks


def submit_vote_kick_event(vrchat_client, event: "vote_kicks.VoteKickEvent") -> str:
    """
    Returns a short human-readable status string (also what gets folded
    into the AAR entry's details). Always logs to the AAR, regardless of
    whether the shared submission succeeded, lost the race to another
    Guardian, or couldn't be reached at all.
    """
    sync_settings = watchlist_sync_settings.load_settings()
    observed_by = vrchat_client.display_name if vrchat_client else "unknown"

    where = f"world {event.world_id}" + (f" (instance {event.instance_id})" if event.instance_id else "")
    detail = f"Vote kick {event.status} against {event.target_display_name} in {where}."

    if not watchlist_sync_settings.is_configured():
        detail += " Local only -- no shared list configured."
        _log(observed_by, event, detail)
        return detail

    result = sheets_vote_kicks.submit_event(
        sync_settings.script_url,
        event_id=event.event_id,
        target_user_id=event.target_user_id,
        target_display_name=event.target_display_name,
        world_id=event.world_id,
        instance_id=event.instance_id,
        status=event.status,
        initiated_at=event.initiated_at,
        succeeded_at=event.succeeded_at,
        submitted_by=observed_by,
    )

    if result.status == "success":
        detail += " Submitted to the shared VoteKicks list."
    elif result.status == "duplicate":
        detail += " Another Guardian already submitted this event."
    else:
        detail += f" Couldn't reach the shared list ({result.error_message}) -- recorded locally only."

    _log(observed_by, event, detail)
    return detail


def _log(observed_by: str, event: "vote_kicks.VoteKickEvent", detail: str):
    aar.save_entry(aar.AAREntry(
        timestamp=aar.now_iso(),
        moderator=observed_by,
        action=f"vote_kick_{event.status}",
        target_display_name=event.target_display_name,
        target_user_id=event.target_user_id or "",
        details=detail,
        success=True,
    ))
