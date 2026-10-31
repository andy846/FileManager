"""UI polish guardrails: icons, contrast and non-emoji navigation."""

from PyQt6.QtCore import QEvent, QObject
from PyQt6.QtWidgets import QWidget

from app.core.constants import MODULE_ICONS
from app.core.theme import DARK, LIGHT
from app.ui.icons import PATHS, get_icon


def _luminance(hex_color):
    value = hex_color.lstrip("#")
    channels = [int(value[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    channels = [
        channel / 12.92 if channel <= 0.04045
        else ((channel + 0.055) / 1.055) ** 2.4
        for channel in channels
    ]
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def _contrast(first, second):
    high, low = sorted(
        [_luminance(first), _luminance(second)], reverse=True
    )
    return (high + 0.05) / (low + 0.05)


def test_icons_render_and_navigation_is_not_emoji(app):
    icon = get_icon("dashboard", "dark", size=18)
    assert not icon.isNull()
    assert all(value in PATHS for value in MODULE_ICONS.values())
    for value in MODULE_ICONS.values():
        assert value.isascii()


def test_theme_text_contrast_meets_aa():
    for palette in (LIGHT, DARK):
        assert _contrast(palette["text"], palette["panel"]) >= 4.5
        assert _contrast(palette["text_hint"], palette["panel"]) >= 4.5
        assert _contrast(palette["primary_text"], palette["primary"]) >= 4.5
        assert _contrast(
            palette["danger_text"], palette["danger_fill"]
        ) >= 4.5
        assert _contrast(
            palette["danger_text"], palette["danger_hover"]
        ) >= 4.5
        assert _contrast(
            palette["primary_text"], palette["success_hover"]
        ) >= 4.5
        assert _contrast(palette["text_hint"], palette["bg"]) >= 4.5
        assert _contrast(
            palette["nav_group"], palette["panel_alt"]
        ) >= 4.5


def test_module_titles_have_no_emoji(app):
    from app.ui.main_window import MainWindow

    class _Q:
        def fileName(self):
            return "unused.ini"

        def sync(self):
            pass

    class _Settings:
        q = _Q()

        def option(self, name, default):
            return default

        def set_option(self, name, value):
            pass

        def value(self, name, default=None):
            return default

        def set_value(self, name, value):
            pass

        def recent(self, name):
            return []

        def remember_path(self, name, path):
            pass

        def save_geometry(self, data):
            pass

        def load_geometry(self):
            return None

    window = MainWindow(_Settings())
    try:
        for page in window.pages:
            assert page.title.isascii() or all(
                ord(char) < 0x1F000 for char in page.title
            )
    finally:
        window.close()


def test_startup_does_not_flash_top_level_widgets(app):
    """Parentless QLabel.setVisible() used to create short-lived top-level windows."""
    from PyQt6.QtTest import QTest

    from app.ui.main_window import MainWindow

    shown = []

    class ShowFilter(QObject):
        def eventFilter(self, obj, event):
            if (event.type() == QEvent.Type.Show and isinstance(obj, QWidget)
                    and obj.isWindow()):
                shown.append(type(obj).__name__)
            return False

    class _Q:
        def fileName(self):
            return "unused.ini"

        def sync(self):
            pass

    class _Settings:
        q = _Q()

        def option(self, name, default):
            return default

        def set_option(self, name, value):
            pass

        def value(self, name, default=None):
            return default

        def set_value(self, name, value):
            pass

        def recent(self, name):
            return []

        def remember_path(self, name, path):
            pass

        def save_geometry(self, data):
            pass

        def load_geometry(self):
            return None

    filter_object = ShowFilter()
    app.installEventFilter(filter_object)
    window = MainWindow(_Settings())
    try:
        window.show()
        QTest.qWait(200)
        assert shown == ["MainWindow"], shown
    finally:
        app.removeEventFilter(filter_object)
        window.close()

