"""
invites_dialog.py

The "Requests" menu -> everyone standing at the door of a group you
watch over, waiting to be let in. Pulls pending GROUP JOIN REQUESTS
(the opposite current from invite_dialog.py's "we reach out to them")
across every group in the cached moderation shortlist (group_mod_
cache.py) you actually hold permission to review, and gathers them
into one room instead of making you check each door separately. More
than one group can have someone waiting at once, so each name in the
list wears the group they're asking after as a small icon out at the
right edge (IconRowDelegate, same trick group_picker_dialog.py already
knows -- QListWidgetItem.setIcon() only ever draws on the left, old
habit of Qt's).

Nothing in here gets cached the way group_mod_cache itself does --
someone waiting to join changes too fast, and saying yes or no to a
person is too real a moment, to ever hand you something stale. Every
time this window opens, and every time you hit Refresh, it goes and
looks again for real.
"""

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QMessageBox,
    QMenu,
    QInputDialog,
    QApplication,
)

import aar
import player_profile
import watchlist
import watchlist_categories
import watchlist_submit
from icon_row_delegate import IconRowDelegate, GROUP_ICON_ROLE, GROUP_ICON_LABELS_ROLE
from profile_dialog import ProfileDialog


class InvitesDialog(QDialog):
    def __init__(self, client, eligible_groups, icon_pixmaps):
        """eligible_groups: whatever group_mod_cache.py's last scan found
        you hold join-request-review permission in -- a shortlist, not
        gospel (see the module's own opening words above, and _refresh()
        below, which checks again for real before trusting any of it).
        icon_pixmaps: {group_id: QPixmap}, the same well main.py already
        draws from for the player list and the Kick/Ban-From picker --
        no reason to fetch a group's face twice."""
        super().__init__()
        self.setObjectName("InvitesDialog")
        self.setWindowTitle("Invites — Pending Join Requests")
        self.resize(420, 480)

        self.client = client
        self.eligible_groups = eligible_groups
        self.icon_pixmaps = icon_pixmaps
        # A person's trust rank, age-verification, and VRC+ standing
        # don't shift mid-session any more than the stripes on your back
        # do -- same reasoning as main.py's _player_profile_cache. Looked
        # up once per requester, kept close, reused every time Refresh
        # gets clicked again.
        self._profile_cache: dict = {}

        self._build_ui()
        self._refresh()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        hint = QLabel(
            "Pending requests to join groups you can review, across every "
            "group in your moderation shortlist. Select one and use "
            "Accept/Reject below, or right-click a row for more (profile, "
            "watchlist)."
        )
        hint.setObjectName("invitesHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.status_label = QLabel("")
        self.status_label.setObjectName("invitesStatus")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.request_list = QListWidget()
        self.request_list.setObjectName("invitesRequestList")
        self.request_list.setToolTip("Pending join requests -- the group each one is for shows as an icon on the right")
        # Held onto as an attribute, not left as a passing local -- PySide
        # will otherwise garbage-collect the Python wrapper right out from
        # under the C++ side the moment __init__ finishes, same lesson
        # group_picker_dialog.py already learned the hard way.
        self._delegate = IconRowDelegate(self.request_list)
        self.request_list.setItemDelegate(self._delegate)
        self.request_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.request_list.customContextMenuRequested.connect(self._open_context_menu)
        layout.addWidget(self.request_list)

        button_row = QHBoxLayout()

        refresh_button = QPushButton("Refresh")
        refresh_button.setObjectName("invitesRefreshButton")
        refresh_button.setToolTip("Re-scan every eligible group for pending requests")
        refresh_button.clicked.connect(self._refresh)
        button_row.addWidget(refresh_button)

        button_row.addStretch()

        reject_button = QPushButton("Reject")
        reject_button.setObjectName("invitesRejectButton")
        reject_button.setToolTip("Reject the selected join request")
        reject_button.clicked.connect(lambda: self._respond(accept=False))
        button_row.addWidget(reject_button)

        accept_button = QPushButton("Accept")
        accept_button.setObjectName("invitesAcceptButton")
        accept_button.setToolTip("Accept the selected join request")
        accept_button.clicked.connect(lambda: self._respond(accept=True))
        button_row.addWidget(accept_button)

        layout.addLayout(button_row)

        close_button = QPushButton("Close")
        close_button.setObjectName("invitesCloseButton")
        close_button.setToolTip("Close this window")
        close_button.clicked.connect(self.accept)
        layout.addWidget(close_button)

    def _refresh(self):
        self.request_list.clear()

        if not self.eligible_groups:
            self.status_label.setText(
                "No groups in your moderation shortlist grant permission to review join requests."
            )
            return

        self.status_label.setText("Checking eligible groups...")
        QApplication.processEvents()

        total_found = 0
        errors = []
        for entry in self.eligible_groups:
            result = self.client.get_group_join_requests(entry.group_id)
            if result.status != "success":
                errors.append(f"{entry.group_name}: {result.error_message}")
                continue

            for req in result.requests:
                profile = self._get_profile(req.user_id)

                label = req.display_name
                if profile and profile.badge_text:
                    label = f"{label}  {profile.badge_text}"

                item = QListWidgetItem(label)
                item.setData(Qt.UserRole, (entry.group_id, entry.group_name, req.user_id, req.display_name))

                tooltip_lines = [f"Requesting to join {entry.group_name}"]
                if profile:
                    item.setForeground(QColor(profile.rank.color))
                    tooltip_lines.append(profile.tooltip)
                item.setToolTip("\n".join(tooltip_lines))

                pixmap = self.icon_pixmaps.get(entry.group_id)
                if pixmap:
                    item.setData(GROUP_ICON_ROLE, pixmap)
                    item.setData(GROUP_ICON_LABELS_ROLE, entry.group_name)
                self.request_list.addItem(item)
                total_found += 1

        if errors:
            self.status_label.setText("Couldn't check: " + "; ".join(errors))
        elif total_found == 0:
            self.status_label.setText("No pending join requests right now.")
        else:
            self.status_label.setText(f"{total_found} pending request(s).")

    def _get_profile(self, user_id: str):
        """Trust rank color plus 18+/VRC+ badges for whoever's asking to
        join -- same well, same signals (GET /users/{id}) the main player
        list already drinks from, see player_profile.py. Kept close for
        the life of this window; a failed lookup just leaves a row with
        no color and no badges rather than crashing the whole thing,
        same grace-under-a-bad-connection main.py's
        _ensure_trust_rank_cached already practices."""
        if user_id in self._profile_cache:
            return self._profile_cache[user_id]

        result = self.client.get_user(user_id)
        profile = player_profile.build_profile(result) if result.status == "success" else None
        self._profile_cache[user_id] = profile
        return profile

    def _open_context_menu(self, position):
        item = self.request_list.itemAt(position)
        if item is None:
            return
        self.request_list.setCurrentItem(item)
        _group_id, _group_name, target_user_id, target_display_name = item.data(Qt.UserRole)

        menu = QMenu(self)
        menu.setToolTipsVisible(True)

        profile_action = menu.addAction(
            "View Profile", lambda: self._view_profile(target_user_id, target_display_name)
        )
        profile_action.setToolTip("Show this player's rank, badges, and notes")

        web_profile_action = menu.addAction(
            "Open Web Profile ↗",
            lambda: QDesktopServices.openUrl(QUrl(f"https://vrchat.com/home/user/{target_user_id}")),
        )
        web_profile_action.setToolTip("Open this player's profile on the VRChat website")

        menu.addSeparator()

        accept_action = menu.addAction("Accept", lambda: self._respond(accept=True))
        accept_action.setToolTip("Accept this join request")

        reject_action = menu.addAction("Reject", lambda: self._respond(accept=False))
        reject_action.setToolTip("Reject this join request")

        menu.addSeparator()

        watchlist_label = "Remove from WatchList" if target_user_id in watchlist.get_watched_ids() else "Add to WatchList"
        watchlist_action = menu.addAction(
            watchlist_label, lambda: self._toggle_watchlist(target_user_id, target_display_name)
        )
        watchlist_action.setToolTip("Toggle this player's watchlist membership")

        menu.exec(self.request_list.viewport().mapToGlobal(position))

    def _view_profile(self, user_id: str, display_name: str):
        dialog = ProfileDialog(self.client, user_id, display_name)
        dialog.exec()

    def _toggle_watchlist(self, user_id: str, display_name: str):
        if user_id in watchlist.get_watched_ids():
            watchlist.remove_entries([user_id])
            aar.save_entry(aar.AAREntry(
                timestamp=aar.now_iso(),
                moderator=self.client.display_name or "unknown",
                action="watchlist_remove",
                target_display_name=display_name,
                target_user_id=user_id,
                details="Removed from watchlist",
                success=True,
            ))
            return

        category_labels = [watchlist_categories.CATEGORIES[k].label for k in watchlist_categories.CATEGORY_ORDER]
        chosen_label, ok = QInputDialog.getItem(
            self, "Add to Watchlist", f"Category for {display_name}:", category_labels, 0, False
        )
        if not ok:
            return
        category_key = next(k for k in watchlist_categories.CATEGORY_ORDER
                             if watchlist_categories.CATEGORIES[k].label == chosen_label)

        reason, ok = QInputDialog.getText(
            self, "Add to Watchlist", f"Reason for watching {display_name} (optional):"
        )
        if not ok:
            return

        status = watchlist_submit.submit_watchlist_entry(
            self, self.client, user_id, display_name, reason.strip(), category_key
        )
        QMessageBox.information(self, "Watchlist", status)

    def _respond(self, accept: bool):
        item = self.request_list.currentItem()
        if item is None:
            return
        group_id, group_name, target_user_id, target_display_name = item.data(Qt.UserRole)

        verb = "Accept" if accept else "Reject"
        confirm = QMessageBox.question(
            self, f"{verb} join request",
            f"{verb} {target_display_name}'s request to join {group_name}?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return

        result = self.client.respond_to_group_join_request(group_id, target_user_id, accept)

        aar.save_entry(aar.AAREntry(
            timestamp=aar.now_iso(),
            moderator=self.client.display_name or "unknown",
            action="join_request_accept" if accept else "join_request_reject",
            target_display_name=target_display_name,
            target_user_id=target_user_id,
            details=f"{'Accepted' if accept else 'Rejected'} join request for {group_name}",
            success=(result.status == "success"),
            error_message=result.error_message,
        ))

        if result.status == "success":
            self.request_list.takeItem(self.request_list.row(item))
            self.status_label.setText(f"{'Accepted' if accept else 'Rejected'} {target_display_name}.")
        else:
            QMessageBox.warning(self, "Failed", f"Couldn't respond: {result.error_message}")
