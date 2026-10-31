"""Background worker for duplicate scanning and trash cleanup."""

from PyQt6.QtCore import pyqtSignal

from app.core.workers import BaseWorker, CancelledError
from app.modules.duplicates.scanner import find_duplicates
from app.core.utils import send_to_trash


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
        import concurrent.futures

        deleted, failed = [], []
        done = 0
        total = len(self.paths)
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.threads) as pool:
            futs = {pool.submit(send_to_trash, p): p for p in self.paths}
            try:
                for fut in concurrent.futures.as_completed(futs):
                    path = futs[fut]
                    self.control.checkpoint()
                    ok, err = fut.result()
                    if ok:
                        deleted.append(path)
                    else:
                        failed.append((path, err))
                    done += 1
                    self.cleanup_progress.emit(done, total)
            except CancelledError:
                self.cleanup_complete.emit(deleted, failed)
                return
        self.cleanup_complete.emit(deleted, failed)
