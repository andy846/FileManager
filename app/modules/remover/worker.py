"""Background workers for the Remover module."""

from PyQt6.QtCore import QThread, pyqtSignal

from app.core.workers import CancelledError
from app.modules.remover.scanner import scan_files
from app.modules.remover.deleter import delete_files


class ScannerWorker(QThread):
    progress = pyqtSignal(str)
    file_found = pyqtSignal(object)
    scan_complete = pyqtSignal(list)
    scan_warnings = pyqtSignal(int)
    error = pyqtSignal(str)

    def __init__(self, folder, extensions, filters, recursive=True):
        super().__init__()
        self.folder = folder
        self.extensions = extensions
        self.filters = filters
        self.recursive = recursive
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def _check(self):
        if self._cancelled:
            raise CancelledError("掃描已取消")

    def run(self):
        try:
            scan_errors = []
            results = scan_files(
                self.folder, self.extensions, self.filters,
                recursive=self.recursive,
                progress_callback=lambda c: self.progress.emit(f"已掃描 {c} 個項目"),
                file_found_callback=lambda info: self.file_found.emit(info),
                cancel_check=self._check,
                on_error=lambda path, error: scan_errors.append((path, error)),
            )
            self.scan_complete.emit(results)
            self.scan_warnings.emit(len(scan_errors))
        except CancelledError:
            self.scan_complete.emit([])
        except Exception as exc:
            self.error.emit(str(exc))


class DeletionWorker(QThread):
    progress = pyqtSignal(int, int)
    file_deleted = pyqtSignal(str)
    file_failed = pyqtSignal(str, str)
    delete_complete = pyqtSignal(list, list, list)

    def __init__(self, files, permanent=False, threads=None):
        super().__init__()
        self.files = files
        self.permanent = permanent
        self.threads = threads
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def _check(self):
        if self._cancelled:
            raise CancelledError("刪除已取消")

    def run(self):
        deleted, failed, cancelled = delete_files(
            self.files,
            cancel_check=self._check,
            progress_callback=lambda d, t: self.progress.emit(d, t),
            file_deleted_callback=lambda p: self.file_deleted.emit(p),
            file_failed_callback=lambda p, e: self.file_failed.emit(p, e),
            permanent=self.permanent,
            threads=self.threads,
            include_cancelled=True,
        )
        self.delete_complete.emit(deleted, failed, cancelled)
