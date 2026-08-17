"""
glow.py

Every button here breathes a little -- purple, red, amber, green, blue,
blurple, same color language the whole UI speaks, because even a click
deserves to mean something. Qt Style Sheets don't know box-shadow (some
things never got better after the LAN-party era, apparently), so the
actual glow is a QGraphicsDropShadowEffect, hand-wired to brighten the
instant your cursor finds it -- like a CRT waking up. Small thing.
Still worth doing right. Presence matters, even in a hover state.
"""

from PySide6.QtCore import QObject, QEvent
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QGraphicsDropShadowEffect, QWidget

# Same hex values as style.qss's accent colors, so the glow always
# matches the button's own border color.
PRIMARY = "#b98af0"
DANGER = "#ff5577"
WARNING = "#ffb703"
SUCCESS = "#3ddc97"
INFO = "#4fa3e3"
DISCORD = "#5865f2"


class _GlowHoverFilter(QObject):
    def __init__(self, effect: QGraphicsDropShadowEffect, color: QColor,
                 base_blur: int, hover_blur: int, base_alpha: int, hover_alpha: int):
        super().__init__(effect)
        self._effect = effect
        self._color = color
        self._base_blur = base_blur
        self._hover_blur = hover_blur
        self._base_alpha = base_alpha
        self._hover_alpha = hover_alpha

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Enter:
            self._effect.setBlurRadius(self._hover_blur)
            self._color.setAlpha(self._hover_alpha)
            self._effect.setColor(self._color)
        elif event.type() == QEvent.Leave:
            self._effect.setBlurRadius(self._base_blur)
            self._color.setAlpha(self._base_alpha)
            self._effect.setColor(self._color)
        return False  # never swallow the event -- QPushButton still needs it


def apply_glow(widget: QWidget, color: str = PRIMARY,
                base_blur: int = 16, hover_blur: int = 32,
                base_alpha: int = 90, hover_alpha: int = 210):
    """
    Attaches a soft drop-shadow glow in `color` to `widget`, e.g. a
    QPushButton, that brightens/widens on hover. Safe to call once per
    widget -- a widget can only carry one QGraphicsDropShadowEffect, and
    this owns both the effect and its hover filter off the widget itself
    so nothing needs to be kept alive by the caller.
    """
    qcolor = QColor(color)
    qcolor.setAlpha(base_alpha)

    effect = QGraphicsDropShadowEffect(widget)
    effect.setBlurRadius(base_blur)
    effect.setOffset(0, 0)
    effect.setColor(qcolor)
    widget.setGraphicsEffect(effect)

    hover_filter = _GlowHoverFilter(effect, qcolor, base_blur, hover_blur, base_alpha, hover_alpha)
    widget.installEventFilter(hover_filter)
