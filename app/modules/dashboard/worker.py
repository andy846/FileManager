"""Background worker for dashboard folder analysis."""

from PyQt6.QtCore import QThread, pyqtSignal

from app.core.workers import CancelledError, OperationControl
from app.modules.dashboard.scanner import scan_folder


class DashboardScanWorker(QThread):
    """Run :func:`scan_folder` without blocking the UI."""

    progress = pyqtSignal(int, int, int)  # files, folders, bytes
    completed = pyqtSignal(object)  # ScanSummary, or None when cancelled
    failed = pyqtSignal(str)

    def __init__(self, folder, control=None):
        super().__init__()
        self.folder = folder
        self.control = control or OperationControl()

    def cancel(self):
        self.control.cancel()

    def run(self):
        try:
            summary = scan_folder(
                self.folder, control=self.control,
                progress=self.progress.emit, workers=4,
            )
            self.completed.emit(summary)
        except CancelledError:
            self.completed.emit(None)
        except Exception as exc:  # pragma: no cover - surfaced in the UI
            self.failed.emit(str(exc))
