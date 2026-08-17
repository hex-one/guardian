"""
note_dialog.py

The popup for adding/editing a note on a player. Calls VRChat's real
userNotes API (via vrchat_api.py) and logs the result to the local AAR
log (aar.py) either way -- successes AND failures, so the AAR is a
trustworthy record of what was actually attempted, not just what worked.
Honest record-keeping means writing down the misses too.

--------------------------------------------------------------------------
BEGINNER NOTES:

- This dialog is reused for both "adding a fresh note" and "editing an
  existing one" -- there's no separate edit flow, because VRChat's API
  itself treats them the same way (posting a note again just overwrites
  your previous one for that player). We pre-fill the text box by
  checking our own local AAR log for the last note we sent this player,
  so editing feels natural even though under the hood it's identical to
  creating one.

- Every widget has setObjectName(...) set, same as the login dialog, for
  your QSS styling whenever it's ready.
--------------------------------------------------------------------------
"""

from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QTextEdit,
    QCheckBox,
    QPushButton,
    QApplication,
    QInputDialog,
)

import aar
import watchlist
import watchlist_categories
import watchlist_submit
from vrchat_api import VRChatClient
from glow import apply_glow, PRIMARY


class NoteDialog(QDialog):
    def __init__(self, client: VRChatClient, target_user_id: str, target_display_name: str,
                 action: str = "note", banner: str = None):
        super().__init__()
        self.setObjectName("NoteDialog")

        # action/banner let Kick and Mute reuse this exact dialog (same
        # "fetch the live note, let the mod edit it, save" flow) while
        # logging to the AAR under their own action type and showing an
        # explanation of what this dialog can/can't actually do for them.
        # See main.py for how Kick/Mute construct these.
        self.action = action
        title_word = action.capitalize() if action != "note" else "Note"
        self.setWindowTitle(f"{title_word} — {target_display_name}")
        self.resize(360, 300 if banner else 260)

        self.client = client
        self.target_user_id = target_user_id
        self.target_display_name = target_display_name
        self.banner_text = banner

        self._build_ui()
        self._load_current_note()

    def _load_current_note(self):
        """
        Checks VRChat directly for whatever note is currently on file for
        this player (via GET /users/{id}, which includes YOUR note on them).
        This is the source of truth -- it'll reflect notes set from the
        VRChat website too, not just ones sent through this app. If the
        live check fails for some reason (offline, expired session), we
        fall back to our own local AAR record instead of leaving the box
        empty and silently overwriting whatever's actually on file.
        """
        self.status_label.setText("Checking VRChat for an existing note...")
        QApplication.processEvents()

        result = self.client.get_user(self.target_user_id)

        if result.status == "success":
            if result.note:
                self.note_input.setPlainText(result.note)
                self.status_label.setText("Editing the existing note VRChat has on file for this player.")
            else:
                self.status_label.setText("No existing note on file for this player yet.")
            return

        # Live fetch failed -- fall back to our local record rather than
        # showing a blank box that would silently overwrite an existing note.
        previous_note = aar.latest_note_for_user(self.target_user_id)
        if previous_note:
            self.note_input.setPlainText(previous_note)
            self.status_label.setText(
                f"Couldn't reach VRChat to check the current note ({result.error_message}) -- "
                f"showing the last note sent from this app instead."
            )
        else:
            self.status_label.setText(f"Couldn't check for an existing note: {result.error_message}")

    def _watchlist_button_label(self) -> str:
        return "Remove from WatchList" if self.target_user_id in watchlist.get_watched_ids() else "Add to WatchList"

    def _toggle_watchlist(self):
        if self.target_user_id in watchlist.get_watched_ids():
            watchlist.remove_entries([self.target_user_id])
            aar.save_entry(aar.AAREntry(
                timestamp=aar.now_iso(),
                moderator=self.client.display_name or "unknown",
                action="watchlist_remove",
                target_display_name=self.target_display_name,
                target_user_id=self.target_user_id,
                details="Removed from watchlist",
                success=True,
            ))
            self.status_label.setText(f"Removed {self.target_display_name} from the watchlist.")
        else:
            category_labels = [watchlist_categories.CATEGORIES[k].label for k in watchlist_categories.CATEGORY_ORDER]
            chosen_label, ok = QInputDialog.getItem(
                self, "Add to Watchlist", f"Category for {self.target_display_name}:", category_labels, 0, False
            )
            if not ok:
                return
            category_key = next(k for k in watchlist_categories.CATEGORY_ORDER
                                 if watchlist_categories.CATEGORIES[k].label == chosen_label)

            # Routes through the shared submission logic -- if Sheets sync
            # is configured, this actually submits to the shared list
            # (with the fresh duplicate/cleared check), not just a
            # local-only add.
            status = watchlist_submit.submit_watchlist_entry(
                self, self.client, self.target_user_id, self.target_display_name,
                self.note_input.toPlainText().strip(), category_key,
            )
            self.status_label.setText(status)
        self.watchlist_button.setText(self._watchlist_button_label())

    def _build_ui(self):
        layout = QVBoxLayout(self)

        if self.banner_text:
            banner_label = QLabel(self.banner_text)
            banner_label.setObjectName("actionBanner")
            banner_label.setWordWrap(True)
            layout.addWidget(banner_label)

        header_word = "Note for" if self.action == "note" else f"{self.action.capitalize()} — note for"
        header = QLabel(f"{header_word} {self.target_display_name}")
        header.setObjectName("noteHeader")
        header.setWordWrap(True)
        layout.addWidget(header)

        self.status_label = QLabel("")
        self.status_label.setObjectName("noteStatus")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.note_input = QTextEdit()
        self.note_input.setObjectName("noteInput")
        self.note_input.setPlaceholderText("What's this player being noted for?")
        layout.addWidget(self.note_input)

        # Only offered for plain notes -- Kick/Ban reuse this dialog but
        # their whole point IS the AAR record, so excluding those wouldn't
        # make sense. A plain note can be purely personal (e.g. "cool
        # builder, ask about their avatar setup later") with nothing to do
        # with moderation, hence the option here specifically.
        self.exclude_from_aar_checkbox = None
        if self.action == "note":
            self.exclude_from_aar_checkbox = QCheckBox("Personal note \u2014 exclude from AAR report")
            self.exclude_from_aar_checkbox.setObjectName("noteExcludeFromAarCheckbox")
            self.exclude_from_aar_checkbox.setToolTip(
                "Keep this note off the local AAR log -- it still saves to VRChat either way"
            )
            layout.addWidget(self.exclude_from_aar_checkbox)

        button_row = QHBoxLayout()

        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setObjectName("noteCancelButton")
        self.cancel_button.setToolTip("Close without saving")
        self.cancel_button.clicked.connect(self.reject)
        button_row.addWidget(self.cancel_button)

        self.watchlist_button = QPushButton(self._watchlist_button_label())
        self.watchlist_button.setObjectName("noteWatchlistButton")
        self.watchlist_button.setToolTip("Add or remove this player from the watchlist")
        self.watchlist_button.clicked.connect(self._toggle_watchlist)
        button_row.addWidget(self.watchlist_button)

        save_label = "Save Note" if self.action == "note" else f"Save Note & Log {self.action.capitalize()}"
        self.save_button = QPushButton(save_label)
        self.save_button.setObjectName("noteSaveButton")
        self.save_button.setToolTip("Save this note to VRChat")
        apply_glow(self.save_button, PRIMARY)
        self.save_button.clicked.connect(self._save)
        button_row.addWidget(self.save_button)

        layout.addLayout(button_row)

    def _save(self):
        note_text = self.note_input.toPlainText().strip()
        if not note_text:
            self.status_label.setText("Note can't be empty.")
            return

        self.status_label.setText("Saving to VRChat...")
        self.save_button.setEnabled(False)
        QApplication.processEvents()

        result = self.client.set_user_note(self.target_user_id, note_text)
        self.save_button.setEnabled(True)

        exclude_from_aar = self.exclude_from_aar_checkbox is not None and self.exclude_from_aar_checkbox.isChecked()

        # Log to the AAR either way -- a failed attempt is still worth a
        # record ("tried to note this player, but it failed because...") --
        # unless the mod explicitly marked this one as personal/non-
        # moderation via the checkbox above, in which case it's skipped
        # entirely (the note itself still saves to VRChat regardless).
        if not exclude_from_aar:
            aar.save_entry(aar.AAREntry(
                timestamp=aar.now_iso(),
                moderator=self.client.display_name or "unknown",
                action=self.action,
                target_display_name=self.target_display_name,
                target_user_id=self.target_user_id,
                details=note_text,
                success=(result.status == "success"),
                error_message=result.error_message,
            ))

        if result.status == "success":
            done_word = "Note saved." if self.action == "note" else f"Note saved and {self.action} logged."
            if exclude_from_aar:
                done_word += " (Not added to AAR.)"
            self.status_label.setText(done_word)
            self.accept()
        else:
            self.status_label.setText(f"Failed to save: {result.error_message}")
