"""Safety tests for shutdown discovery and scanner error reporting."""

import threading

from PyQt6.QtCore import QThread
from PyQt6.QtWidgets import QWidget


class _Settings:
    def __init__(self, path):
        self.q = _FakeQ(path)

    def option(self, name, default=None):
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


class _FakeQ:
    def __init__(self, path):
        self._path = str(path)

    def fileName(self):
        return self._path

    def sync(self):
        pass


class _SlowThread(QThread):
    def __init__(self):
        super().__init__()
        self._stop = threading.Event()

    def run(self):
        self._stop.wait(30)

    def stop(self):
        self._stop.set()


def test_running_threads_finds_dialog_owned_unparented_worker(app, tmp_path):
    from app.ui.main_window import MainWindow

    window = MainWindow(_Settings(tmp_path / "settings.ini"))
    thread = _SlowThread()
    try:
        dialog = QWidget(window)
        dialog.worker = thread  # unparented QThread stored on a dialog
        thread.start()
        assert thread.isRunning()
        assert thread in window._running_threads()
    finally:
        thread.stop()
        thread.wait(5000)
        window.close()


def test_remover_scan_reports_unreadable_directories(tmp_path, monkeypatch):
    import app.modules.remover.scanner as scanner_module

    def fake_walk(_path, onerror=None):
        error = OSError("access denied")
        error.filename = str(tmp_path / "locked")
        if onerror is not None:
            onerror(error)
        return iter(())

    monkeypatch.setattr(scanner_module.os, "walk", fake_walk)
    errors = []
    results = scanner_module.scan_files(
        str(tmp_path), [], {},
        on_error=lambda path, error: errors.append((path, error)),
    )
    assert results == []
    assert len(errors) == 1
    assert errors[0][0] == str(tmp_path / "locked")
