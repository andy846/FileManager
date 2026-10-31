"""Theme-aware inline SVG icons (Lucide-style line icons).

The app deliberately avoids emoji as structural icons: they render differently
across Windows versions and cannot follow the light/dark colour tokens.
"""

# ruff: noqa: E501

from PyQt6.QtCore import QByteArray, Qt
from PyQt6.QtGui import QIcon, QPainter, QPixmap
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtWidgets import QApplication

from app.core.theme import DARK, LIGHT

PATHS = {
    "dashboard": '<path d="M3 10.5 12 3l9 7.5"/><path d="M5 9.5V21h14V9.5"/><path d="M9 21v-7h6v7"/>',
    "browser": '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Z"/>',
    "search": '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>',
    "copy": '<rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2"/>',
    "move": '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Z"/><path d="M9 13h6"/><path d="m12 10 3 3-3 3"/>',
    "trash": '<path d="M3 6h18"/><path d="M8 6V4h8v2"/><path d="M19 6l-1 14H6L5 6"/><path d="M10 11v6M14 11v6"/>',
    "duplicates": '<rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2"/><path d="M11 14h6M14 11v6"/>',
    "rename": '<path d="M4 20h4L19 9l-4-4L4 16v4Z"/><path d="m14 6 4 4"/>',
    "compare": '<path d="M12 3v18"/><path d="M5 7h14"/><path d="m7 7-3 6h6Z"/><path d="m17 7-3 6h6Z"/>',
    "hash": '<path d="M4 9h16M4 15h16M10 3 8 21M16 3l-2 18"/>',
    "archive": '<rect x="3" y="4" width="18" height="5" rx="1"/><path d="M5 9v10a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V9"/><path d="M10 13h4"/>',
    "settings": '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1-2.8 2.8-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.6v.2h-4v-.2a1.7 1.7 0 0 0-1-1.6 1.7 1.7 0 0 0-1.9.3l-.1.1L4.2 17l.1-.1a1.7 1.7 0 0 0 .3-1.9 1.7 1.7 0 0 0-1.6-1H2.8v-4H3a1.7 1.7 0 0 0 1.6-1 1.7 1.7 0 0 0-.3-1.9L4.2 7 7 4.2l.1.1a1.7 1.7 0 0 0 1.9.3 1.7 1.7 0 0 0 1-1.6V2.8h4V3a1.7 1.7 0 0 0 1 1.6 1.7 1.7 0 0 0 1.9-.3l.1-.1L19.8 7l-.1.1a1.7 1.7 0 0 0-.3 1.9 1.7 1.7 0 0 0 1.6 1h.2v4H21a1.7 1.7 0 0 0-1.6 1Z"/>',
    "history": '<path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5"/><path d="M12 7v5l3 2"/>',
    "sun": '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
    "moon": '<path d="M21 12.8A9 9 0 1 1 11.2 3 7 7 0 0 0 21 12.8Z"/>',
    "task": '<rect x="4" y="3" width="16" height="18" rx="2"/><path d="m8 9 2 2 4-4"/><path d="M8 16h8"/>',
    "monitor": '<rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8M12 16v4"/>',
    "eye": '<path d="M2 12s3.5-6 10-6 10 6 10 6-3.5 6-10 6S2 12 2 12Z"/><circle cx="12" cy="12" r="2.5"/>',
    "star": '<path d="m12 3 2.8 5.7 6.2.9-4.5 4.4 1.1 6.2-5.6-3-5.6 3 1.1-6.2L3 9.6l6.2-.9L12 3Z"/>',
    "columns": '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M9 4v16M15 4v16"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "x": '<path d="M6 6l12 12M18 6 6 18"/>',
    "refresh": '<path d="M20 11a8 8 0 0 0-14-5L3 9"/><path d="M3 4v5h5"/><path d="M4 13a8 8 0 0 0 14 5l3-3"/><path d="M21 20v-5h-5"/>',
    "arrow-left": '<path d="M19 12H5"/><path d="m11 18-6-6 6-6"/>',
    "arrow-right": '<path d="M5 12h14"/><path d="m13 6 6 6-6 6"/>',
    "arrow-up": '<path d="M12 19V5"/><path d="m5 12 7-7 7 7"/>',
    "chevron-down": '<path d="m6 9 6 6 6-6"/>',
    "chevron-right": '<path d="m9 6 6 6-6 6"/>',
    "play": '<path d="m8 5 11 7-11 7Z"/>',
    "pause": '<path d="M8 5v14M16 5v14"/>',
    "stop": '<rect x="6" y="6" width="12" height="12" rx="1"/>',
    "folder-open": '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v1H3Z"/><path d="M3 10h18l-2 9H5Z"/>',
    "file": '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8Z"/><path d="M14 2v6h6"/>',
    "check": '<path d="m5 12 4 4L19 6"/>',
    "alert": '<path d="M12 3 2 21h20Z"/><path d="M12 9v5M12 18h.01"/>',
    "info": '<circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/>',
    "external": '<path d="M14 3h7v7"/><path d="M10 14 21 3"/><path d="M21 14v5a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5"/>',
    "more": '<circle cx="5" cy="12" r="1"/><circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/>',
    "list": '<path d="M8 6h13M8 12h13M8 18h13"/><path d="M3 6h.01M3 12h.01M3 18h.01"/>',
    "grid": '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
    "sync": '<path d="M20 7h-9a4 4 0 0 0-4 4v1"/><path d="m17 4 3 3-3 3"/><path d="M4 17h9a4 4 0 0 0 4-4v-1"/><path d="m7 20-3-3 3-3"/>',
    "download": '<path d="M12 3v12"/><path d="m7 10 5 5 5-5"/><path d="M4 19h16"/>',
    "upload": '<path d="M12 21V9"/><path d="m7 14 5-5 5 5"/><path d="M4 5h16"/>',
    "drive": '<rect x="3" y="5" width="18" height="6" rx="2"/><rect x="3" y="13" width="18" height="6" rx="2"/><path d="M7 8h.01M7 16h.01"/>',
    "filter": '<path d="M3 5h18l-7 8v6l-4 2v-8Z"/>',
    "lock": '<rect x="4" y="10" width="16" height="11" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3"/>',
}

_CACHE = {}


def _palette(theme):
    return DARK if theme == "dark" else LIGHT


def icon_color(theme, role="text"):
    palette = _palette(theme)
    return palette.get(role, palette["text"])


def get_icon(name, theme="dark", color=None, size=18):
    """Render a line icon with the current theme colour."""
    if name not in PATHS:
        name = "file"
    color = color or icon_color(theme)
    try:
        screen = QApplication.primaryScreen()
        dpr = screen.devicePixelRatio() if screen else 1.0
    except Exception:
        dpr = 1.0
    dpr = max(1.0, float(dpr))
    key = (name, color, int(size), dpr)
    cached = _CACHE.get(key)
    if cached is not None:
        return cached

    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
        f'fill="none" stroke="{color}" stroke-width="1.8" '
        f'stroke-linecap="round" stroke-linejoin="round">'
        f'{PATHS[name]}</svg>'
    )
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    pixel_size = max(1, int(size * dpr))
    pixmap = QPixmap(pixel_size, pixel_size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter)
    painter.end()
    pixmap.setDevicePixelRatio(dpr)
    icon = QIcon(pixmap)
    _CACHE[key] = icon
    return icon


def set_icon(widget, name, theme="dark", role="text", size=16):
    try:
        widget.setIcon(get_icon(name, theme, icon_color(theme, role), size))
        widget.setProperty("appIconName", name)
        widget.setProperty("appIconRole", role)
        widget.setProperty("appIconSize", size)
    except Exception:
        pass
    return widget


def refresh_icons(root, theme="dark"):
    """Re-render icons after a light/dark theme switch."""
    from PyQt6.QtWidgets import QAbstractButton

    for widget in root.findChildren(QAbstractButton):
        name = widget.property("appIconName")
        if not name:
            continue
        role = widget.property("appIconRole") or "text"
        size = int(widget.property("appIconSize") or 16)
        try:
            widget.setIcon(get_icon(name, theme, icon_color(theme, role), size))
        except Exception:
            pass
