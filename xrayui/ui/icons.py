"""Stroke-style SVG icons for the sidebar UI, rendered via QtSvg and tinted
to the palette. Path data is copied from the mockup at 16x16, stroke-width
1.6, round caps/joins -- the same look as the mockup's inline <svg> glyphs.
"""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

# Each entry is the <svg> body (paths/shapes only, no wrapper) at a 16x16
# viewBox, taken from the mockup verbatim.
_PATHS: dict[str, str] = {
    "servers": (
        '<rect x="2.5" y="3" width="11" height="4" rx="1"/>'
        '<rect x="2.5" y="9" width="11" height="4" rx="1"/>'
        '<path d="M5 5h.01M5 11h.01"/>'
    ),
    "subscriptions": '<path d="M3 4h10M3 8h10M3 12h6"/>',
    "routing": (
        '<circle cx="8" cy="8" r="5.5"/>'
        '<path d="M2.5 8h11M8 2.5c1.8 1.6 2.6 3.4 2.6 5.5S9.8 11.9 8 13.5'
        'M8 2.5C6.2 4.1 5.4 5.9 5.4 8s.8 3.9 2.6 5.5"/>'
    ),
    "dns": (
        '<path d="M8 2v12M4 5h7.5l1.5 1.5L11.5 8H4zM12 9H4.5L3 10.5 4.5 12H12z"/>'
    ),
    "activity": '<path d="M2 8.5h2.5l1.5-4 2.5 7 1.5-3H14"/>',
    "hotspot": (
        '<path d="M2.5 6.5a8 8 0 0 1 11 0M4.5 8.8a5 5 0 0 1 7 0'
        'M6.6 11a2 2 0 0 1 2.8 0"/>'
    ),
    "settings": (
        '<circle cx="8" cy="8" r="2.2"/>'
        '<path d="M8 1.8v1.6M8 12.6v1.6M1.8 8h1.6M12.6 8h1.6'
        'M3.6 3.6l1.1 1.1M11.3 11.3l1.1 1.1M3.6 12.4l1.1-1.1M11.3 4.7l1.1-1.1"/>'
    ),
    "chevron-down": '<path d="M5 6.5 8 9.5l3-3"/>',
    "chevron-right": '<path d="m6 4 4 4-4 4"/>',
    "search": '<circle cx="7" cy="7" r="4.2"/><path d="m10.2 10.2 3 3"/>',
    "anti-filter": '<path d="M6 3 3 8l3 5M10 3l3 5-3 5"/>',
    "low-usage": '<path d="M3 13c0-6 4-9 10-10-.5 6-3.5 10-10 10zM3 13l5-5"/>',
    "connected": (
        '<path d="M8 1.8 13 3.6v4c0 3.1-2.1 5.4-5 6.6C5.1 13 3 10.7 3 7.6v-4z"/>'
        '<path d="m5.8 8 1.6 1.6L10.4 6.4"/>'
    ),
    "edit": '<path d="M11 2.5 13.5 5 5.5 13H3v-2.5z"/>',
    "refresh": (
        '<path d="M13 8A5 5 0 1 1 11.5 4.3M13 2v3.5h-3.5"/>'
    ),
    "close": '<path d="M4 4l8 8M12 4l-8 8"/>',
    "up": '<path d="M4 10l4-4 4 4"/>',
    "down": '<path d="M4 6l4 4 4-4"/>',
    "test": '<path d="M9 2 4 9h4l-1 5 5-7H8z"/>',
    "check": '<path d="M3.5 8.5 6.5 11.5 12.5 5.5"/>',
}

_cache: dict[tuple[str, str, int], QIcon] = {}


def _svg(name: str, color: str) -> str:
    body = _PATHS[name]
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" '
        f'fill="none" stroke="{color}" stroke-width="1.6" '
        f'stroke-linecap="round" stroke-linejoin="round">{body}</svg>'
    )


def icon(name: str, color: str = "#f5f5f7", size: int = 16) -> QIcon:
    """A tinted QIcon for `name` (see _PATHS), cached by (name, color, size)."""
    key = (name, color, size)
    cached = _cache.get(key)
    if cached is not None:
        return cached
    renderer = QSvgRenderer(_svg(name, color).encode("utf-8"))
    pixmap = QPixmap(QSize(size, size))
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    result = QIcon(pixmap)
    _cache[key] = result
    return result
