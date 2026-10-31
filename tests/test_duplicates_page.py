"""Regression tests for the duplicates page tree and scan progress."""

import time


def test_scan_progress_switches_to_real_percentage(app):
    from app.core.settings import AppSettings
    from app.modules.duplicates.page import DuplicatesPage
    from app.modules.duplicates.scanner import ScanProgress

    page = DuplicatesPage(AppSettings(), None)
    try:
        page.scanning = True
        page._scan_started = time.monotonic()
        page._on_scan_progress(ScanProgress("scan", 25, 0, 25))
        assert page.progress.maximum() == 0
        assert "25" in page.stats.text()

        page._on_scan_progress(ScanProgress("quick", 5, 10, 100))
        assert page.progress.maximum() == 1000
        assert page.progress.value() == 500

        page._on_scan_progress(ScanProgress("full", 512, 1024, 100))
        assert page.progress.maximum() == 1000
        assert page.progress.value() == 500
    finally:
        page._finish_scan_ui()
        page.deleteLater()


def test_scan_failure_restores_controls(app, monkeypatch):
    from PyQt6.QtWidgets import QMessageBox

    from app.core.i18n import set_language
    from app.core.settings import AppSettings
    from app.modules.duplicates.page import DuplicatesPage

    set_language("en")
    messages = []
    monkeypatch.setattr(
        QMessageBox, "warning", lambda *args: messages.append(args)
    )
    page = DuplicatesPage(AppSettings(), None)
    try:
        page.scanning = True
        page.progress.setVisible(True)
        page.scan_btn.setEnabled(False)
        page.stop_btn.setEnabled(True)
        page._on_scan_failed("boom")
        assert page.scan_btn.isEnabled()
        assert not page.stop_btn.isEnabled()
        assert page.progress.isHidden()
        assert page.stats.text() == "Search failed"
        assert messages
    finally:
        page.deleteLater()


def test_cleanup_rebuild_keeps_tree_in_sync(app, tmp_path, monkeypatch):
    from PyQt6.QtWidgets import QMessageBox

    from app.core.models import DuplicateGroup, FileInfo
    from app.core.settings import AppSettings
    from app.modules.duplicates.page import DuplicatesPage

    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    page = DuplicatesPage(AppSettings(), None)

    g1 = DuplicateGroup(hash="a", size=10, files=[
        FileInfo(path=str(tmp_path / f"a{i}.txt"), size=10) for i in range(3)])
    g2 = DuplicateGroup(hash="b", size=20, files=[
        FileInfo(path=str(tmp_path / f"b{i}.txt"), size=20) for i in range(2)])
    page.groups = [g1, g2]
    page._populate()
    assert page.tree.topLevelItemCount() == 2

    # Delete two of g1's three files: g1 is no longer a duplicate group.
    deleted = [g1.files[1].path, g1.files[2].path]
    page._size_map = {}
    page._on_clean_complete(deleted, [])

    assert len(page.groups) == 1
    assert page.tree.topLevelItemCount() == len(page.groups)
    # These used to raise / mis-index when the tree had a stale 1-child row.
    page._auto_select("extra")
    assert page._selected_paths()
