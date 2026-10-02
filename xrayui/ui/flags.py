"""Country flags as crisp, rounded pixmaps, rendered once per size.

A flag is one country emoji (U+1F1E6 + the two letters), drawn with the
system's colour emoji font, so it needs no asset of its own and stays sharp at
any size. Windows' Segoe UI Emoji holds no flag glyphs and would draw the two
letters instead, so there the bundled 4x3 SVGs are drawn with QSvgRenderer at
the screen's device pixel ratio; a hairline edge keeps white flags (Japan,
Finland) from dissolving into a light background.
"""
from __future__ import annotations

from functools import lru_cache

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontDatabase,
    QGuiApplication,
    QIcon,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRawFont,
)
from PySide6.QtSvg import QSvgRenderer

from ..core import geo_exit

FLAG_W, FLAG_H = 20, 15
_RADIUS = 3.0
_REGIONAL_A = 0x1F1E6
_EMOJI_FAMILIES = ("Apple Color Emoji", "Segoe UI Emoji", "Noto Color Emoji",
                   "Twemoji Mozilla", "Noto Emoji", "OpenMoji", "JoyPixels")

_cache: dict[tuple, QPixmap] = {}
_icons: dict[int, QIcon] = {}


def _device_ratio() -> float:
    screen = QGuiApplication.primaryScreen()
    return screen.devicePixelRatio() if screen else 1.0


def flag_emoji(code: str | None) -> str:
    """A two-letter country code as its flag emoji, e.g. "de" -> the German one.

    Empty when the code is not a country the app has a name for.
    """
    code = geo_exit.normalize(code)
    if not code:
        return ""
    return "".join(chr(_REGIONAL_A + ord(c) - ord("a")) for c in code)


@lru_cache(maxsize=1)
def _emoji_family() -> str:
    """The first installed family that really has flags, else "".

    Windows ships Segoe UI Emoji, which has the letters but not the flag, so
    the family has to be asked, not assumed.
    """
    installed = set(QFontDatabase.families())
    for family in _EMOJI_FAMILIES:
        if family not in installed:
            continue
        raw = QRawFont.fromFont(QFont(family, 16))
        if raw.isValid() and raw.supportsCharacter(_REGIONAL_A):
            return family
    return ""


@lru_cache(maxsize=8)
def _ink_ratio(family: str) -> tuple[float, float]:
    """How much of a font pixel the flag's ink really covers, width then height.

    A bitmap emoji font reports a cell with room around the flag, so the font
    size that fits the cell leaves a visible gap inside the box. Measured once
    at a large size, the ink is what decides the size we ask for.
    """
    sample = QPixmap(192, 192)
    sample.fill(Qt.transparent)
    painter = QPainter(sample)
    painter.setFont(QFont(family, 128))
    painter.drawText(sample.rect(), Qt.AlignCenter, "\U0001F1E6\U0001F1E6")
    painter.end()
    image = sample.toImage()
    x0 = y0 = 1 << 20
    x1 = y1 = -1
    for y in range(image.height()):
        for x in range(image.width()):
            if image.pixelColor(x, y).alpha() > 8:
                x0, y0 = min(x0, x), min(y0, y)
                x1, y1 = max(x1, x), max(y1, y)
    if x1 < x0 or y1 < y0:  # no ink at all: this font draws nothing
        return (1.0, 1.0)
    return ((x1 - x0 + 1) / 128.0, (y1 - y0 + 1) / 128.0)


def _fit_emoji_font(text: str, width: int, height: int) -> QFont | None:
    """The biggest pixel size of the emoji font whose flag fills the box."""
    family = _emoji_family()
    if not family:
        return None
    ratio_w, ratio_h = _ink_ratio(family)
    largest = int(max(width / ratio_w, height / ratio_h)) + 1
    for size in range(largest, 6, -1):
        if size * ratio_w <= width and size * ratio_h <= height:
            return QFont(family, size)
    return QFont(family, 8)


def _emoji_pixmap(code: str, text: str, width: int, height: int,
                  dpr: float) -> QPixmap | None:
    font = _fit_emoji_font(text, width, height)
    if font is None:
        return None
    pix = QPixmap(round(width * dpr), round(height * dpr))
    pix.setDevicePixelRatio(dpr)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setFont(font)
    p.drawText(pix.rect(), Qt.AlignCenter, text)
    p.end()
    return pix



def flag_pixmap(code: str | None, width: int = FLAG_W, height: int = FLAG_H) -> QPixmap | None:
    code = geo_exit.normalize(code)
    if not code:
        return None
    dpr = _device_ratio()
    key = (code, width, height, dpr)
    cached = _cache.get(key)
    if cached is not None:
        return cached

    text = flag_emoji(code)
    pix = _emoji_pixmap(code, text, width, height, dpr)
    if pix is not None:
        _cache[key] = pix
        return pix

    renderer = QSvgRenderer(str(geo_exit.flag_path(code)))

    if not renderer.isValid():
        return None
    pix = QPixmap(round(width * dpr), round(height * dpr))
    pix.setDevicePixelRatio(dpr)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
    rect = QRectF(0, 0, width, height)
    clip = QPainterPath()
    clip.addRoundedRect(rect, _RADIUS, _RADIUS)
    p.setClipPath(clip)
    renderer.render(p, rect)
    p.setClipping(False)
    edge = QPen(QColor(0, 0, 0, 46))
    edge.setWidthF(1.0)
    p.setPen(edge)
    p.setBrush(Qt.NoBrush)
    inset = rect.adjusted(0.5, 0.5, -0.5, -0.5)
    p.drawRoundedRect(inset, _RADIUS - 0.5, _RADIUS - 0.5)
    p.end()
    _cache[key] = pix
    return pix


def flag_icon(code: str | None) -> QIcon | None:
    pix = flag_pixmap(code)
    if pix is None:
        return None
    icon = _icons.get(id(pix))
    if icon is None:
        icon = _icons[id(pix)] = QIcon(pix)
    return icon
