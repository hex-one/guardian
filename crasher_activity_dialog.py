"""
crasher_activity_dialog.py

The "Crasher Activity" right-click viewer -- shows every locally-
observed correlation between this player switching avatars nearby and
something suspicious happening shortly after (a Udon script exception,
a model-validation warning, or -- the strongest one -- the log going
silent for good with no graceful shutdown logged in between). Opened
from main.py's player menu, disabled there entirely when there's
nothing to show (see _build_player_menu).

No shared list, no "Check Shared List" button the way votes_dialog.py
has one -- see crasher_activity.py's module docstring for why this
stays local. What's shown here is exactly what Guardian saw and
nothing more; the caveat text says so plainly rather than letting a
correlation read as a verdict, even for the "strong"-confidence entries.
"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
)

import aar
import crasher_activity
from glow import apply_glow, DANGER, WARNING

_SIGNAL_LABELS = {
    "udon_exception": "Udon exception",
    "model_validation_warning": "avatar validation warning",
    "validation_warning_with_zero_mb": "validation warning + 0MB download",
    "crash_after_validation_warning": "log went silent after a validation warning",
}


class CrasherActivityDialog(QDialog):
    def __init__(self, vrchat_client, player_user_id: str, player_name: str):
        super().__init__()
        self.setObjectName("CrasherActivityDialog")
        self.setWindowTitle(f"Crasher Activity — {player_name}")
        self.resize(460, 420)

        # Optional only so this dialog can still be constructed/tested
        # without a live session; main.py always passes the real client.
        self.vrchat_client = vrchat_client
        self.player_user_id = player_user_id
        self.player_name = player_name

        self._build_ui()
        self._reload()

    def _build_ui(self):
        outer = QVBoxLayout(self)

        header = QLabel(
            f"Suspicious timing Guardian observed shortly after {self.player_name} switched avatars "
            "nearby. Every entry here is a TIMING correlation, not proof -- even the \"strong\"-"
            "confidence ones, where the log went silent for good right after. A client can crash "
            "for reasons that have nothing to do with any particular avatar."
        )
        header.setObjectName("crasherActivityHeader")
        header.setWordWrap(True)
        outer.addWidget(header)

        self.flag_list = QListWidget()
        self.flag_list.setObjectName("crasherActivityFlagList")
        self.flag_list.setToolTip(
            "Possible crasher activity flags involving this player, most recent last -- "
            "select one or more and Clear Selected to dismiss them"
        )
        self.flag_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        outer.addWidget(self.flag_list)

        self.status_label = QLabel("")
        self.status_label.setObjectName("crasherActivityStatus")
        self.status_label.setWordWrap(True)
        outer.addWidget(self.status_label)

        button_row = QHBoxLayout()

        self.clear_button = QPushButton("Clear Selected")
        self.clear_button.setObjectName("crasherActivityClearButton")
        self.clear_button.setToolTip(
            f"Dismiss the selected event(s) for {self.player_name} -- doesn't affect other "
            "players an ambiguous flag also named"
        )
        apply_glow(self.clear_button, DANGER)
        self.clear_button.clicked.connect(self._clear_selected)
        button_row.addWidget(self.clear_button)

        button_row.addStretch()

        close_button = QPushButton("Close")
        close_button.setObjectName("crasherActivityCloseButton")
        close_button.setToolTip("Close this window")
        close_button.clicked.connect(self.accept)
        button_row.addWidget(close_button)

        outer.addLayout(button_row)

    def _format_flag(self, flag: "crasher_activity.CrasherFlag") -> str:
        where = f"world {flag.world_id}" + (f" (instance {flag.instance_id})" if flag.instance_id else "")
        signal_label = _SIGNAL_LABELS.get(flag.signal, flag.signal)
        confidence_tag = "STRONG" if flag.confidence == "strong" else "circumstantial"
        prefix = f"[{confidence_tag}] {signal_label}"

        if len(flag.candidates) == 1:
            c = flag.candidates[0]
            return (f"{prefix} — {flag.observed_at} — {where} — avatar \"{c.avatar_name}\", switched "
                    f"{c.seconds_before_exception:.0f}s before")

        others = ", ".join(
            f"{c.display_name} (\"{c.avatar_name}\")" for c in flag.candidates
            if not (c.user_id == self.player_user_id or c.display_name == self.player_name)
        )
        mine = next(
            c for c in flag.candidates
            if c.user_id == self.player_user_id or c.display_name == self.player_name
        )
        return (f"{prefix} — {flag.observed_at} — {where} — AMBIGUOUS: avatar \"{mine.avatar_name}\" "
                f"({mine.seconds_before_exception:.0f}s before) — also switched around the same "
                f"time: {others}")

    def _reload(self):
        self.flag_list.clear()
        flags = crasher_activity.get_flags_for_target(self.player_user_id, self.player_name)
        if not flags:
            self.status_label.setText("No possible crasher activity observed for this player.")
            return

        strong_count = 0
        for flag in sorted(flags, key=lambda f: f.observed_at):
            item = QListWidgetItem(self._format_flag(flag))
            item.setData(Qt.UserRole, flag)
            if flag.confidence == "strong":
                item.setForeground(QColor(DANGER))
                strong_count += 1
            else:
                item.setForeground(QColor(WARNING))
            self.flag_list.addItem(item)

        strong_note = f", {strong_count} of them strong-confidence" if strong_count else ""
        self.status_label.setText(f"{len(flags)} flag(s){strong_note} — review before acting on any of them.")

    def _clear_selected(self):
        selected = self.flag_list.selectedItems()
        if not selected:
            self.status_label.setText("Select at least one event to clear.")
            return

        flags = [item.data(Qt.UserRole) for item in selected]
        confirm = QMessageBox.question(
            self, "Clear Crasher Activity",
            f"Dismiss {len(flags)} event(s) for {self.player_name}? Any other player an "
            "ambiguous flag also named keeps seeing it until they clear it too.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return

        moderator = self.vrchat_client.display_name if self.vrchat_client else "unknown"
        cleared = 0
        for flag in flags:
            if crasher_activity.dismiss_flag_for_target(flag.flag_id, self.player_user_id, self.player_name):
                cleared += 1

        if cleared:
            signal_label = _SIGNAL_LABELS.get(flags[0].signal, flags[0].signal) if len(flags) == 1 else None
            details = (
                f"Dismissed a possible-crasher flag ({signal_label}, {flags[0].observed_at})"
                if signal_label else f"Dismissed {cleared} possible-crasher flag(s)"
            )
            aar.save_entry(aar.AAREntry(
                timestamp=aar.now_iso(), moderator=moderator, action="crasher_activity_dismissed",
                target_display_name=self.player_name, target_user_id=self.player_user_id,
                details=f"{details} for {self.player_name}. Circumstantial to begin with -- reviewed and dismissed.",
                success=True,
            ))

        self._reload()
        self.status_label.setText(f"Cleared {cleared} of {len(flags)} selected.")
