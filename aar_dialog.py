"""
aar_dialog.py

Lets you "pull" the After Action Report -- view it, copy it to your
clipboard, save it as a .md file, submit it straight to a configured
Discord channel, or clear the local log. The record, whenever you need
to see it.

Also backs the Reports menu's filtered views (Show Bans/Show Kicks/
Show Notes) -- same dialog, same buttons, just constructed with an
`action_filter` (one of aar.ACTION_CATEGORIES' sets) and a different
title. Filtered, Clear only removes THAT category from the overall
AAR (aar.clear_entries(actions=...)), not the whole log -- everything
outside the filter is untouched either way.
"""

from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QTextEdit,
    QPushButton,
    QFileDialog,
    QApplication,
    QMessageBox,
    QInputDialog,
)

import aar
import discord_targets
import discord_api
from glow import apply_glow, DISCORD, WARNING


class AARReportDialog(QDialog):
    def __init__(self, action_filter: set = None, title: str = "After Action Report"):
        super().__init__()
        self.setObjectName("AARReportDialog")
        self.setWindowTitle(title)
        self.resize(520, 480)
        self._action_filter = action_filter

        self._build_ui()
        self._load_report()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        self.report_view = QTextEdit()
        self.report_view.setObjectName("aarReportView")
        self.report_view.setReadOnly(True)
        layout.addWidget(self.report_view)

        button_row = QHBoxLayout()

        self.copy_button = QPushButton("Copy to Clipboard")
        self.copy_button.setObjectName("aarCopyButton")
        self.copy_button.setToolTip("Copy the report text to the clipboard")
        self.copy_button.clicked.connect(self._copy_to_clipboard)
        button_row.addWidget(self.copy_button)

        self.save_button = QPushButton("Save to File...")
        self.save_button.setObjectName("aarSaveButton")
        self.save_button.setToolTip("Save the report to a Markdown file")
        self.save_button.clicked.connect(self._save_to_file)
        button_row.addWidget(self.save_button)

        self.discord_button = QPushButton("Submit to Discord")
        self.discord_button.setObjectName("aarDiscordButton")
        self.discord_button.setToolTip("Send the report to a configured Discord webhook")
        apply_glow(self.discord_button, DISCORD)
        self.discord_button.clicked.connect(self._submit_to_discord)
        button_row.addWidget(self.discord_button)

        layout.addLayout(button_row)

        # Clear is destructive, so it gets its own row -- separated from
        # Copy/Save so it's not an easy mis-click next to the safe actions.
        clear_row = QHBoxLayout()
        clear_row.addStretch()  # pushes the button to the right
        self.clear_button = QPushButton("Clear Report")
        self.clear_button.setObjectName("aarClearButton")
        self.clear_button.setToolTip("Permanently delete all entries in the local moderation log")
        apply_glow(self.clear_button, WARNING)
        self.clear_button.clicked.connect(self._clear_report)
        clear_row.addWidget(self.clear_button)
        layout.addLayout(clear_row)

    def _load_report(self):
        entries = aar.load_entries()
        if self._action_filter:
            entries = [e for e in entries if e.action in self._action_filter]
        self.report_text = aar.export_markdown(entries)
        self.report_view.setPlainText(self.report_text)

    def _copy_to_clipboard(self):
        QApplication.clipboard().setText(self.report_text)
        QMessageBox.information(self, "Copied", "Report copied to clipboard.")

    def _save_to_file(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save AAR Report", "aar_report.md", "Markdown (*.md)")
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.report_text)

    def _submit_to_discord(self):
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
                self, "Submit to Discord", "Send this report to:", names, 0, False
            )
            if not ok:
                return
            target = next(t for t in targets if t.name == chosen_name)

        self.discord_button.setEnabled(False)
        QApplication.processEvents()
        result = discord_api.send_report(target.webhook_url, self.report_text)
        self.discord_button.setEnabled(True)

        if result.status == "success":
            QMessageBox.information(self, "Sent", f'Report sent to "{target.name}".')
        else:
            QMessageBox.warning(self, "Failed to send", f'Couldn\'t send to "{target.name}": {result.error_message}')

    def _clear_report(self):
        if self._action_filter:
            scope_text = (
                f"This permanently deletes just the entries shown here "
                f"({self.windowTitle()}) from the local moderation action log -- "
                f"everything else in the overall AAR is untouched."
            )
        else:
            scope_text = "This permanently deletes the ENTIRE local moderation action log."

        confirm = QMessageBox.question(
            self,
            "Clear Report?",
            f"{scope_text} It does NOT undo any notes/kicks/bans already applied "
            f"on VRChat -- it only clears this local record. This can't be "
            f"undone.\n\n"
            f"Consider saving or copying the report first if you want a copy.\n\n"
            f"Clear it anyway?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,  # default to the safe choice
        )
        if confirm != QMessageBox.Yes:
            return

        aar.clear_entries(actions=self._action_filter)
        self._load_report()
