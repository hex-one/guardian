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

from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
)

import crasher_activity
from glow import DANGER, WARNING

_SIGNAL_LABELS = {
    "udon_exception": "Udon exception",
    "model_validation_warning": "avatar validation warning",
    "crash_after_validation_warning": "log went silent after a validation warning",
}


class CrasherActivityDialog(QDialog):
    def __init__(self, player_user_id: str, player_name: str):
        super().__init__()
        self.setObjectName("CrasherActivityDialog")
        self.setWindowTitle(f"Crasher Activity — {player_name}")
        self.resize(460, 380)

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
        self.flag_list.setToolTip("Possible crasher activity flags involving this player, most recent last")
        outer.addWidget(self.flag_list)

        self.status_label = QLabel("")
        self.status_label.setObjectName("crasherActivityStatus")
        self.status_label.setWordWrap(True)
        outer.addWidget(self.status_label)

        button_row = QHBoxLayout()
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
            if flag.confidence == "strong":
                item.setForeground(QColor(DANGER))
                strong_count += 1
            else:
                item.setForeground(QColor(WARNING))
            self.flag_list.addItem(item)

        strong_note = f", {strong_count} of them strong-confidence" if strong_count else ""
        self.status_label.setText(f"{len(flags)} flag(s){strong_note} — review before acting on any of them.")
