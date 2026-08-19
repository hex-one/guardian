"""
wallpaper_utils.py

Turns a chosen image file into a blurred, darkened QPixmap sized to fit
the player list -- diffused and darkened on purpose, per what was asked
for, so player names/badges/rank colors stay readable on top of it
instead of competing with a sharp, bright background image. Ambiance
shouldn't drown out the signal.

--------------------------------------------------------------------------
BEGINNER NOTES:

- Four modes, chosen in Config (WALLPAPER_MODES below is the exact list
  the dropdown offers): "fill" (scale to cover the area, crop the
  overflow -- the original, default behavior, no distortion but crops
  edges), "stretch" (scale to exactly fit, ignoring aspect ratio -- no
  cropping, but can distort), "center" (native size -- or scaled DOWN,
  keeping aspect ratio, only if it wouldn't otherwise fit -- centered,
  never upscaled past its real resolution), "tile" (native size,
  repeated across the whole area). _build_canvas() below is where each
  mode actually gets composited, BEFORE the blur/darken pass runs --
  that pass is identical for all four, only what's underneath it
  differs.

- QGraphicsBlurEffect is Qt's built-in blur -- rather than pulling in an
  extra image-processing library (like Pillow) just for this, we use
  Qt's own graphics effects: put the composited canvas in a tiny
  throwaway QGraphicsScene, apply the blur effect, then "render" that
  scene into a plain QPixmap we can actually use as a widget background.

- The darken step afterward is just painting a semi-transparent black
  rectangle on top -- simple, but does the job.

- This only processes the image at whatever SIZE you ask for -- it does
  NOT re-process automatically if the window gets resized later (that
  would mean reprocessing on every resize event, which is more complexity
  than this needed for a first pass). Re-applying from Config after a
  resize is the workaround for now if the crop looks off.
--------------------------------------------------------------------------
"""

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QRectF, QSize
from PySide6.QtGui import QPixmap, QPainter, QColor
from PySide6.QtWidgets import QGraphicsScene, QGraphicsPixmapItem, QGraphicsBlurEffect

# Where the processed (blurred/darkened/sized) wallpaper gets written so it
# can be referenced by path from a QSS background-image -- see
# save_wallpaper_cache() below for why this exists instead of just handing
# main.py the in-memory QPixmap.
WALLPAPER_CACHE_FILE = Path.home() / ".ascended_guardian" / "wallpaper_cache.png"

# (value, label) pairs, in the order Config's dropdown shows them.
WALLPAPER_MODES = [
    ("fill", "Fill (crop to cover)"),
    ("stretch", "Stretch (exact fit)"),
    ("center", "Center (actual size)"),
    ("tile", "Tile (repeat)"),
]
DEFAULT_WALLPAPER_MODE = "fill"


def _build_canvas(source: QPixmap, target_size: QSize, mode: str) -> QPixmap:
    """The pre-blur composite: `source` placed into a target_size canvas
    according to `mode`. Never distorts UNLESS mode is literally
    "stretch" -- that one's the whole point of offering it."""
    canvas = QPixmap(target_size)
    canvas.fill(Qt.black)
    painter = QPainter(canvas)

    if mode == "stretch":
        scaled = source.scaled(target_size, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        painter.drawPixmap(0, 0, scaled)

    elif mode == "center":
        if source.width() > target_size.width() or source.height() > target_size.height():
            draw_pixmap = source.scaled(target_size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        else:
            draw_pixmap = source  # smaller than the area -- shown at its real size, never upscaled
        x = (target_size.width() - draw_pixmap.width()) // 2
        y = (target_size.height() - draw_pixmap.height()) // 2
        painter.drawPixmap(x, y, draw_pixmap)

    elif mode == "tile":
        # Native size, repeated -- composited here (not left to QSS's own
        # background-repeat) specifically so the blur/darken pass below
        # runs on the WHOLE canvas at once. Blurring one small tile and
        # then repeating it would leave hard seams at every tile edge;
        # blurring the already-tiled canvas blends across them instead.
        tile_w, tile_h = source.width(), source.height()
        if tile_w > 0 and tile_h > 0:
            for y in range(0, target_size.height(), tile_h):
                for x in range(0, target_size.width(), tile_w):
                    painter.drawPixmap(x, y, source)

    else:  # "fill" -- scale to cover, crop the center overflow
        scaled = source.scaled(target_size, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
        x = max((scaled.width() - target_size.width()) // 2, 0)
        y = max((scaled.height() - target_size.height()) // 2, 0)
        cropped = scaled.copy(x, y, target_size.width(), target_size.height())
        painter.drawPixmap(0, 0, cropped)

    painter.end()
    return canvas


def build_wallpaper(image_path: str, target_size: QSize, mode: str = DEFAULT_WALLPAPER_MODE,
                     blur_radius: float = 10.0, darken_alpha: int = 150) -> Optional[QPixmap]:
    """
    Returns a QPixmap of exactly `target_size`, composited per `mode`
    (see WALLPAPER_MODES / _build_canvas above), blurred, and darkened.
    Returns None if the image can't be loaded -- a bad wallpaper choice
    should never crash the app, just result in no wallpaper.
    """
    if not image_path:
        return None

    source = QPixmap(image_path)
    if source.isNull():
        return None

    canvas = _build_canvas(source, target_size, mode)

    # Blur via a throwaway graphics scene.
    scene = QGraphicsScene()
    item = QGraphicsPixmapItem(canvas)
    blur = QGraphicsBlurEffect()
    blur.setBlurRadius(blur_radius)
    item.setGraphicsEffect(blur)
    scene.addItem(item)

    blurred = QPixmap(target_size)
    blurred.fill(Qt.transparent)
    painter = QPainter(blurred)
    scene.render(painter, QRectF(0, 0, target_size.width(), target_size.height()))

    # Darken on top, in the same paint pass.
    painter.fillRect(QRectF(0, 0, target_size.width(), target_size.height()), QColor(0, 0, 0, darken_alpha))
    painter.end()

    return blurred


def save_wallpaper_cache(pixmap: QPixmap) -> Optional[str]:
    """
    Writes the already-processed wallpaper to disk and returns its path
    as a forward-slash string, ready to drop straight into a QSS
    background-image: url(...) declaration (QSS url() needs forward
    slashes -- Windows' native backslashes break its parser). Returns
    None if the save fails, same "cosmetic failure, never crash" contract
    as build_wallpaper() returning None on a bad source image.

    Why a file on disk instead of handing main.py the QPixmap directly:
    the app's global style.qss already claims #playerList's background
    for the app-wide dark theme, and Qt always lets a style sheet's own
    background win over a QPalette brush set in code -- setting the
    palette (the previous approach) silently painted right over the
    wallpaper. A per-widget QSS background-image, applied via that
    widget's own setStyleSheet(), overrides the app-wide sheet for that
    one property, which a QPalette brush cannot reliably do once any
    style sheet is in play.
    """
    WALLPAPER_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not pixmap.save(str(WALLPAPER_CACHE_FILE), "PNG"):
        return None
    return WALLPAPER_CACHE_FILE.as_posix()
