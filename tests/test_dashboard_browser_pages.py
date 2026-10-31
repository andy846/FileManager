"""Offscreen smoke tests for the dashboard and browser pages."""

import json
import os

from app.modules.dashboard.scanner import scan_folder


class _FakeQ:
    def __init__(self, path):
        self._path = str(path)

    def fileName(self):
        return self._path


class FakeSettings:
    def __init__(self, path):
        self.data = {}
        self.recent_data = {}
        self.q = _FakeQ(path)

    def option(self, name, default):
        return self.data.get(name, default)

    def set_option(self, name, value):
        self.data[name] = value

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


def test_dashboard_applies_scan_summary(app, sample_tree, tmp_path):
    from app.core.i18n import set_language
    from app.modules.dashboard.page import DashboardPage

    set_language("zh_TW")
    settings = FakeSettings(tmp_path / "settings.ini")
    page = DashboardPage(settings)
    try:
        summary = scan_folder(sample_tree)
        page._apply_summary(summary)
        assert page.summary is summary
        assert page.table.rowCount() == len(summary.top_files)
        assert "個檔案" in page.summary_label.text()
        assert "資料夾分析" in page.cleanup_source.text()
        assert "資料夾分析" in page.junk_hint.text()
        assert "{count}" not in page.junk_hint.text()
        assert "{count}" not in page.old_hint.text()
        assert "歷史累計" in page.dup_hint.text()
        page.on_theme_changed()
        assert page.folder.text() == summary.root
        other = tmp_path / "other"
        other.mkdir()
        page.folder.set_path(str(other))
        assert "尚未分析" in page.cleanup_source.text()
        page.folder.set_path(summary.root)
        page._render_drives([
            {
                "root": "C:\\", "display_name": "Windows (C:)",
                "kind": "fixed", "filesystem": "NTFS",
                "total": 1000, "used": 400, "free": 600, "error": "",
                "is_network": False, "is_extra": False,
            },
            {
                "root": "\\\\server\\share",
                "display_name": "share", "kind": "network",
                "filesystem": "NTFS", "unc": "\\\\server\\share",
                "total": 0, "used": 0, "free": 0,
                "error": "unavailable", "is_network": True,
                "is_extra": True,
            },
        ])
        assert page.disk_layout.count() == 2
        assert "網路 1" in page.disk_summary.text()
        # The summary is cached next to the fake settings file.
        page._on_completed(summary)
        assert os.path.isfile(tmp_path / "dashboard_cache.json")
    finally:
        page.request_stop()
        page.deleteLater()
        set_language("en")


def test_browser_page_navigates_and_saves_state(app, tmp_path):
    from app.core.i18n import set_language
    from app.modules.browser.page import BrowserPage

    set_language("zh_TW")
    settings = FakeSettings(tmp_path / "settings.ini")
    page = BrowserPage(settings)
    try:
        folder = tmp_path / "browse"
        folder.mkdir()
        (folder / "one.txt").write_text("hello", encoding="utf-8")
        page.apply_payload({"folder": str(folder)})
        tab = page.tabs.currentWidget()
        assert tab is not None
        assert tab.left.current_path == str(folder)
        assert page.tabs.count() == 1
        from PyQt6.QtCore import Qt

        assert tab.left.proxy.headerData(
            0, Qt.Orientation.Horizontal
        ) == "名稱"

        page._save_state()
        state = json.loads(settings.data["browser/state"])
        assert state["tabs"][0]["left"] == str(folder)

        page._toggle_hidden(True)
        assert page.show_hidden is True
        page._toggle_hidden(False)
        assert page.show_hidden is False

        # Closing a tab can be undone from the session's recent-tab stack.
        second = page._new_tab(str(folder), str(folder))
        assert page.tabs.count() == 2
        page._close_tab(page.tabs.indexOf(second))
        assert page.tabs.count() == 1
        page._restore_closed_tab()
        assert page.tabs.count() == 2
        assert page.tabs.currentWidget().left.current_path == str(folder)
    finally:
        page.request_stop()
        page.deleteLater()
        set_language("en")


def test_preview_text_and_binary(app, tmp_path):
    from app.modules.browser.preview import PreviewPanel

    panel = PreviewPanel()
    try:
        text_file = tmp_path / "notes.txt"
        text_file.write_text("hello preview", encoding="utf-8")
        panel.show_path(str(text_file))
        assert panel.stack.currentWidget() is panel.text_view
        assert "hello preview" in panel.text_view.toPlainText()

        binary = tmp_path / "data.bin"
        binary.write_bytes(b"\x00\x01\x02")
        panel.show_path(str(binary))
        assert panel.stack.currentWidget() is panel.message

        from PyQt6.QtGui import QColor, QImage

        image_path = tmp_path / "image.png"
        image = QImage(40, 30, QImage.Format.Format_RGB32)
        image.fill(QColor("#3366cc"))
        assert image.save(str(image_path))
        panel.show_path(str(image_path))
        assert panel.stack.currentWidget() is panel.image_scroll
    finally:
        panel.deleteLater()
