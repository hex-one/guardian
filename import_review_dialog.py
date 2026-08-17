"""
import_review_dialog.py

Shown after Import in the Watchlist window. Imported entries are treated
as brand-new SUBMISSION CANDIDATES -- never trusted or added directly --
so every one gets checked against a single fresh pull of the shared list
(both pending and already-reviewed rows) before anything is submitted,
exactly the same rule a normal single Add follows, just batched into one
table instead of one popup per entry. Trust is earned per-entry, not
inherited from the batch it arrived in.

--------------------------------------------------------------------------
BEGINNER NOTES:

- One fetch_all() covers the WHOLE batch, not one per row -- checking 50
  imported entries against the shared list is one network call, not 50.

- Each row is independently editable (User ID, Display Name, Reason,
  Category) right in the table before you submit -- this is the "batch
  view table edit in field" part. The Include checkbox lets you leave
  specific rows out of the submission without deleting them from the
  table.

- A "cleared" status needs the same soft-warning treatment a single Add
  gets -- checking Include on a cleared row and hitting Submit shows ONE
  batched confirmation listing everyone affected, rather than a
  popup-per-row wall of clicks.
--------------------------------------------------------------------------
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QComboBox,
    QCheckBox,
    QWidget,
    QPushButton,
    QMessageBox,
    QApplication,
    QHeaderView,
)

import aar
import watchlist
import watchlist_categories
import watchlist_sync_settings
import sheets_watchlist
from glow import apply_glow, PRIMARY, INFO

COL_INCLUDE = 0
COL_USER_ID = 1
COL_DISPLAY_NAME = 2
COL_REASON = 3
COL_CATEGORY = 4
COL_STATUS = 5


class ImportReviewDialog(QDialog):
    def __init__(self, vrchat_client, imported_entries: list):
        super().__init__()
        self.setObjectName("ImportReviewDialog")
        self.setWindowTitle("Review Imported Watchlist Entries")
        self.resize(820, 440)

        self.vrchat_client = vrchat_client
        self.imported_entries = imported_entries

        # row -> (status_kind, matching SheetEntry or None). status_kind is
        # one of: "new", "pending", "approved", "rejected", "cleared",
        # "local_only" (no sync configured), "check_failed".
        self.row_status = {}

        self._build_ui()
        self._populate_table()
        self._check_all_against_shared_list()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        header = QLabel(
            "Imported entries are treated as new submissions, not trusted as-is -- each one is "
            "checked against a fresh copy of the shared list before anything is sent. Edit any "
            "field below before submitting; uncheck Include to leave a row out."
        )
        header.setObjectName("importReviewHeader")
        header.setWordWrap(True)
        layout.addWidget(header)

        self.table = QTableWidget()
        self.table.setObjectName("importReviewTable")
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(["Include", "User ID", "Display Name", "Reason", "Category", "Status"])
        self.table.horizontalHeader().setSectionResizeMode(COL_REASON, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(COL_STATUS, QHeaderView.Stretch)
        layout.addWidget(self.table)

        self.status_label = QLabel("")
        self.status_label.setObjectName("importReviewStatus")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        button_row = QHBoxLayout()

        self.recheck_button = QPushButton("Re-check Against Shared List")
        self.recheck_button.setObjectName("importRecheckButton")
        self.recheck_button.setToolTip("Re-fetch the shared list and re-check every row's status")
        apply_glow(self.recheck_button, INFO)
        self.recheck_button.clicked.connect(self._check_all_against_shared_list)
        button_row.addWidget(self.recheck_button)

        button_row.addStretch()

        self.submit_button = QPushButton("Submit Selected")
        self.submit_button.setObjectName("importSubmitButton")
        self.submit_button.setToolTip("Submit every included row to the watchlist")
        apply_glow(self.submit_button, PRIMARY)
        self.submit_button.clicked.connect(self._submit_selected)
        button_row.addWidget(self.submit_button)

        close_button = QPushButton("Close")
        close_button.setObjectName("importCloseButton")
        close_button.setToolTip("Close without importing")
        close_button.clicked.connect(self.accept)
        button_row.addWidget(close_button)

        layout.addLayout(button_row)

    # -- Table setup --------------------------------------------------------

    def _populate_table(self):
        self.table.setRowCount(len(self.imported_entries))
        for row, entry in enumerate(self.imported_entries):
            container = QWidget()
            inner = QHBoxLayout(container)
            inner.setAlignment(Qt.AlignCenter)
            inner.setContentsMargins(0, 0, 0, 0)
            include_checkbox = QCheckBox()
            include_checkbox.setToolTip("Include this row when submitting")
            include_checkbox.setChecked(True)
            inner.addWidget(include_checkbox)
            self.table.setCellWidget(row, COL_INCLUDE, container)

            self.table.setItem(row, COL_USER_ID, QTableWidgetItem(entry.user_id))
            self.table.setItem(row, COL_DISPLAY_NAME, QTableWidgetItem(entry.display_name))
            self.table.setItem(row, COL_REASON, QTableWidgetItem(entry.reason))

            category_combo = QComboBox()
            category_combo.setToolTip("Watchlist category to submit this entry under")
            for key in watchlist_categories.CATEGORY_ORDER:
                cat = watchlist_categories.CATEGORIES[key]
                category_combo.addItem(f"{cat.icon} {cat.label}", key)
            start_index = (watchlist_categories.CATEGORY_ORDER.index(entry.category)
                           if entry.category in watchlist_categories.CATEGORY_ORDER else 0)
            category_combo.setCurrentIndex(start_index)
            self.table.setCellWidget(row, COL_CATEGORY, category_combo)

            status_item = QTableWidgetItem("Checking...")
            status_item.setFlags(status_item.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(row, COL_STATUS, status_item)

    def _row_include_checkbox(self, row: int) -> QCheckBox:
        return self.table.cellWidget(row, COL_INCLUDE).findChild(QCheckBox)

    def _current_row_values(self, row: int):
        user_id = self.table.item(row, COL_USER_ID).text().strip()
        display_name = self.table.item(row, COL_DISPLAY_NAME).text().strip()
        reason = self.table.item(row, COL_REASON).text().strip()
        category = self.table.cellWidget(row, COL_CATEGORY).currentData()
        include = self._row_include_checkbox(row).isChecked()
        return user_id, display_name, reason, category, include

    def _set_status(self, row: int, text: str):
        self.table.item(row, COL_STATUS).setText(text)

    # -- Checking against the shared list -----------------------------------

    def _check_all_against_shared_list(self):
        sync_settings = watchlist_sync_settings.load_settings()

        if not watchlist_sync_settings.is_configured():
            for row in range(self.table.rowCount()):
                self.row_status[row] = ("local_only", None)
                self._set_status(row, "No shared list configured -- will add locally only.")
            self.status_label.setText("No Sheets sync configured -- entries will be added locally only.")
            return

        self.status_label.setText("Checking all entries against the shared list (one fresh pull)...")
        self.recheck_button.setEnabled(False)
        QApplication.processEvents()

        check = sheets_watchlist.fetch_all(sync_settings.csv_url)
        self.recheck_button.setEnabled(True)

        if check.status != "success":
            self.status_label.setText(f"Couldn't check the shared list: {check.error_message}")
            for row in range(self.table.rowCount()):
                self.row_status[row] = ("check_failed", None)
                self._set_status(row, "Couldn't check \u2014 submit will add locally only.")
            return

        existing_by_id = {e.user_id: e for e in check.entries}

        for row in range(self.table.rowCount()):
            user_id = self.table.item(row, COL_USER_ID).text().strip()
            existing = existing_by_id.get(user_id)

            if existing is None:
                self.row_status[row] = ("new", None)
                self._set_status(row, "New \u2014 ready to submit")
            elif existing.status in ("pending", "approved"):
                self.row_status[row] = (existing.status, existing)
                self._set_status(row, f"Already on shared list ({existing.status}) \u2014 will be skipped")
            elif existing.status == "rejected":
                self.row_status[row] = ("rejected", existing)
                self._set_status(row, "Previously rejected \u2014 will be skipped")
            elif existing.status == "cleared":
                self.row_status[row] = ("cleared", existing)
                reviewer = existing.reviewed_by or "someone"
                self._set_status(row, f"Previously cleared by {reviewer} \u2014 will ask before resubmitting")

        self.status_label.setText("Check complete \u2014 review statuses below, then Submit Selected.")

    # -- Submission ----------------------------------------------------------

    def _submit_selected(self):
        sync_settings = watchlist_sync_settings.load_settings()
        submitted_by = self.vrchat_client.user_id if self.vrchat_client else "unknown"

        cleared_rows = [
            row for row in range(self.table.rowCount())
            if self.row_status.get(row, (None, None))[0] == "cleared" and self._current_row_values(row)[4]
        ]

        if cleared_rows:
            names = ", ".join(self.table.item(row, COL_DISPLAY_NAME).text() for row in cleared_rows)
            confirm = QMessageBox.question(
                self, "Resubmitting Previously Cleared Entries",
                f"{len(cleared_rows)} selected entr{'y is' if len(cleared_rows) == 1 else 'ies are'} "
                f"previously reviewed and cleared, and will be resubmitted for review:\n\n{names}"
                "\n\nProceed with these too?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if confirm != QMessageBox.Yes:
                # Uncheck them rather than aborting the whole batch -- the
                # rest of the selection (new entries etc.) can still go
                # through normally.
                for row in cleared_rows:
                    self._row_include_checkbox(row).setChecked(False)
                    self._set_status(row, "Skipped (cleared, not resubmitted).")

        submitted, skipped, failed = 0, 0, 0

        for row in range(self.table.rowCount()):
            user_id, display_name, reason, category, include = self._current_row_values(row)
            if not include:
                continue

            status_kind, _existing = self.row_status.get(row, ("new", None))

            if status_kind in ("pending", "approved", "rejected"):
                skipped += 1
                continue

            if status_kind in ("local_only", "check_failed") or not watchlist_sync_settings.is_configured():
                watchlist.add_entry(watchlist.WatchlistEntry(
                    user_id=user_id, display_name=display_name, reason=reason,
                    added_at=aar.now_iso(), category=category,
                ))
                submitted += 1
                self._set_status(row, "Added locally.")
                continue

            confirm_resubmit = (status_kind == "cleared")
            self._set_status(row, "Submitting...")
            QApplication.processEvents()

            result = sheets_watchlist.submit_entry(
                sync_settings.script_url, user_id, display_name, reason, submitted_by,
                category=category, confirm_resubmit=confirm_resubmit,
            )

            if result.status == "success":
                submitted += 1
                self._set_status(row, "Submitted for review.")
            else:
                failed += 1
                self._set_status(row, f"Failed: {result.error_message}")

        self.status_label.setText(
            f"Done \u2014 {submitted} submitted, {skipped} skipped (already on the list), {failed} failed."
        )
