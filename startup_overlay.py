"""
startup_overlay.py

A checklist overlay covering the main window while it's still getting
ready -- same idea as Ascended STT's loading screen (show the actual
work happening, step by step, rather than a blank window or a fake
spinner), just built as native Qt widgets instead of HTML/CSS/JS,
since Guardian has no web layer to put one in.

Sits as a plain child widget of QuickModWindow's CENTRAL widget --
covering the whole content area (status line, instance list, footer,
everything below the menu bar), not the menu bar itself, which stays
usable throughout. Sizing this to player_list's own geometry instead
(covering just the list) was tried and reverted -- it pushed the main
window wider. main.py's resizeEvent override keeps it matched to the
central widget's size; not a separate window, so closing/moving/
resizing behaves like part of the same window because it is one.

--------------------------------------------------------------------------
BEGINNER NOTES:

- mark_step(step_id, status, message=None) is the only thing callers
  need: "pending" (default, greyed out), "active" (currently running,
  pulsing dot), "done" (checkmark), or "error" (X, with an optional
  reason). Same four states and the same ○ ● ✓ ✕ icons Ascended STT's
  checklist uses, so the two apps read the same way at a glance.

- Each checklist row fades in on its own, staggered a beat after the
  one above it (start_reveal_animation, called once the overlay is
  actually showing) -- a QGraphicsOpacityEffect per row driven by a
  QPropertyAnimation, since QSS alone can't animate opacity the way
  real CSS can. Purely a presentation flourish; mark_step() still
  works normally underneath a row that hasn't finished fading in yet,
  it just won't be VISIBLE doing so until its turn comes.

- reveal_and_hide() is the finale: shows "Let's GO!!!" (cycling
  through the full RGB hue range while it's up, not a fixed color),
  holds it long enough to actually see a few hues go by, then hides
  the whole overlay. Nothing below re-shows it -- a fresh one only
  exists because a fresh QuickModWindow got built (sign-out/sign-in,
  or a relaunch).
--------------------------------------------------------------------------
"""

import math

from PySide6.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QGraphicsOpacityEffect

STARTUP_STEPS = [
    ("settings_loaded", "Loading settings"),
    ("log_finding", "Finding VRChat log file"),
    ("temp_bans_checked", "Checking temp bans"),
    ("watchlist_synced", "Syncing watchlist"),
    ("ready", "Ready"),
]

_STATUS_COLORS = {
    "pending": "#777777",
    "active": "#b4aee6",
    "done": "#7fd97f",
    "error": "#ff8080",
}
_STATUS_ICONS = {
    "pending": "○",
    "active": "●",
    "done": "✓",
    "error": "✕",
}


class _RainbowLabel(QLabel):
    """A label whose text color continuously cycles through the full
    hue wheel (plus a gentle opacity pulse from the same timer tick)
    while running -- the native-Qt equivalent of Ascended STT's
    "Let's GO!!!" CSS hue-rotate animation, since QSS has no filter
    property to lean on the way real CSS does."""

    HUE_STEP_DEGREES = 3
    TICK_MS = 30

    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self._hue = 0
        self._pulse_phase = 0.0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)

    def start_cycling(self):
        self._hue = 0
        self._pulse_phase = 0.0
        self._timer.start(self.TICK_MS)
        self._tick()

    def stop_cycling(self):
        self._timer.stop()

    def _tick(self):
        self._hue = (self._hue + self.HUE_STEP_DEGREES) % 360
        self._pulse_phase += 0.25
        color = QColor.fromHsv(self._hue, 255, 255)
        alpha = 0.55 + 0.45 * ((math.sin(self._pulse_phase) + 1) / 2)
        self.setStyleSheet(
            f"color: rgba({color.red()}, {color.green()}, {color.blue()}, {alpha:.2f});"
            f"font-size: 22px; font-weight: 800; letter-spacing: 0.5px;"
        )


class StartupOverlay(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("startupOverlay")
        self.setStyleSheet("#startupOverlay { background-color: #000000; }")
        self._row_widgets = {}  # step_id -> (icon_label, text_label, message_label)

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)
        layout.setSpacing(16)

        title = QLabel("Starting up...")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("color: #b4aee6; font-size: 15px; font-weight: 700;")
        layout.addWidget(title)

        checklist = QVBoxLayout()
        checklist.setSpacing(8)
        self._row_animations = []  # kept alive here -- a QPropertyAnimation with no other reference gets GC'd mid-flight
        for step_id, label_text in STARTUP_STEPS:
            row_widget = QWidget()
            row = QHBoxLayout(row_widget)
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(8)

            icon = QLabel(_STATUS_ICONS["pending"])
            icon.setFixedWidth(16)
            icon.setAlignment(Qt.AlignCenter)
            icon.setStyleSheet(f"color: {_STATUS_COLORS['pending']}; font-size: 13px;")
            row.addWidget(icon)

            text = QLabel(label_text)
            text.setStyleSheet(f"color: {_STATUS_COLORS['pending']}; font-size: 12px;")
            row.addWidget(text)

            message = QLabel("")
            message.setStyleSheet("color: #999999; font-size: 10px;")
            row.addWidget(message)

            row.addStretch()

            # Opacity effects apply to a WIDGET, not a layout -- wrapping
            # each row in its own QWidget is what makes a per-row fade
            # possible at all, not just one effect for the whole list.
            opacity_effect = QGraphicsOpacityEffect(row_widget)
            opacity_effect.setOpacity(0.0)
            row_widget.setGraphicsEffect(opacity_effect)

            checklist.addWidget(row_widget)
            self._row_widgets[step_id] = (icon, text, message, opacity_effect)

        checklist_wrapper = QWidget()
        checklist_wrapper.setLayout(checklist)
        checklist_wrapper.setFixedWidth(240)
        layout.addWidget(checklist_wrapper, alignment=Qt.AlignCenter)

        self._lets_go = _RainbowLabel("LET'S GO!!!")
        self._lets_go.setAlignment(Qt.AlignCenter)
        self._lets_go.hide()
        layout.addWidget(self._lets_go)

    def mark_step(self, step_id, status, message=None):
        row = self._row_widgets.get(step_id)
        if not row:
            return
        icon, text, message_label, _opacity_effect = row
        color = _STATUS_COLORS.get(status, _STATUS_COLORS["pending"])
        icon.setText(_STATUS_ICONS.get(status, _STATUS_ICONS["pending"]))
        icon.setStyleSheet(f"color: {color}; font-size: 13px;")
        text.setStyleSheet(f"color: {color}; font-size: 12px;")
        message_label.setText(f"- {message}" if message else "")

    def start_reveal_animation(self, stagger_ms=150, fade_ms=450):
        """Fades each row in one after another, top to bottom -- a beat
        of `stagger_ms` between each row STARTING its fade, not between
        one finishing and the next beginning, so by the last row it's
        been rippling down the list rather than crawling. Call once,
        right after the overlay is actually visible."""
        delay = 0
        for step_id, _label_text in STARTUP_STEPS:
            _icon, _text, _message, opacity_effect = self._row_widgets[step_id]
            anim = QPropertyAnimation(opacity_effect, b"opacity", self)
            anim.setDuration(fade_ms)
            anim.setStartValue(0.0)
            anim.setEndValue(1.0)
            anim.setEasingCurve(QEasingCurve.OutCubic)
            self._row_animations.append(anim)
            QTimer.singleShot(delay, anim.start)
            delay += stagger_ms

    def reveal_and_hide(self, delay_ms=3000):
        self._lets_go.show()
        self._lets_go.start_cycling()
        QTimer.singleShot(delay_ms, self._finish_reveal)

    def _finish_reveal(self):
        self._lets_go.stop_cycling()
        self.hide()
