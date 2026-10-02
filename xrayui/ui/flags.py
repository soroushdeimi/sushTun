"""Country flags as crisp, rounded pixmaps, rendered once per size.

The bundled 4x3 SVGs are drawn with QSvgRenderer straight at the screen's
device pixel ratio, so they stay sharp on HiDPI; a hairline edge keeps white
flags (Japan, Finland) from dissolving into a light background.
"""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QGuiApplication, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtSvg import QSvgRenderer

from ..core import geo_exit

FLAG_W, FLAG_H = 20, 15
_RADIUS = 3.0

_cache: dict[tuple, QPixmap] = {}
_icons: dict[int, QIcon] = {}


def _device_ratio() -> float:
    screen = QGuiApplication.primaryScreen()
    return screen.devicePixelRatio() if screen else 1.0


def flag_pixmap(code: str | None, width: int = FLAG_W, height: int = FLAG_H) -> QPixmap | None:
    code = geo_exit.normalize(code)
    if not code:
        return None
    dpr = _device_ratio()
    key = (code, width, height, dpr)
    cached = _cache.get(key)
    if cached is not None:
        return cached

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
