"""
invite_dialog.py

Right-click a player -> Invite. Sends a real group-membership invite via
VRChat's API (POST /groups/{id}/invites) -- this invites them to JOIN THE
GROUP, not just the current instance (VRChat doesn't have a lightweight
"invite to this specific instance" web API action separate from group
membership). An open door to the whole circle, not just the current room.
Only enabled when there's a group instance to invite them into and the
logged-in user has invite permission there -- same rule as Grp Kick/Grp
Ban.
"""

from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QApplication,
)

import aar
from vrchat_api import VRChatClient
from glow import apply_glow, PRIMARY


class InviteDialog(QDialog):
    def __init__(self, client: VRChatClient, target_user_id: str, target_display_name: str,
                 group_id: str, group_name: str):
        super().__init__()
        self.setObjectName("InviteDialog")
        self.setWindowTitle(f"Invite — {target_display_name}")
        self.resize(360, 160)

        self.client = client
        self.target_user_id = target_user_id
        self.target_display_name = target_display_name
        self.group_id = group_id
        self.group_name = group_name

        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        header = QLabel(f"Invite {self.target_display_name} to join {self.group_name}?")
        header.setObjectName("inviteHeader")
        header.setWordWrap(True)
        layout.addWidget(header)

        self.status_label = QLabel("")
        self.status_label.setObjectName("inviteStatus")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        button_row = QHBoxLayout()

        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setObjectName("inviteCancelButton")
        self.cancel_button.setToolTip("Close without sending the invite")
        self.cancel_button.clicked.connect(self.reject)
        button_row.addWidget(self.cancel_button)

        self.invite_button = QPushButton("Send Invite")
        self.invite_button.setObjectName("inviteConfirmButton")
        self.invite_button.setToolTip("Send a group-membership invite via VRChat")
        apply_glow(self.invite_button, PRIMARY)
        self.invite_button.clicked.connect(self._send_invite)
        button_row.addWidget(self.invite_button)

        layout.addLayout(button_row)

    def _send_invite(self):
        self.status_label.setText("Sending invite...")
        self.invite_button.setEnabled(False)
        QApplication.processEvents()

        result = self.client.invite_user_to_group(self.group_id, self.target_user_id)

        aar.save_entry(aar.AAREntry(
            timestamp=aar.now_iso(),
            moderator=self.client.display_name or "unknown",
            action="invite",
            target_display_name=self.target_display_name,
            target_user_id=self.target_user_id,
            details=f"Invited to join {self.group_name}",
            success=(result.status == "success"),
            error_message=result.error_message,
        ))

        self.invite_button.setEnabled(True)

        if result.status == "success":
            self.status_label.setText("Invite sent.")
            self.accept()
        else:
            self.status_label.setText(f"Failed to send invite: {result.error_message}")
