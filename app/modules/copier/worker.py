"""Background worker that performs copy or move operations."""

import os
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

from PyQt6.QtCore import pyqtSignal

from app.core.workers import BaseWorker, CancelledError
from app.core.utils import extended_path, send_to_trash
from app.core.models import STATUS_DONE, STATUS_SKIPPED, STATUS_FAILED
from app.core.constants import STATS_INTERVAL
from app.core.transfer import (
    DestinationExistsError, copy_file, move_file,
)
from app.modules.copier.scanner import build_tasks


class ScanWorker(BaseWorker):
    """Builds the copy/move task list off the UI thread."""

    tasks_ready = pyqtSignal(list)
    scan_failed = pyqtSignal(str)

    def __init__(self, control, source, target, mode, options):
        super().__init__(control)
        self.source = source
        self.target = target
        self.mode = mode
        self.options = options

    def run(self):
        try:
            self.control.checkpoint()
            tasks = build_tasks(
                self.source, self.target, self.mode, self.options,
                cancel_check=self.control.checkpoint,
            )
            self.tasks_ready.emit(tasks)
        except CancelledError:
            self.tasks_ready.emit([])
        except Exception as exc:
            self.scan_failed.emit(str(exc))


class TransferWorker(BaseWorker):
    """Copy or move files with threading, pause/cancel and verification."""

    task_updated = pyqtSignal(object)
    run_finished = pyqtSignal(bool, object)

    def __init__(self, control, tasks, options, operation="copy"):
        super().__init__(control)
        self.tasks = list(tasks)
        self.options = options
        self.operation = operation  # "copy" or "move"

    def _process(self, task, bytes_lock, counts):
        try:
            self.control.wait_if_paused()
            self.control.checkpoint()

            dst = task.dst
            mode = self.options.get("conflict_mode", "skip")
            # Cheap pre-check keeps the table honest for the common case;
            # the authoritative decision is re-evaluated at commit time.
            if mode == "skip" and os.path.lexists(extended_path(dst)):
                task.status = STATUS_SKIPPED
                task.error = "目標已存在"
                return

            backup_overwrite = None
            if mode == "overwrite" and self.options.get(
                    "to_trash_on_overwrite", False):
                def backup_overwrite(path):
                    ok, err = send_to_trash(path)
                    if not ok:
                        raise RuntimeError(
                            f"無法備份原檔至資源回收筒，已拒絕覆寫: "
                            f"{path} ({err})"
                        )

            def on_commit(final_dst):
                task.dst = final_dst

            verify = self.options.get(
                "verify_mode", self.options.get("verify", "quick")
            )
            retries = self.options.get("retries", 1)
            preserve = self.options.get("preserve_metadata", True)
            if self.operation == "copy":
                copy_file(
                    task.src, dst, control=self.control, verify=verify,
                    retries=retries, preserve_metadata=preserve,
                    conflict=mode, backup_overwrite=backup_overwrite,
                    on_commit=on_commit,
                )
            else:  # move
                move_file(
                    task.src, dst, control=self.control, verify=verify,
                    retries=retries, preserve_metadata=preserve,
                    conflict=mode, backup_overwrite=backup_overwrite,
                    on_commit=on_commit,
                )

            task.status = STATUS_DONE
            with bytes_lock:
                counts["bytes"] += task.size
        except CancelledError:
            raise
        except DestinationExistsError:
            task.status = STATUS_SKIPPED
            task.error = "目標已存在"
        except Exception as exc:
            task.status = STATUS_FAILED
            task.error = str(exc)

    def run(self):
        total = len(self.tasks)
        threads = max(1, min(self.options.get("threads", 4), 16))
        bytes_lock = threading.Lock()
        counts = {"done": 0, "skipped": 0, "failed": 0,
                  "cancelled": 0, "bytes": 0}

        start = time.time()
        last_emit = 0.0
        try:
            with ThreadPoolExecutor(max_workers=threads) as pool:
                futures = {pool.submit(self._process, t, bytes_lock, counts): t
                           for t in self.tasks}
                done_count = 0
                for fut in as_completed(futures):
                    task = futures[fut]
                    try:
                        fut.result()
                    except CancelledError:
                        task.status = STATUS_FAILED
                        task.error = "已取消"
                        counts["cancelled"] += 1
                    except Exception as exc:
                        task.status = STATUS_FAILED
                        task.error = str(exc)
                        counts["failed"] += 1
                    else:
                        if task.status == STATUS_DONE:
                            counts["done"] += 1
                        elif task.status == STATUS_SKIPPED:
                            counts["skipped"] += 1
                        else:
                            counts["failed"] += 1
                    done_count += 1
                    self.task_updated.emit(task)
                    self.progress_changed.emit(done_count, total)

                    now = time.time()
                    if now - last_emit >= STATS_INTERVAL:
                        elapsed = max(now - start, 0.001)
                        speed = counts["bytes"] / elapsed
                        remain = total - done_count
                        rate = done_count / elapsed if elapsed else 0
                        eta = remain / rate if rate else 0
                        self.stats_changed.emit(speed, eta, counts["bytes"])
                        last_emit = now

            elapsed = time.time() - start
            # Emit final stats so speed/ETA are accurate at completion.
            speed = counts["bytes"] / max(elapsed, 0.001)
            rate = done_count / elapsed if elapsed else 0
            eta = (total - done_count) / rate if rate else 0
            self.stats_changed.emit(speed, eta, counts["bytes"])
            cancelled = self.control.is_cancelled()
            summary = {
                "done": counts["done"],
                "skipped": counts["skipped"],
                "failed": counts["failed"],
                "cancelled": counts["cancelled"],
                "bytes": counts["bytes"],
                "elapsed": elapsed,
                "speed": speed,
            }
            self.run_finished.emit(cancelled, summary)
        except Exception as exc:
            self.emit_log(f"執行緒錯誤: {exc}")
            self.run_finished.emit(self.control.is_cancelled(), counts)
