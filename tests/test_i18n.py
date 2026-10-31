"""Localization and application icon guardrails."""

import json
import os

from PyQt6.QtGui import QIcon
from PyQt6.QtTest import QTest

from app.core.i18n import DEFAULT_LANGUAGE, set_language, tr
from app.core.constants import MODULE_COPY, MODULE_DASHBOARD


class _Q:
    def fileName(self):
        return "unused.ini"

    def sync(self):
        pass


class _Settings:
    def __init__(self):
        self.q = _Q()
        self.data = {}
        self.recent_data = {}
        self.geometry = None

    def option(self, name, default):
        return self.data.get(name, default)

    def set_option(self, name, value):
        self.data[name] = value

    def set_options(self, values):
        self.data.update(values)

    def value(self, name, default=None):
        return self.data.get(name, default)

    def set_value(self, name, value):
        self.data[name] = value

    def recent(self, name):
        return list(self.recent_data.get(name, []))

    def remember_path(self, name, path):
        paths = self.recent_data.setdefault(name, [])
        if path in paths:
            paths.remove(path)
        paths.insert(0, path)

    def save_geometry(self, data):
        self.geometry = data

    def load_geometry(self):
        return None


def test_english_is_default_and_catalog_has_no_duplicate_keys():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(root, "assets", "i18n", "en.json")
    pairs = []
    with open(path, encoding="utf-8") as handle:
        json.load(
            handle,
            object_pairs_hook=lambda items: pairs.extend(items) or dict(items),
        )
    assert len({key for key, _value in pairs}) == len(pairs)
    assert DEFAULT_LANGUAGE == "en"
    set_language("en")
    assert tr("儀表板") == "Dashboard"
    assert tr("1 個檔案") == "1 file"
    assert tr("C:\\temp\\file.txt") == "C:\\temp\\file.txt"
    assert tr("Y:/folder/file.txt") == "Y:/folder/file.txt"
    set_language("zh_TW")
    assert tr("儀表板") == "儀表板"
    set_language("en")


def test_english_localizer_translates_shell(app):
    from app.core.i18n import Localizer
    from app.ui.main_window import MainWindow

    set_language("en")
    window = MainWindow(_Settings())
    localizer = Localizer(app, window)
    try:
        window.show()
        localizer.translate_all()
        QTest.qWait(40)
        localizer.translate_all()
        assert window.windowTitle() == "FileManager v2.1.0"
        assert window.nav_items[MODULE_DASHBOARD].text(0) == "Dashboard"
        assert window.nav_items[MODULE_COPY].text(0) == "Batch copy / move"
        assert window.collapse_btn.text() == "Collapse sidebar"
        assert window.task_btn.text() == "Tasks"
        assert window._status_label.text() == "Ready"
        assert window.nav.topLevelItem(0).text(0) == "Workspace"
        # A transient widget can disappear between Show and the queued
        # localization pass; that must not abort the app.
        from PyQt6.QtWidgets import QLabel

        transient = QLabel("暫時標籤")
        transient.deleteLater()
        QTest.qWait(10)
        localizer._translate_tree(transient)
        # The Chinese language remains available after a restart.
        set_language("zh_TW")
        assert window.collapse_btn.text() == "Collapse sidebar"
    finally:
        localizer.timer.stop()
        app.removeEventFilter(localizer)
        window.close()
        set_language("zh_TW")


def test_chinese_mode_keeps_source_strings(app):
    from app.ui.main_window import MainWindow

    set_language("zh_TW")
    window = MainWindow(_Settings())
    try:
        assert window.collapse_btn.text() == "收起側邊欄"
        assert window.nav_items[MODULE_DASHBOARD].text(0) == "儀表板"
    finally:
        window.close()
        set_language("en")


def test_retry_spinbox_suffix_is_translated(app):
    from app.modules.settings.page import SettingsPage

    set_language("en")
    page = SettingsPage(_Settings(), None)
    try:
        assert tr(" 次") == " times"
        assert page.retries.suffix() == " times"
    finally:
        page.deleteLater()


def test_localizer_translates_spinbox_suffix(app):
    from PyQt6.QtWidgets import QSpinBox

    from app.core.i18n import Localizer

    set_language("en")
    box = QSpinBox()
    box.setSuffix(" 次")
    localizer = Localizer(app, box)
    try:
        localizer.translate_all()
        assert box.suffix() == " times"
    finally:
        localizer.timer.stop()
        app.removeEventFilter(localizer)
        box.deleteLater()


def test_language_setting_is_migrated(app):
    from app.core.settings import AppSettings

    class FakeQ:
        def __init__(self):
            self.data = {}

        def contains(self, key):
            return key in self.data

        def value(self, key, default=None):
            return self.data.get(key, default)

        def setValue(self, key, value):
            self.data[key] = value

        def sync(self):
            pass

    settings = object.__new__(AppSettings)
    settings.q = FakeQ()
    settings.migrate()
    assert settings.option("language", "en") == "en"


def test_settings_language_switch_is_persisted(app, monkeypatch, tmp_path):
    from PyQt6.QtCore import QSettings
    from PyQt6.QtWidgets import QMessageBox

    from app.core.settings import AppSettings
    from app.modules.settings.page import SettingsPage

    settings = object.__new__(AppSettings)
    settings.q = QSettings(
        str(tmp_path / "settings.ini"), QSettings.Format.IniFormat
    )
    messages = []
    monkeypatch.setattr(
        QMessageBox, "information",
        lambda *args: messages.append(args[2] if len(args) > 2 else ""),
    )
    page = SettingsPage(settings, None)
    try:
        index = page.language_combo.findData("zh_TW")
        page.language_combo.setCurrentIndex(index)
        page._save()
        assert settings.option("language", "en") == "zh_TW"
        assert any("restart" in message.lower() for message in messages)
    finally:
        page.deleteLater()
        settings.q.clear()


def test_icon_asset_has_multiple_sizes(app):
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    icon = QIcon(os.path.join(root, "assets", "app_icon.ico"))
    assert not icon.isNull()
    sizes = {(size.width(), size.height()) for size in icon.availableSizes()}
    assert (16, 16) in sizes
    assert (32, 32) in sizes
    assert (256, 256) in sizes


def test_frozen_icon_path_prefers_meipass(monkeypatch, tmp_path):
    import main

    assets = tmp_path / "assets"
    assets.mkdir()
    icon = assets / "app_icon.ico"
    icon.write_bytes(b"icon")
    monkeypatch.setattr(main.sys, "frozen", True, raising=False)
    monkeypatch.setattr(main.sys, "_MEIPASS", str(tmp_path), raising=False)
    monkeypatch.setattr(
        main.sys, "executable", str(tmp_path / "FileManager.exe"), raising=False
    )
    assert main._icon_path() == str(icon)


def test_packaged_spec_includes_localization_assets():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, "FileManager.spec"), encoding="utf-8") as handle:
        spec = handle.read()
    assert "assets/i18n" in spec
