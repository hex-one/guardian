"""
group_picker_dialog.py

The "From"/"To" half of "Grp Kick From", "Grp Ban From", and "Invite
To..." -- shows every group from the cached shortlist (see
group_mod_cache.py) that's relevant to whichever of those called it,
each with its own icon at the right edge (same trick as the player
list -- IconRowDelegate, since QListWidgetItem's .setIcon() only draws
on the left), and lets a mod pick one. The freshness recheck that
actually matters happens right after this closes, in main.py, not
here.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
)

from icon_row_delegate import IconRowDelegate, GROUP_ICON_ROLE, GROUP_ICON_LABELS_ROLE


class GroupPickerDialog(QDialog):
    def __init__(self, entries, icon_pixmaps=None, title="Choose a Group"):
        super().__init__()
        self.setObjectName("GroupPickerDialog")
        self.setWindowTitle(title)
        self.resize(360, 420)
        self.selected_entry = None
        icon_pixmaps = icon_pixmaps or {}

        layout = QVBoxLayout(self)

        hint = QLabel(
            "Groups you currently have moderation permission in, from the "
            "last scan. Picking one still double-checks your permission "
            "fresh before anything happens."
        )
        hint.setObjectName("groupPickerHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.group_list = QListWidget()
        self.group_list.setObjectName("groupPickerList")
        # Kept as an attribute, not a local variable, for the same
        # reason main.py keeps its own delegate reference -- PySide
        # would otherwise garbage-collect the Python wrapper out from
        # under the C++ side once __init__ returns.
        self._delegate = IconRowDelegate(self.group_list)
        self.group_list.setItemDelegate(self._delegate)
        for entry in entries:
            item = QListWidgetItem(entry.group_name)
            item.setData(Qt.UserRole, entry)
            pixmap = icon_pixmaps.get(entry.group_id)
            if pixmap:
                item.setData(GROUP_ICON_ROLE, pixmap)
                item.setData(GROUP_ICON_LABELS_ROLE, entry.group_name)
            self.group_list.addItem(item)
        if self.group_list.count():
            self.group_list.setCurrentRow(0)
        self.group_list.itemDoubleClicked.connect(lambda _item: self._confirm())
        layout.addWidget(self.group_list)

        button_row = QHBoxLayout()
        button_row.addStretch()

        cancel_button = QPushButton("Cancel")
        cancel_button.setObjectName("groupPickerCancelButton")
        cancel_button.setToolTip("Close without picking a group")
        cancel_button.clicked.connect(self.reject)
        button_row.addWidget(cancel_button)

        select_button = QPushButton("Select")
        select_button.setObjectName("groupPickerSelectButton")
        select_button.setToolTip("Use the selected group")
        select_button.clicked.connect(self._confirm)
        button_row.addWidget(select_button)

        layout.addLayout(button_row)

    def _confirm(self):
        item = self.group_list.currentItem()
        if item is None:
            return
        self.selected_entry = item.data(Qt.UserRole)
        self.accept()
