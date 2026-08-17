"""
watchlist_submit.py

Shared logic for adding a player to the watchlist -- used by the
right-click menu, the Note dialog's WatchList button, and the Watchlist
window's manual-add form, so all three behave IDENTICALLY: if Google
Sheets sync is configured, this actually submits the entry to the shared
list (after a fresh duplicate/cleared check against the live sheet);
otherwise it just adds locally, same as before sync existed.

Before this existed, only the Watchlist window's form went through the
real submission flow -- the right-click and Note dialog paths only ever
called a purely local add, with no connection to the shared sheet at
all, regardless of whether sync was configured. That's the bug this
file fixes: three separate places doing three different things for what
should be one consistent action. One truth, however you arrive at it.
"""

from PySide6.QtWidgets import QMessageBox, QApplication

import aar
import watchlist
import watchlist_sync_settings
import sheets_watchlist


def _log_watchlist_add(vrchat_client, user_id: str, display_name: str, category: str, details: str):
    """Every real "added to the watchlist" outcome below funnels through
    here -- one place to log, even though this function has three
    callers of its own (right-click menu, Note dialog, Watchlist
    window's manual-add form) and three different ways an add can
    actually succeed. See aar.ACTION_CATEGORIES["watchlist"]."""
    aar.save_entry(aar.AAREntry(
        timestamp=aar.now_iso(),
        moderator=vrchat_client.display_name if vrchat_client else "unknown",
        action="watchlist_add",
        target_display_name=display_name,
        target_user_id=user_id,
        details=f"{details} (category: {category})",
        success=True,
    ))


def submit_watchlist_entry(parent, vrchat_client, user_id: str, display_name: str,
                            reason: str, category: str) -> str:
    """
    Returns a short status string meant to be shown directly to the user
    (a status label, or a message box -- caller's choice). May show its
    own confirmation dialog (the "previously cleared" soft warning),
    parented to `parent`.
    """
    sync_settings = watchlist_sync_settings.load_settings()

    if not watchlist_sync_settings.is_configured():
        watchlist.add_entry(watchlist.WatchlistEntry(
            user_id=user_id, display_name=display_name, reason=reason,
            added_at=aar.now_iso(), category=category,
        ))
        _log_watchlist_add(vrchat_client, user_id, display_name, category,
                            f"Added to watchlist (local only \u2014 no shared list configured): {reason}")
        return f"Added {display_name} (local only \u2014 no shared list configured)."

    submitted_by = vrchat_client.user_id if vrchat_client else "unknown"

    # A FRESH pull (not the local cache) right before submitting -- catches
    # someone else's very recent submission or a prior review that a
    # stale local copy could easily miss.
    check = sheets_watchlist.fetch_all(sync_settings.csv_url)

    if check.status != "success":
        watchlist.add_entry(watchlist.WatchlistEntry(
            user_id=user_id, display_name=display_name, reason=reason,
            added_at=aar.now_iso(), category=category,
        ))
        _log_watchlist_add(vrchat_client, user_id, display_name, category,
                            f"Added to watchlist (couldn't reach shared list, local only): {reason}")
        return f"Couldn't reach the shared list ({check.error_message}) \u2014 added locally only for now."

    existing = next((e for e in check.entries if e.user_id == user_id), None)
    confirm_resubmit = False

    if existing and existing.status in ("pending", "approved"):
        return f"Already on the shared list (status: {existing.status})."

    if existing and existing.status == "rejected":
        return ("This player was previously reviewed and rejected. Contact an approver if "
                "you believe this should be revisited.")

    if existing and existing.status == "cleared":
        proceed = QMessageBox.question(
            parent, "Previously Cleared",
            f"{display_name} was previously reviewed and cleared"
            + (f" on {existing.reviewed_at}" if existing.reviewed_at else "")
            + (f" by {existing.reviewed_by}" if existing.reviewed_by else "")
            + ".\n\nSubmit anyway?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if proceed != QMessageBox.Yes:
            return "Not submitted."
        confirm_resubmit = True

    QApplication.processEvents()
    result = sheets_watchlist.submit_entry(
        sync_settings.script_url, user_id, display_name, reason, submitted_by,
        category=category, confirm_resubmit=confirm_resubmit,
    )

    if result.status == "success":
        _log_watchlist_add(vrchat_client, user_id, display_name, category,
                            f"Submitted to shared watchlist for review: {reason}")
        return f"Submitted {display_name} for review."
    return f"Submission failed: {result.error_message}"
