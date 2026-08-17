"""
icon_row_delegate.py

Custom item delegate that draws the normal item text, plus zero or
more small icon pixmaps lined up at the RIGHT edge of the row.
Generic on purpose -- reused by two different lists:

- The player list: one icon per group a player belongs to that the
  logged-in user ALSO moderates (see group_mod_cache.py), not just the
  group hosting the current instance. Could be zero, one, or several.
- The "Grp Kick From"/"Grp Ban From" group pickers (group_picker_
  dialog.py): exactly one icon per row, that group's own.

Was player_list_delegate.py / PlayerListDelegate before the group
pickers needed the same right-edge-icon trick -- renamed rather than
duplicated, since paint() below never actually had anything
player-specific in it to begin with.

--------------------------------------------------------------------------
BEGINNER NOTES:

- QListWidgetItem only supports .setIcon(), which draws at the LEFT edge
  of a row -- there's no built-in way to put an icon at the end next to
  the text. An "item delegate" is Qt's mechanism for taking over exactly
  how a row gets drawn, which is what lets us add that.

- We store the icon(s) to draw as custom per-row DATA on the item,
  under a role number (GROUP_ICON_ROLE) that doesn't collide with any
  of Qt's built-in roles -- either a single QPixmap, a list of them, or
  None/empty for no icons. GROUP_ICON_LABELS_ROLE holds the matching
  group name(s), same shape (single string or a list, index-aligned
  with the icons), used for the per-icon hover tooltip -- optional; an
  icon with no label just falls back to the row's own tooltip, same as
  before this existed. Callers set this (main.py's _refresh_list() for
  the player list, group_picker_dialog.py for the group picker); this
  file only reads it back out, paints it, and answers tooltip queries.

- paint() first shrinks the drawing rect so the DEFAULT text painting
  (super().paint()) doesn't draw underneath where the icons will go,
  then draws them right-to-left from the row's right edge, which ends
  up placing them in the ORIGINAL list order reading left-to-right.
  _icon_rects() computes exactly where each one landed, in that same
  order -- paint() and helpEvent() both call it, so the drawn
  positions and the hit-testing for tooltips can never drift apart.

- helpEvent() is Qt's mechanism for a delegate to answer its own
  QEvent.ToolTip queries instead of the item's plain .setToolTip()
  text -- checked here for whichever icon rect the cursor is actually
  over, falling back to the item's normal tooltip everywhere else on
  the row.
--------------------------------------------------------------------------
"""

from PySide6.QtCore import Qt, QRect, QEvent
from PySide6.QtWidgets import QStyledItemDelegate, QStyleOptionViewItem, QToolTip
from PySide6.QtGui import QPixmap

# Role numbers Qt hasn't already claimed, used to attach icon data to a
# specific row's QListWidgetItem via item.setData(ROLE, ...).
GROUP_ICON_ROLE = Qt.UserRole + 10
GROUP_ICON_LABELS_ROLE = Qt.UserRole + 11


class IconRowDelegate(QStyledItemDelegate):
    ICON_SIZE = 16
    ICON_MARGIN = 6
    ICON_GAP = 2  # between adjacent icons, when there's more than one

    def _icons_and_labels(self, index):
        raw_icons = index.data(GROUP_ICON_ROLE)
        if isinstance(raw_icons, QPixmap):
            raw_icons = [raw_icons]  # single-icon callers shouldn't have to remember to wrap it in a list
        icons = [p for p in (raw_icons or []) if isinstance(p, QPixmap) and not p.isNull()]

        raw_labels = index.data(GROUP_ICON_LABELS_ROLE)
        if isinstance(raw_labels, str):
            raw_labels = [raw_labels]
        labels = list(raw_labels or [])
        # Pad/truncate to match icons 1:1 -- a caller that set icons
        # without labels (or fewer labels than icons) just gets no
        # tooltip for the unlabeled ones, not a crash.
        labels = (labels + [None] * len(icons))[:len(icons)]

        return icons, labels

    def _icon_rects(self, original_rect: QRect, count: int) -> list:
        """Rects for `count` icons, right-to-left from the row's right
        edge -- index 0 is the LEFTMOST icon (original list order),
        matching how paint() below places them."""
        y = original_rect.top() + (original_rect.height() - self.ICON_SIZE) // 2
        rects = []
        x = original_rect.right() - self.ICON_MARGIN - self.ICON_SIZE
        for _ in range(count):
            rects.append(QRect(x, y, self.ICON_SIZE, self.ICON_SIZE))
            x -= (self.ICON_SIZE + self.ICON_GAP)
        rects.reverse()  # was built right-to-left; reverse so index 0 = leftmost icon
        return rects

    def paint(self, painter, option, index):
        icons, _labels = self._icons_and_labels(index)
        original_rect = QRect(option.rect)

        if icons:
            # Shrink a COPY of the option so default text painting leaves
            # room on the right for the icons -- never mutate the option
            # Qt handed us.
            option = QStyleOptionViewItem(option)
            reserved = len(icons) * self.ICON_SIZE + (len(icons) - 1) * self.ICON_GAP + self.ICON_MARGIN * 2
            option.rect = QRect(
                original_rect.left(), original_rect.top(),
                max(original_rect.width() - reserved, 0), original_rect.height(),
            )

        super().paint(painter, option, index)

        if not icons:
            return

        for pixmap, rect in zip(icons, self._icon_rects(original_rect, len(icons))):
            scaled = pixmap.scaled(self.ICON_SIZE, self.ICON_SIZE, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            painter.drawPixmap(rect.topLeft(), scaled)

    def helpEvent(self, event, view, option, index):
        if event.type() == QEvent.ToolTip:
            icons, labels = self._icons_and_labels(index)
            if icons:
                for rect, label in zip(self._icon_rects(QRect(option.rect), len(icons)), labels):
                    if label and rect.contains(event.pos()):
                        QToolTip.showText(event.globalPos(), label, view)
                        return True
        return super().helpEvent(event, view, option, index)
