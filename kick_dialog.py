"""
kick_dialog.py

The Kick popup. This is a REAL action -- it removes the player's GROUP
MEMBERSHIP via VRChat's API (the same thing VRCX's "Kick" button in its
group moderation panel does). This is NOT the same as an instant live
instance kick (that one's Photon-only and out of reach). A kicked player
can rejoin the group later depending on the group's own join settings --
that's what makes Kick a lighter action than Ban, which locks them out
until manually unbanned.

Mirrors ban_dialog.py's pattern (reason required, confirmation prompt,
logs every attempt to the AAR either way) minus the temp-duration option,
since a kick doesn't have a timer -- there's nothing to auto-reverse.
A door closed, not locked.
"""

from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QTextEdit,
    QPushButton,
    QApplication,
    QMessageBox,
)

import aar
import note_lookup
from vrchat_api import VRChatClient
from glow import apply_glow, DANGER


class KickDialog(QDialog):
    def __init__(self, client: VRChatClient, target_user_id: str, target_display_name: str,
                 group_id: str, group_name: str):
        super().__init__()
        self.setObjectName("KickDialog")
        self.setWindowTitle(f"Grp Kick — {target_display_name}")
        self.resize(380, 260)

        self.client = client
        self.target_user_id = target_user_id
        self.target_display_name = target_display_name
        self.group_id = group_id
        self.group_name = group_name

        self._build_ui()
        self._load_current_note()

    def _load_current_note(self):
        note_text, status_message = note_lookup.fetch_current_note(self.client, self.target_user_id)
        if note_text:
            self.reason_input.setPlainText(note_text)
        self.status_label.setText(status_message)

    def _build_ui(self):
        layout = QVBoxLayout(self)

        header = QLabel(f"Grp Kick {self.target_display_name} from {self.group_name}")
        header.setObjectName("kickHeader")
        header.setWordWrap(True)
        layout.addWidget(header)

        info = QLabel(
            "This removes their group membership -- they can rejoin later "
            "depending on the group's join settings. For a full lockout, use Grp Ban instead."
        )
        info.setObjectName("kickInfo")
        info.setWordWrap(True)
        layout.addWidget(info)

        self.status_label = QLabel("")
        self.status_label.setObjectName("kickStatus")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.reason_input = QTextEdit()
        self.reason_input.setObjectName("kickReasonInput")
        self.reason_input.setPlaceholderText("Reason for the kick (required, also saved as a note)")
        layout.addWidget(self.reason_input)

        button_row = QHBoxLayout()
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setObjectName("kickCancelButton")
        self.cancel_button.setToolTip("Close without kicking")
        self.cancel_button.clicked.connect(self.reject)
        button_row.addWidget(self.cancel_button)

        self.kick_button = QPushButton("Grp Kick")
        self.kick_button.setObjectName("kickConfirmButton")
        self.kick_button.setToolTip("Confirm and execute the group membership kick")
        apply_glow(self.kick_button, DANGER)
        self.kick_button.clicked.connect(self._attempt_kick)
        button_row.addWidget(self.kick_button)

        layout.addLayout(button_row)

    def _attempt_kick(self):
        reason = self.reason_input.toPlainText().strip()
        if not reason:
            self.status_label.setText("A reason is required.")
            return

        confirm = QMessageBox.question(
            self, "Confirm Grp Kick",
            f"Grp Kick {self.target_display_name} from {self.group_name}?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return

        self.status_label.setText("Saving note...")
        self.kick_button.setEnabled(False)
        QApplication.processEvents()

        note_result = self.client.set_user_note(self.target_user_id, reason)

        self.status_label.setText("Kicking...")
        QApplication.processEvents()
        kick_result = self.client.kick_from_group(self.group_id, self.target_user_id)

        aar.save_entry(aar.AAREntry(
            timestamp=aar.now_iso(),
            moderator=self.client.display_name or "unknown",
            action="kick",
            target_display_name=self.target_display_name,
            target_user_id=self.target_user_id,
            details=reason,
            success=(kick_result.status == "success"),
            error_message=kick_result.error_message,
        ))

        self.kick_button.setEnabled(True)

        if kick_result.status != "success":
            self.status_label.setText(f"Kick failed: {kick_result.error_message}")
            return

        note_warning = "" if note_result.status == "success" else " (note-saving failed, but the kick went through)"
        self.status_label.setText(f"Kicked.{note_warning}")
        self.accept()
