"""Application entry point for the unified File Management System."""

import os
import sys

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QFont, QIcon

from app.core.i18n import (
    LANGUAGE_EN, Localizer, install_qt_translations, language, set_language,
)
from app.core.settings import AppSettings
from app.ui.main_window import MainWindow


def _icon_path():
    """Find the icon both in development and in a PyInstaller onedir build."""
    if getattr(sys, "frozen", False):
        roots = [
            getattr(sys, "_MEIPASS", ""),
            os.path.dirname(sys.executable),
            os.path.join(os.path.dirname(sys.executable), "_internal"),
        ]
        for root in roots:
            if not root:
                continue
            candidate = os.path.join(root, "assets", "app_icon.ico")
            if os.path.isfile(candidate):
                return candidate
    return os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "assets", "app_icon.ico"
    )


def _set_windows_app_id():
    if not sys.platform.startswith("win"):
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "FileManager.FileManager.2"
        )
    except Exception:
        pass


def main():
    _set_windows_app_id()
    app = QApplication(sys.argv)
    app.setApplicationName("FileManager")

    settings = AppSettings()
    set_language(settings.option("language", "en"))
    install_qt_translations(app)

    icon = QIcon(_icon_path())
    if not icon.isNull():
        app.setWindowIcon(icon)

    family = "Segoe UI" if language() == LANGUAGE_EN else "Microsoft JhengHei"
    font = QFont(family, 10)
    font.setStyleHint(QFont.StyleHint.SansSerif)
    app.setFont(font)

    window = MainWindow(settings)
    if not icon.isNull():
        window.setWindowIcon(icon)
    localizer = None
    if language() == LANGUAGE_EN:
        localizer = Localizer(app, window)
        localizer.translate_all()
    app._localizer = localizer
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
