"""Background worker for duplicate scanning and trash cleanup."""

from PyQt6.QtCore import pyqtSignal

from app.core.workers import BaseWorker, CancelledError
from app.modules.duplicates.scanner import find_duplicates
from app.modules.remover.deleter import delete_files


class DuplicatesWorker(BaseWorker):
    """Scans for duplicate files. Emits ``scan_complete`` with groups."""

    scan_progress = pyqtSignal(object)  # ScanProgress
    scan_complete = pyqtSignal(list)
    scan_cancelled = pyqtSignal()
    scan_failed = pyqtSignal(str)

    def __init__(self, control, folder, recursive=True, min_size=1,
                 exclude=None, ignore_hardlinks=True):
        super().__init__(control)
        self.folder = folder
        self.recursive = recursive
        self.min_size = min_size
        self.exclude = list(exclude or [])
        self.ignore_hardlinks = ignore_hardlinks

    def run(self):
        try:
            self.control.checkpoint()
            groups = find_duplicates(
                self.folder, self.recursive,
                progress_callback=self.scan_progress.emit,
                cancel_check=self.control.checkpoint,
                min_size=self.min_size,
                exclude=self.exclude,
                ignore_hardlinks=self.ignore_hardlinks,
            )
            if self.control.is_cancelled():
                self.scan_cancelled.emit()
            else:
                self.scan_complete.emit(groups)
        except CancelledError:
            self.scan_cancelled.emit()
        except Exception as exc:
            self.emit_log(f"掃描錯誤: {exc}")
            self.scan_failed.emit(str(exc))


class CleanupWorker(BaseWorker):
    """Sends selected duplicate files to the recycle bin in parallel."""

    cleanup_progress = pyqtSignal(int, int)
    cleanup_complete = pyqtSignal(list, list)  # deleted, failed

    def __init__(self, control, paths, threads=8):
        super().__init__(control)
        self.paths = paths
        self.threads = threads

    def run(self):
        deleted, failed = delete_files(
            self.paths,
            cancel_check=self.control.checkpoint,
            progress_callback=lambda done, total: self.cleanup_progress.emit(done, total),
            threads=self.threads,
        )
        self.cleanup_complete.emit(deleted, failed)
