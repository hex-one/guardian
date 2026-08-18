"""
watchlist_dialog.py

The Watchlist window: view/remove watchlisted players (multi-select),
add one manually, import/export the list as a JSON file, post it to a
configured Discord channel as an attachment, and (if Google Sheets sync
is configured in Config) pull the shared approved list and submit new
candidates to it for review, plus a Review Queue for approvers. The
whole team's memory, in one window.

Also holds the "VoteKicks" tab -- a separate room in the same house,
same idea as Watchlist itself (local record + optional shared sync),
just for vote-kick events instead of watched players. See vote_kicks.py,
vote_kick_submit.py, and sheets_vote_kicks.py for the half of this that
lives outside the UI.
"""

import json
from dataclasses import asdict

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QAbstractItemView,
    QPushButton,
    QLineEdit,
    QComboBox,
    QMessageBox,
    QFileDialog,
    QInputDialog,
    QApplication,
    QFrame,
    QTabWidget,
    QWidget,
)

import aar
import watchlist
import watchlist_categories
import watchlist_submit
from import_review_dialog import ImportReviewDialog
import discord_targets
import discord_api
import watchlist_sync_settings
import sheets_watchlist
import vote_kicks
import sheets_vote_kicks
from glow import apply_glow, PRIMARY, DANGER, SUCCESS, WARNING, INFO, DISCORD


class WatchlistDialog(QDialog):
    def __init__(self, vrchat_client=None):
        super().__init__()
        self.setObjectName("WatchlistDialog")
        self.setWindowTitle("Watchlist")
        self.resize(460, 640)

        # Needed for "who submitted/reviewed this" -- optional only so this
        # dialog can still be constructed/tested without a live session;
        # main.py always passes the real client.
        self.vrchat_client = vrchat_client

        self._build_ui()
        self._reload()
        self._reload_review_queue()
        self._reload_vote_kicks()

    def _hline(self) -> QFrame:
        f = QFrame()
        f.setFrameShape(QFrame.HLine)
        return f

    def _build_ui(self):
        window_layout = QVBoxLayout(self)
        tabs = QTabWidget()
        tabs.setObjectName("watchlistTabs")
        window_layout.addWidget(tabs)

        watchlist_page = QWidget()
        outer = QVBoxLayout(watchlist_page)
        tabs.addTab(watchlist_page, "Watchlist")

        votekicks_page = QWidget()
        tabs.addTab(votekicks_page, "VoteKicks")
        self._build_vote_kicks_tab(votekicks_page)

        header = QLabel(
            "Players flagged for extra attention. If one shows up in an instance, "
            "their name blinks with a caution icon in the player list."
        )
        header.setObjectName("watchlistHeader")
        header.setWordWrap(True)
        outer.addWidget(header)

        self.entry_list = QListWidget()
        self.entry_list.setObjectName("watchlistEntryList")
        self.entry_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        outer.addWidget(self.entry_list)

        remove_row = QHBoxLayout()
        remove_row.addStretch()
        self.remove_button = QPushButton("Remove Selected")
        self.remove_button.setObjectName("watchlistRemoveButton")
        self.remove_button.setToolTip("Remove the selected watchlist entries")
        apply_glow(self.remove_button, DANGER)
        self.remove_button.clicked.connect(self._remove_selected)
        remove_row.addWidget(self.remove_button)
        outer.addLayout(remove_row)

        outer.addWidget(self._hline())

        add_label = QLabel("Add a player manually")
        add_label.setObjectName("watchlistAddLabel")
        outer.addWidget(add_label)

        add_row = QHBoxLayout()
        self.user_id_input = QLineEdit()
        self.user_id_input.setObjectName("watchlistUserIdInput")
        self.user_id_input.setPlaceholderText("User ID (usr_...)")
        self.user_id_input.setToolTip("The player's VRChat user ID")
        add_row.addWidget(self.user_id_input)

        self.display_name_input = QLineEdit()
        self.display_name_input.setObjectName("watchlistDisplayNameInput")
        self.display_name_input.setPlaceholderText("Display name")
        self.display_name_input.setToolTip("The player's display name")
        add_row.addWidget(self.display_name_input)
        outer.addLayout(add_row)

        self.reason_input = QLineEdit()
        self.reason_input.setObjectName("watchlistReasonInput")
        self.reason_input.setPlaceholderText("Reason (optional)")
        self.reason_input.setToolTip("Why this player is being watched")
        outer.addWidget(self.reason_input)

        category_row = QHBoxLayout()
        category_row.addWidget(QLabel("Category:"))
        self.category_combo = QComboBox()
        self.category_combo.setObjectName("watchlistCategoryCombo")
        self.category_combo.setToolTip("Watchlist category for this entry")
        for key in watchlist_categories.CATEGORY_ORDER:
            cat = watchlist_categories.CATEGORIES[key]
            self.category_combo.addItem(f"{cat.icon} {cat.label}", key)
        category_row.addWidget(self.category_combo)
        category_row.addStretch()
        outer.addLayout(category_row)

        self.status_label = QLabel("")
        self.status_label.setObjectName("watchlistStatus")
        self.status_label.setWordWrap(True)
        outer.addWidget(self.status_label)

        add_button_row = QHBoxLayout()
        add_button_row.addStretch()
        self.add_button = QPushButton("Add to Watchlist")
        self.add_button.setObjectName("watchlistAddButton")
        self.add_button.setToolTip("Add this player to the watchlist")
        apply_glow(self.add_button, PRIMARY)
        self.add_button.clicked.connect(self._add_manual)
        add_button_row.addWidget(self.add_button)
        outer.addLayout(add_button_row)

        outer.addWidget(self._hline())

        bottom_row = QHBoxLayout()

        self.import_button = QPushButton("Import...")
        self.import_button.setObjectName("watchlistImportButton")
        self.import_button.setToolTip("Import watchlist entries from a JSON file for review")
        apply_glow(self.import_button, PRIMARY)
        self.import_button.clicked.connect(self._import)
        bottom_row.addWidget(self.import_button)

        self.export_button = QPushButton("Export...")
        self.export_button.setObjectName("watchlistExportButton")
        self.export_button.setToolTip("Export the current watchlist to a JSON file")
        self.export_button.clicked.connect(self._export)
        bottom_row.addWidget(self.export_button)

        self.discord_button = QPushButton("Post to Discord")
        self.discord_button.setObjectName("watchlistDiscordButton")
        self.discord_button.setToolTip("Post the watchlist as a JSON file to a configured Discord webhook")
        apply_glow(self.discord_button, DISCORD)
        self.discord_button.clicked.connect(self._post_to_discord)
        bottom_row.addWidget(self.discord_button)

        self.sync_now_button = QPushButton("Sync Now")
        self.sync_now_button.setObjectName("watchlistSyncNowButton")
        self.sync_now_button.setToolTip("Manually pull and merge the shared Google Sheets watchlist")
        apply_glow(self.sync_now_button, INFO)
        self.sync_now_button.clicked.connect(self._sync_now)
        bottom_row.addWidget(self.sync_now_button)

        bottom_row.addStretch()

        close_button = QPushButton("Close")
        close_button.setObjectName("watchlistCloseButton")
        close_button.setToolTip("Close this window")
        close_button.clicked.connect(self.accept)
        bottom_row.addWidget(close_button)

        outer.addLayout(bottom_row)

        outer.addWidget(self._hline())

        # -- Review Queue (only useful if you're on the approver allowlist
        # baked into the Apps Script -- anyone else's review attempts get
        # rejected server-side, with the error shown here) --------------

        review_label = QLabel("Review Queue \u2014 pending submissions and removal requests from the shared list")
        review_label.setObjectName("watchlistReviewLabel")
        review_label.setStyleSheet("font-weight: bold;")
        outer.addWidget(review_label)

        self.review_list = QListWidget()
        self.review_list.setObjectName("watchlistReviewList")
        self.review_list.setToolTip("Pending submissions and removal requests from the shared list")
        self.review_list.currentItemChanged.connect(self._on_review_selection_changed)
        outer.addWidget(self.review_list)

        review_button_row = QHBoxLayout()

        # Approve: for a new submission, means "add to the live list"; for
        # a removal request, means "deny the removal, keep them listed" --
        # both are the same underlying action (new_status="approved"), so
        # no special-casing needed for this one specifically.
        self.approve_button = QPushButton("Approve")
        self.approve_button.setObjectName("watchlistApproveButton")
        self.approve_button.setToolTip("Add this submission to the live list, or deny the selected removal request")
        apply_glow(self.approve_button, SUCCESS)
        self.approve_button.clicked.connect(lambda: self._review_selected("approved"))
        review_button_row.addWidget(self.approve_button)

        # Reject only makes sense for a brand-new submission ("this
        # shouldn't be on the list at all") -- disabled for removal
        # requests via _on_review_selection_changed below, since there's
        # no sensible "reject the removal request" outcome distinct from
        # just clicking Approve (deny it, keep them listed).
        self.reject_button = QPushButton("Reject")
        self.reject_button.setObjectName("watchlistRejectButton")
        self.reject_button.setToolTip("Reject this new submission (not available for removal requests)")
        apply_glow(self.reject_button, WARNING)
        self.reject_button.clicked.connect(lambda: self._review_selected("rejected"))
        review_button_row.addWidget(self.reject_button)

        # This button's actual target status depends on what's selected --
        # "cleared" for a new submission, "removed" (confirms the removal)
        # for a removal request -- see _on_review_selection_changed, which
        # also relabels it so the meaning is never ambiguous on screen.
        self.clear_button = QPushButton("Mark Not a Threat (Clear)")
        self.clear_button.setObjectName("watchlistClearButton")
        self.clear_button.setToolTip("Clear a submission as not a threat, or confirm a pending removal")
        apply_glow(self.clear_button, WARNING)
        self.clear_button.clicked.connect(self._on_clear_or_confirm_removal)
        review_button_row.addWidget(self.clear_button)

        outer.addLayout(review_button_row)

    # -- List -------------------------------------------------------------

    def _reload(self):
        self.entry_list.clear()
        for entry in watchlist.load_entries():
            category = watchlist_categories.get_category(entry.category)
            label = f"{category.icon} {entry.display_name} ({entry.user_id}) \u2014 {category.label}"
            if entry.reason:
                label += f": {entry.reason}"
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, entry)
            self.entry_list.addItem(item)

    def _remove_selected(self):
        selected = self.entry_list.selectedItems()
        if not selected:
            self.status_label.setText("Select at least one to remove.")
            return

        entries = [item.data(Qt.UserRole) for item in selected]
        names = ", ".join(e.display_name for e in entries)

        sync_settings = watchlist_sync_settings.load_settings()

        if not watchlist_sync_settings.is_configured():
            # No shared list -- purely local, same as before sync existed.
            confirm = QMessageBox.question(
                self, "Remove from Watchlist",
                f"Remove {len(entries)} player(s) from the watchlist?\n\n{names}",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if confirm != QMessageBox.Yes:
                return
            watchlist.remove_entries([e.user_id for e in entries])
            for entry in entries:
                aar.save_entry(aar.AAREntry(
                    timestamp=aar.now_iso(),
                    moderator=self.vrchat_client.display_name if self.vrchat_client else "unknown",
                    action="watchlist_remove",
                    target_display_name=entry.display_name,
                    target_user_id=entry.user_id,
                    details=f"Removed from watchlist (category: {entry.category})",
                    success=True,
                ))
            self._reload()
            self.status_label.setText(f"Removed {len(entries)}.")
            return

        # Removal is a moderation decision just like adding one -- it needs
        # to go through the same approval gate, not just vanish locally
        # only to reappear on the next sync. One fresh pull covers
        # checking the whole selection, same batching pattern as Import.
        self.status_label.setText("Checking the shared list first...")
        self.remove_button.setEnabled(False)
        QApplication.processEvents()

        check = sheets_watchlist.fetch_all(sync_settings.csv_url)
        self.remove_button.setEnabled(True)

        if check.status != "success":
            self.status_label.setText(f"Couldn't reach the shared list ({check.error_message}).")
            return

        existing_by_id = {e.user_id: e for e in check.entries}
        to_request, to_remove_locally, already_in_review = [], [], []

        for entry in entries:
            sheet_entry = existing_by_id.get(entry.user_id)
            if sheet_entry is None:
                # Never actually made it to the shared list -- nothing to
                # request removal of, just drop the local copy.
                to_remove_locally.append(entry)
            elif sheet_entry.status == "approved":
                to_request.append(entry)
            elif sheet_entry.status == "pending_removal":
                already_in_review.append(entry)
            else:
                # cleared/rejected/pending -- not currently live either
                # way, nothing meaningful to request removal of.
                to_remove_locally.append(entry)

        confirm_names = ", ".join(e.display_name for e in to_request)
        proceed = True
        if to_request:
            proceed = QMessageBox.question(
                self, "Request Removal",
                f"Submit a removal request for {len(to_request)} player(s)? They'll stay on the "
                f"watchlist until an approver confirms it:\n\n{confirm_names}",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            ) == QMessageBox.Yes

        requested_by = self.vrchat_client.user_id if self.vrchat_client else "unknown"
        requested, failed = 0, 0

        if proceed:
            for entry in to_request:
                result = sheets_watchlist.request_removal(sync_settings.script_url, entry.user_id, requested_by)
                if result.status == "success":
                    requested += 1
                    aar.save_entry(aar.AAREntry(
                        timestamp=aar.now_iso(),
                        moderator=self.vrchat_client.display_name if self.vrchat_client else "unknown",
                        action="watchlist_removal_request",
                        target_display_name=entry.display_name,
                        target_user_id=entry.user_id,
                        details=f"Requested removal from shared watchlist (category: {entry.category})",
                        success=True,
                    ))
                    # Deliberately NOT removed locally here -- a removal
                    # request doesn't take effect until an approver
                    # confirms it (same principle as a new submission not
                    # being live until it's approved). They keep blinking
                    # until that happens; the next sync will drop them
                    # once the sheet actually shows "removed".
                else:
                    failed += 1

        if to_remove_locally:
            watchlist.remove_entries([e.user_id for e in to_remove_locally])
            for entry in to_remove_locally:
                aar.save_entry(aar.AAREntry(
                    timestamp=aar.now_iso(),
                    moderator=self.vrchat_client.display_name if self.vrchat_client else "unknown",
                    action="watchlist_remove",
                    target_display_name=entry.display_name,
                    target_user_id=entry.user_id,
                    details=f"Removed from watchlist (category: {entry.category})",
                    success=True,
                ))

        self._reload()
        self._reload_review_queue()

        parts = []
        if requested:
            parts.append(f"{requested} submitted for removal review")
        if to_remove_locally:
            parts.append(f"{len(to_remove_locally)} removed locally (never reached the shared list)")
        if already_in_review:
            parts.append(f"{len(already_in_review)} already have a pending removal request")
        if failed:
            parts.append(f"{failed} failed")
        self.status_label.setText(", ".join(parts) + "." if parts else "Nothing to remove.")

    # -- Manual add -------------------------------------------------------

    def _add_manual(self):
        user_id = self.user_id_input.text().strip()
        display_name = self.display_name_input.text().strip()
        reason = self.reason_input.text().strip()
        category = self.category_combo.currentData()

        if not user_id or not display_name:
            self.status_label.setText("Both a User ID and a display name are required.")
            return
        if not user_id.startswith("usr_"):
            self.status_label.setText("That doesn't look like a VRChat user ID (should start with usr_).")
            return

        self.status_label.setText("Checking the shared list for a fresh copy first...")
        self.add_button.setEnabled(False)
        QApplication.processEvents()

        # Routes through the shared submission logic -- same fresh
        # duplicate/cleared check and submission behavior as the
        # right-click menu and Note dialog use.
        status = watchlist_submit.submit_watchlist_entry(
            self, self.vrchat_client, user_id, display_name, reason, category
        )
        self.add_button.setEnabled(True)
        self.status_label.setText(status)

        if status.startswith("Submitted") or status.startswith("Added"):
            self._reload()
            self._clear_add_fields()

    def _clear_add_fields(self):
        self.user_id_input.clear()
        self.display_name_input.clear()
        self.reason_input.clear()
        self.category_combo.setCurrentIndex(0)

    # -- Sync ---------------------------------------------------------------

    def _sync_now(self):
        sync_settings = watchlist_sync_settings.load_settings()
        if not watchlist_sync_settings.is_configured():
            QMessageBox.information(
                self, "Sync not configured",
                "Set the Sheet CSV URL and Apps Script Web App URL in Config first "
                "(account menu \u2192 your username \u2192 Config \u2192 Watchlist Sync).",
            )
            return

        self.sync_now_button.setEnabled(False)
        self.status_label.setText("Syncing from the shared list...")
        QApplication.processEvents()

        result = sheets_watchlist.fetch_all(sync_settings.csv_url)
        self.sync_now_button.setEnabled(True)

        if result.status != "success":
            self.status_label.setText(f"Sync failed: {result.error_message}")
            return

        active_statuses = ("approved", "pending_removal")
        inactive_statuses = ("cleared", "rejected", "removed")

        added = 0
        for sheet_entry in result.entries:
            if sheet_entry.status not in active_statuses:
                continue
            before = watchlist.get_watched_ids()
            watchlist.upsert_entry(watchlist.WatchlistEntry(
                user_id=sheet_entry.user_id,
                display_name=sheet_entry.display_name,
                reason=sheet_entry.reason,
                added_at=sheet_entry.submitted_at or aar.now_iso(),
                category=sheet_entry.category,
            ))
            if sheet_entry.user_id not in before:
                added += 1

        # Prune local entries the sheet says are no longer active (cleared/
        # rejected/removed) -- this is what makes a confirmed removal (or
        # any other status change away from "active") actually stick
        # locally, instead of a stale local copy lingering forever. Entries
        # the sheet doesn't mention at all (never synced -- e.g. purely
        # local-only, sync configured after the fact) are left untouched.
        inactive_ids = {e.user_id for e in result.entries if e.status in inactive_statuses}
        to_prune = [uid for uid in watchlist.get_watched_ids() if uid in inactive_ids]
        if to_prune:
            watchlist.remove_entries(to_prune)

        self._reload()
        self._reload_review_queue()
        pruned_note = f", {len(to_prune)} pruned (no longer active)" if to_prune else ""
        self.status_label.setText(
            f"Synced \u2014 {added} new entr{'y' if added == 1 else 'ies'} from the shared list{pruned_note}."
        )

    # -- Review Queue ------------------------------------------------------

    def _reload_review_queue(self):
        self.review_list.clear()
        sync_settings = watchlist_sync_settings.load_settings()
        if not watchlist_sync_settings.is_configured():
            return

        result = sheets_watchlist.fetch_all(sync_settings.csv_url)
        if result.status != "success":
            # Previously silently returned here -- surfaced now, since an
            # empty-looking queue with no explanation is indistinguishable
            # from "genuinely nothing pending" otherwise.
            self.status_label.setText(f"Couldn't load Review Queue: {result.error_message}")
            return

        for entry in result.entries:
            if entry.status == "pending":
                label = f"{entry.display_name} ({entry.user_id}) \u2014 {entry.reason} [submitted by {entry.submitted_by}]"
            elif entry.status == "pending_removal":
                label = f"\U0001F5D1 REMOVAL REQUEST: {entry.display_name} ({entry.user_id}) \u2014 {entry.reason}"
            else:
                continue
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, entry)
            self.review_list.addItem(item)

    def _on_review_selection_changed(self, current, previous):
        if current is None:
            return
        entry = current.data(Qt.UserRole)
        is_removal = entry.status == "pending_removal"
        self.reject_button.setEnabled(not is_removal)
        self.clear_button.setText("Confirm Removal" if is_removal else "Mark Not a Threat (Clear)")

    def _on_clear_or_confirm_removal(self):
        item = self.review_list.currentItem()
        if item is None:
            self.status_label.setText("Select an entry from the Review Queue first.")
            return
        entry = item.data(Qt.UserRole)
        target_status = "removed" if entry.status == "pending_removal" else "cleared"
        self._review_selected(target_status)

    def _review_selected(self, new_status: str):
        item = self.review_list.currentItem()
        if item is None:
            self.status_label.setText("Select a pending entry from the Review Queue first.")
            return

        entry = item.data(Qt.UserRole)
        sync_settings = watchlist_sync_settings.load_settings()
        reviewer_id = self.vrchat_client.user_id if self.vrchat_client else "unknown"

        confirm = QMessageBox.question(
            self, f"Confirm: {new_status.capitalize()}",
            f"Mark {entry.display_name} as \"{new_status}\"?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return

        result = sheets_watchlist.review_entry(sync_settings.script_url, entry.user_id, new_status, reviewer_id)

        if result.status == "success":
            # Was NOT logged before this -- approving/rejecting/clearing/
            # confirming a removal is as real a moderation decision as
            # submitting the entry in the first place (arguably more so:
            # this is what actually puts someone on the shared list, or
            # takes them off it), so it belongs in the AAR the same way.
            aar.save_entry(aar.AAREntry(
                timestamp=aar.now_iso(),
                moderator=self.vrchat_client.display_name if self.vrchat_client else "unknown",
                action=f"watchlist_{new_status}",
                target_display_name=entry.display_name,
                target_user_id=entry.user_id,
                details=f"Marked {new_status} on shared watchlist review "
                        f"(category: {entry.category}, reason: {entry.reason})",
                success=True,
            ))
            self.status_label.setText(f"Marked {entry.display_name} as {new_status}.")
            self._reload_review_queue()
            if new_status == "approved":
                self._sync_now()  # pick up the newly-approved entry immediately
        else:
            self.status_label.setText(f"Review failed: {result.error_message}")

    # -- Import / export ---------------------------------------------------

    def _import(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import Watchlist", "", "JSON (*.json)")
        if not path:
            return

        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = json.loads(f.read())
            imported = [watchlist.WatchlistEntry(**item) for item in raw]
        except Exception as e:
            self.status_label.setText(f"Import failed: {e}")
            return

        if not imported:
            self.status_label.setText("That file didn't contain any entries.")
            return

        # Imported entries are treated as new submission candidates, not
        # trusted as-is -- the review window checks every one against a
        # fresh copy of the shared list (same rule a normal single Add
        # follows) and lets each field be edited before anything is sent.
        dialog = ImportReviewDialog(self.vrchat_client, imported)
        dialog.exec()
        self._reload()
        self._reload_review_queue()

    def _export(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export Watchlist", "watchlist.json", "JSON (*.json)")
        if not path:
            return

        data = [asdict(e) for e in watchlist.load_entries()]
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        self.status_label.setText(f"Exported to {path}.")

    # -- Discord -----------------------------------------------------------

    def _post_to_discord(self):
        targets = discord_targets.load_targets()

        if not targets:
            QMessageBox.information(
                self, "No Discord targets configured",
                "Add a Discord webhook target first: click your username (top-right) "
                "\u2192 Config \u2192 Discord Integration.",
            )
            return

        if len(targets) == 1:
            target = targets[0]
        else:
            names = [t.name for t in targets]
            chosen_name, ok = QInputDialog.getItem(
                self, "Post to Discord", "Send the watchlist to:", names, 0, False
            )
            if not ok:
                return
            target = next(t for t in targets if t.name == chosen_name)

        data = json.dumps([asdict(e) for e in watchlist.load_entries()], indent=2).encode("utf-8")

        self.discord_button.setEnabled(False)
        self.status_label.setText("Uploading...")
        QApplication.processEvents()
        result = discord_api.send_file(target.webhook_url, "watchlist.json", data,
                                        content="Guardian Watchlist attached.")
        self.discord_button.setEnabled(True)

        if result.status == "success":
            self.status_label.setText(f'Posted to "{target.name}".')
        else:
            self.status_label.setText(f"Failed to post: {result.error_message}")

    # -- VoteKicks tab -------------------------------------------------------

    def _build_vote_kicks_tab(self, page: QWidget):
        layout = QVBoxLayout(page)

        header = QLabel(
            "Vote-kicks Guardian has personally observed in the log -- who was targeted, "
            "where, and whether the vote succeeded. There's no \"who started it\" column: "
            "VRChat's own log never exposes that to any client, so it isn't something this "
            "list can show you either."
        )
        header.setObjectName("voteKicksHeader")
        header.setWordWrap(True)
        layout.addWidget(header)

        self.vote_kicks_list = QListWidget()
        self.vote_kicks_list.setObjectName("voteKicksList")
        layout.addWidget(self.vote_kicks_list)

        self.vote_kicks_status_label = QLabel("")
        self.vote_kicks_status_label.setObjectName("voteKicksStatus")
        self.vote_kicks_status_label.setWordWrap(True)
        layout.addWidget(self.vote_kicks_status_label)

        button_row = QHBoxLayout()
        button_row.addStretch()

        self.vote_kicks_sync_button = QPushButton("Sync Now")
        self.vote_kicks_sync_button.setObjectName("voteKicksSyncButton")
        self.vote_kicks_sync_button.setToolTip("Pull the shared VoteKicks list and merge it in below the local events")
        apply_glow(self.vote_kicks_sync_button, INFO)
        self.vote_kicks_sync_button.clicked.connect(self._sync_vote_kicks)
        button_row.addWidget(self.vote_kicks_sync_button)

        layout.addLayout(button_row)

    def _format_vote_kick_row(self, target_display_name: str, status: str, initiated_at: str,
                               succeeded_at: str, world_id: str, instance_id: str, source: str) -> str:
        where = f"world {world_id}" + (f" (instance {instance_id})" if instance_id else "") if world_id else "unknown instance"
        if status == "succeeded":
            when = succeeded_at or initiated_at
            outcome = "✅ Succeeded"
        else:
            when = initiated_at
            outcome = "⏳ Initiated"
        return f"{outcome} — {target_display_name} — {when} — {where} [{source}]"

    def _reload_vote_kicks(self):
        self.vote_kicks_list.clear()
        events = vote_kicks.load_events()
        if not events:
            self.vote_kicks_status_label.setText("No locally-observed vote-kick events yet.")
            return
        for event in sorted(events, key=lambda e: e.initiated_at or e.succeeded_at, reverse=True):
            label = self._format_vote_kick_row(
                event.target_display_name, event.status, event.initiated_at, event.succeeded_at,
                event.world_id, event.instance_id, "local",
            )
            self.vote_kicks_list.addItem(QListWidgetItem(label))
        self.vote_kicks_status_label.setText(f"{len(events)} locally-observed event(s).")

    def _sync_vote_kicks(self):
        sync_settings = watchlist_sync_settings.load_settings()
        if not watchlist_sync_settings.is_configured():
            QMessageBox.information(
                self, "Sync not configured",
                "Set the Sheet CSV URL and Apps Script Web App URL in Config first "
                "(account menu → your username → Config → Watchlist Sync). "
                "VoteKicks rides on the same two URLs as the Watchlist -- just add a "
                "\"VoteKicks\" tab to the same spreadsheet. See SETUP.md.",
            )
            return

        self.vote_kicks_sync_button.setEnabled(False)
        self.vote_kicks_status_label.setText("Pulling the shared VoteKicks list...")
        QApplication.processEvents()

        result = sheets_vote_kicks.fetch_events(sync_settings.csv_url)
        self.vote_kicks_sync_button.setEnabled(True)

        if result.status != "success":
            self.vote_kicks_status_label.setText(f"Sync failed: {result.error_message}")
            return

        self._reload_vote_kicks()
        local_ids = {e.event_id for e in vote_kicks.load_events()}
        shared_only = [e for e in result.entries if e.event_id not in local_ids]
        for e in shared_only:
            label = self._format_vote_kick_row(
                e.target_display_name, e.status, e.initiated_at, e.succeeded_at,
                e.world_id, e.instance_id, f"shared, reported by {e.submitted_by}",
            )
            self.vote_kicks_list.addItem(QListWidgetItem(label))

        total = len(vote_kicks.load_events()) + len(shared_only)
        self.vote_kicks_status_label.setText(
            f"{len(vote_kicks.load_events())} local event(s), {len(shared_only)} more from the shared "
            f"list not seen locally — {total} shown."
        )
