"""
votes_dialog.py

The "Votes" right-click viewer -- shows what Guardian actually knows
about one player's vote-kick history: when a vote was started against
them, whether it succeeded, and in which world/instance it happened.
Opened from main.py's player menu, disabled there entirely when there's
nothing to show (see _build_player_menu).

Deliberately has NO "initiated by" field anywhere in this dialog.
VRChat's own log never exposes who started a vote-kick to any client
-- confirmed against VRCX's complete vote-parsing source, not guessed.
Rather than leave that silently missing and let it look like a bug,
the header says so plainly.
"""

from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QApplication,
)

import vote_kicks
import watchlist_sync_settings
import sheets_vote_kicks
from glow import apply_glow, INFO


class VotesDialog(QDialog):
    def __init__(self, player_user_id: str, player_name: str):
        super().__init__()
        self.setObjectName("VotesDialog")
        self.setWindowTitle(f"Votes — {player_name}")
        self.resize(420, 360)

        self.player_user_id = player_user_id
        self.player_name = player_name

        self._build_ui()
        self._reload_local()

    def _build_ui(self):
        outer = QVBoxLayout(self)

        header = QLabel(
            f"Vote-kick events Guardian has personally observed against {self.player_name}. "
            "VRChat's log never says who started a vote -- only the target and the outcome "
            "are ever written down, so that field just isn't here to show."
        )
        header.setObjectName("votesHeader")
        header.setWordWrap(True)
        outer.addWidget(header)

        self.event_list = QListWidget()
        self.event_list.setObjectName("votesEventList")
        self.event_list.setToolTip("Vote-kick events Guardian has recorded for this player, most recent last")
        outer.addWidget(self.event_list)

        self.status_label = QLabel("")
        self.status_label.setObjectName("votesStatus")
        self.status_label.setWordWrap(True)
        outer.addWidget(self.status_label)

        button_row = QHBoxLayout()

        self.check_shared_button = QPushButton("Check Shared List")
        self.check_shared_button.setObjectName("votesCheckSharedButton")
        self.check_shared_button.setToolTip("Pull this player's vote-kick history from the shared VoteKicks list")
        apply_glow(self.check_shared_button, INFO)
        self.check_shared_button.clicked.connect(self._check_shared)
        button_row.addWidget(self.check_shared_button)

        button_row.addStretch()

        close_button = QPushButton("Close")
        close_button.setObjectName("votesCloseButton")
        close_button.setToolTip("Close this window")
        close_button.clicked.connect(self.accept)
        button_row.addWidget(close_button)

        outer.addLayout(button_row)

    def _format_local(self, event: "vote_kicks.VoteKickEvent") -> str:
        where = f"world {event.world_id}" + (f" (instance {event.instance_id})" if event.instance_id else "")
        if event.status == "succeeded":
            when = event.succeeded_at or event.initiated_at
            outcome = "✅ Succeeded"
        else:
            when = event.initiated_at
            outcome = "⏳ Initiated (outcome not yet observed)"
        return f"{outcome} — {when} — {where}"

    def _reload_local(self):
        self.event_list.clear()
        events = vote_kicks.get_events_for_target(self.player_user_id, self.player_name)
        if not events:
            self.status_label.setText("No locally-observed vote-kick events for this player.")
            return
        for event in sorted(events, key=lambda e: e.initiated_at or e.succeeded_at):
            self.event_list.addItem(QListWidgetItem(self._format_local(event)))
        self.status_label.setText(f"{len(events)} locally-observed event(s).")

    def _check_shared(self):
        sync_settings = watchlist_sync_settings.load_settings()
        if not watchlist_sync_settings.is_configured():
            self.status_label.setText(
                "Sync not configured -- set the Sheet CSV URL and Apps Script Web App URL in "
                "Config first (account menu → your username → Config → Watchlist Sync)."
            )
            return

        self.check_shared_button.setEnabled(False)
        self.status_label.setText("Checking the shared list...")
        QApplication.processEvents()

        result = sheets_vote_kicks.fetch_events(sync_settings.csv_url)
        self.check_shared_button.setEnabled(True)

        if result.status != "success":
            self.status_label.setText(f"Couldn't reach the shared list: {result.error_message}")
            return

        matches = [
            e for e in result.entries
            if (self.player_user_id and e.target_user_id == self.player_user_id)
            or (not e.target_user_id and e.target_display_name == self.player_name)
        ]

        self.event_list.clear()
        if not matches:
            self.status_label.setText("Nothing on the shared list for this player.")
            return

        for e in sorted(matches, key=lambda e: e.initiated_at or e.succeeded_at):
            where = f"world {e.world_id}" + (f" (instance {e.instance_id})" if e.instance_id else "")
            if e.status == "succeeded":
                when = e.succeeded_at or e.initiated_at
                outcome = "✅ Succeeded"
            else:
                when = e.initiated_at
                outcome = "⏳ Initiated (outcome not yet observed)"
            self.event_list.addItem(QListWidgetItem(f"{outcome} — {when} — {where} — reported by {e.submitted_by}"))

        self.status_label.setText(f"{len(matches)} event(s) on the shared list.")
