"""
unban_dialog.py

Reports-adjacent "UN-Bans" menu -> lists every temp ban still waiting to
auto-expire (see temp_bans.py), how many days remain, and lets you select
one or more to unban right now instead of waiting. Second chances,
tracked properly.
"""

from datetime import datetime, timezone

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
    QMessageBox,
    QApplication,
)

import aar
import temp_bans
from glow import apply_glow, SUCCESS


def _format_remaining(expires: datetime, now: datetime) -> str:
    """Days while there's at least one full day left, then hours, then
    minutes -- "1.3d remaining" stops being useful information once a
    ban's actually about to expire, and mods watching this list in the
    final stretch want a unit that actually moves."""
    seconds = max((expires - now).total_seconds(), 0)
    days = seconds / 86400
    if days >= 1:
        return f"{days:.1f}d remaining"
    hours = seconds / 3600
    if hours >= 1:
        return f"{hours:.1f}h remaining"
    minutes = seconds / 60
    if minutes < 1:
        return "<1m remaining"
    return f"{minutes:.0f}m remaining"


class UnbansDialog(QDialog):
    def __init__(self, client):
        super().__init__()
        self.setObjectName("UnbansDialog")
        self.setWindowTitle("UN-Bans — Pending Temporary Bans")
        self.resize(460, 420)

        self.client = client

        self._build_ui()
        self._reload()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        header = QLabel(
            "Everyone currently serving a temp ban placed from this app. "
            "Select one or more and unban them early, or just let them expire on their own."
        )
        header.setObjectName("unbansHeader")
        header.setWordWrap(True)
        layout.addWidget(header)

        self.ban_list = QListWidget()
        self.ban_list.setObjectName("unbansList")
        self.ban_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        layout.addWidget(self.ban_list)

        self.status_label = QLabel("")
        self.status_label.setObjectName("unbansStatus")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        button_row = QHBoxLayout()

        self.unban_button = QPushButton("Unban Selected")
        self.unban_button.setObjectName("unbansUnbanButton")
        self.unban_button.setToolTip("Unban the selected players now, ahead of their scheduled expiry")
        apply_glow(self.unban_button, SUCCESS)
        self.unban_button.clicked.connect(self._unban_selected)
        button_row.addWidget(self.unban_button)

        button_row.addStretch()

        close_button = QPushButton("Close")
        close_button.setObjectName("unbansCloseButton")
        close_button.setToolTip("Close this window")
        close_button.clicked.connect(self.accept)
        button_row.addWidget(close_button)

        layout.addLayout(button_row)

    def _reload(self):
        self.ban_list.clear()
        now = datetime.now(timezone.utc)

        bans = temp_bans.load_temp_bans()
        if not bans:
            self.status_label.setText("No pending temp bans.")

        for ban in bans:
            expires = datetime.fromisoformat(ban.expires_at)
            label = f"{ban.display_name} — {ban.group_name} — {_format_remaining(expires, now)}"
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, ban)  # the TempBan object itself
            item.setToolTip(ban.reason)
            self.ban_list.addItem(item)

    def _unban_selected(self):
        selected = self.ban_list.selectedItems()
        if not selected:
            self.status_label.setText("Select at least one to unban.")
            return

        names = ", ".join(item.data(Qt.UserRole).display_name for item in selected)
        confirm = QMessageBox.question(
            self, "Confirm Early Unban",
            f"Unban {len(selected)} player(s) now, ahead of their scheduled expiry?\n\n{names}",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return

        self.unban_button.setEnabled(False)
        successes, failures = 0, 0

        for item in selected:
            ban = item.data(Qt.UserRole)
            self.status_label.setText(f"Unbanning {ban.display_name}...")
            QApplication.processEvents()

            result = self.client.unban_from_group(ban.group_id, ban.user_id)

            aar.save_entry(aar.AAREntry(
                timestamp=aar.now_iso(),
                moderator=self.client.display_name or "unknown",
                action="unban",
                target_display_name=ban.display_name,
                target_user_id=ban.user_id,
                details=f"Manually unbanned early (was scheduled to expire {ban.expires_at})",
                success=(result.status == "success"),
                error_message=result.error_message,
            ))

            if result.status == "success":
                temp_bans.remove_temp_ban(ban.user_id, ban.group_id)
                successes += 1
            else:
                failures += 1

        self.unban_button.setEnabled(True)
        self._reload()

        if failures:
            self.status_label.setText(f"Unbanned {successes}, {failures} failed (see AAR for details).")
        else:
            self.status_label.setText(f"Unbanned {successes}.")
