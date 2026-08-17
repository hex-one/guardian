"""
ban_dialog.py

The Ban popup. Unlike Note, this is a genuinely destructive, real action --
it actually bans the player from the group via VRChat's API (blocks them
from the group's instances, and the group itself). Nothing about this
gets treated lightly. Because of that:

  - It requires a reason (can't submit blank).
  - It shows a confirmation prompt before actually banning anyone.
  - Every attempt (success or failure) gets logged to the AAR either way.

--------------------------------------------------------------------------
BEGINNER NOTES:

- This only works for GROUP instances (there has to be a group that owns
  the instance to ban someone FROM). main.py checks for that and shows an
  explanation instead of opening this dialog if you're in a public
  instance with no owning group.

- "Temporary ban" here means: ban them now, and separately remember
  locally (in temp_bans.py) that they should be automatically unbanned
  after N days. VRChat itself doesn't have a concept of a timed ban --
  we're the ones tracking the clock and calling the real unban later.
--------------------------------------------------------------------------
"""

from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QTextEdit,
    QPushButton,
    QCheckBox,
    QSpinBox,
    QComboBox,
    QApplication,
    QMessageBox,
)

import aar
import note_lookup
import temp_bans
from vrchat_api import VRChatClient
from glow import apply_glow, DANGER


class BanDialog(QDialog):
    def __init__(self, client: VRChatClient, target_user_id: str, target_display_name: str,
                 group_id: str, group_name: str):
        super().__init__()
        self.setObjectName("BanDialog")
        self.setWindowTitle(f"Grp Ban — {target_display_name}")
        self.resize(380, 300)

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

        header = QLabel(f"Grp Ban {self.target_display_name} from {self.group_name}")
        header.setObjectName("banHeader")
        header.setWordWrap(True)
        layout.addWidget(header)

        self.status_label = QLabel("")
        self.status_label.setObjectName("banStatus")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.reason_input = QTextEdit()
        self.reason_input.setObjectName("banReasonInput")
        self.reason_input.setPlaceholderText("Reason for the ban (required, also saved as a note)")
        layout.addWidget(self.reason_input)

        temp_row = QHBoxLayout()
        self.temp_checkbox = QCheckBox("Temporary ban —")
        self.temp_checkbox.setObjectName("tempBanCheckbox")
        self.temp_checkbox.setToolTip("Ban for a set duration, then auto-unban -- instead of permanent")
        self.temp_checkbox.toggled.connect(self._on_temp_toggled)
        temp_row.addWidget(self.temp_checkbox)

        self.duration_amount_input = QSpinBox()
        self.duration_amount_input.setObjectName("tempBanAmount")
        self.duration_amount_input.setToolTip("How long the temporary ban lasts")
        self.duration_amount_input.setRange(1, 999)
        self.duration_amount_input.setValue(7)
        self.duration_amount_input.setEnabled(False)
        temp_row.addWidget(self.duration_amount_input)

        self.duration_unit_combo = QComboBox()
        self.duration_unit_combo.setObjectName("tempBanUnit")
        self.duration_unit_combo.setToolTip("Time unit for the temporary ban duration")
        # Item text is what's shown; item data is the keyword timedelta()
        # actually expects, so we don't need to translate "days"/"day(s)"
        # back and forth anywhere else.
        self.duration_unit_combo.addItem("Minutes", "minutes")
        self.duration_unit_combo.addItem("Hours", "hours")
        self.duration_unit_combo.addItem("Days", "days")
        self.duration_unit_combo.setCurrentIndex(2)  # Days, matching the old default
        self.duration_unit_combo.setEnabled(False)
        temp_row.addWidget(self.duration_unit_combo)

        temp_row.addStretch()
        layout.addLayout(temp_row)

        note = QLabel("Unchecked = permanent ban.")
        note.setObjectName("banPermanentNote")
        layout.addWidget(note)

        button_row = QHBoxLayout()
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setObjectName("banCancelButton")
        self.cancel_button.setToolTip("Close without banning")
        self.cancel_button.clicked.connect(self.reject)
        button_row.addWidget(self.cancel_button)

        self.ban_button = QPushButton("Grp Ban")
        self.ban_button.setObjectName("banConfirmButton")
        self.ban_button.setToolTip("Confirm and execute the group ban")
        apply_glow(self.ban_button, DANGER)
        self.ban_button.clicked.connect(self._attempt_ban)
        button_row.addWidget(self.ban_button)

        layout.addLayout(button_row)

    def _on_temp_toggled(self, checked: bool):
        self.duration_amount_input.setEnabled(checked)
        self.duration_unit_combo.setEnabled(checked)

    def _attempt_ban(self):
        reason = self.reason_input.toPlainText().strip()
        if not reason:
            self.status_label.setText("A reason is required.")
            return

        is_temp = self.temp_checkbox.isChecked()
        duration_amount = self.duration_amount_input.value()
        duration_unit = self.duration_unit_combo.currentData()  # "minutes"/"hours"/"days"
        duration_label = self.duration_unit_combo.currentText().lower()

        confirm_text = (
            f"Grp Ban {self.target_display_name} from {self.group_name}"
            + (f" for {duration_amount} {duration_label}?" if is_temp else " PERMANENTLY?")
        )
        confirm = QMessageBox.question(
            self, "Confirm Grp Ban", confirm_text,
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return

        self.status_label.setText("Saving note...")
        self.ban_button.setEnabled(False)
        QApplication.processEvents()

        # Same pattern as the Note action: save the reason as a note first,
        # regardless of whether the ban itself succeeds -- the note is its
        # own useful record even on its own.
        note_result = self.client.set_user_note(self.target_user_id, reason)

        self.status_label.setText("Banning...")
        QApplication.processEvents()
        ban_result = self.client.ban_from_group(self.group_id, self.target_user_id)

        expires_at = temp_bans.expires_at_from(duration_amount, duration_unit) if is_temp else None

        aar.save_entry(aar.AAREntry(
            timestamp=aar.now_iso(),
            moderator=self.client.display_name or "unknown",
            action="ban",
            target_display_name=self.target_display_name,
            target_user_id=self.target_user_id,
            details=reason,
            success=(ban_result.status == "success"),
            error_message=ban_result.error_message,
            limited=is_temp,
            expires_at=expires_at,
        ))

        self.ban_button.setEnabled(True)

        if ban_result.status != "success":
            self.status_label.setText(f"Ban failed: {ban_result.error_message}")
            return

        if is_temp:
            temp_bans.add_temp_ban(temp_bans.TempBan(
                user_id=self.target_user_id,
                display_name=self.target_display_name,
                group_id=self.group_id,
                group_name=self.group_name,
                reason=reason,
                banned_at=aar.now_iso(),
                expires_at=expires_at,
            ))

        note_warning = "" if note_result.status == "success" else " (note-saving failed, but the ban went through)"
        self.status_label.setText(f"Banned.{note_warning}")
        self.accept()
