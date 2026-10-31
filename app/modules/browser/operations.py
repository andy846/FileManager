"""File operations used by the browser (copy, move, trash, dialogs)."""

import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QProgressBar, QPushButton, QTextEdit,
    QVBoxLayout,
)

from app.core.file_ops import is_within, unique_path
from app.core.i18n import tr
from app.core.transfer import DestinationExistsError, copy_file, move_file
from app.core.utils import (
    extended_path, format_size, normalize_path, short_path,
    strip_extended_path,
)
from app.core.workers import CancelledError, OperationControl


def _norm(path):
    return os.path.normcase(os.path.normpath(os.path.abspath(str(path))))


def _is_reparse(path):
    try:
        path = extended_path(path)
        if os.path.islink(path):
            return True
        attrs = getattr(os.stat(path), "st_file_attributes", 0)
        return bool(attrs & 0x400)  # FILE_ATTRIBUTE_REPARSE_POINT
    except OSError:
        return True


def build_plan(sources, dest_dir, control=None):
    """Expand files/folders into a list of directory and file operations."""
    dest_dir = normalize_path(os.path.abspath(str(dest_dir)))
    if not os.path.isdir(extended_path(dest_dir)):
        raise ValueError(f"目標資料夾不存在: {dest_dir}")

    plan = []
    source_dirs = set()
    for source in sources:
        source = normalize_path(os.path.abspath(str(source)))
        if not os.path.exists(extended_path(source)):
            raise ValueError(f"來源不存在: {source}")
        if _is_reparse(source):
            raise ValueError(f"不支援符號連結或重新解析點: {source}")
        if os.path.isdir(extended_path(source)):
            if is_within(dest_dir, source):
                raise ValueError("不能把資料夾複製或搬移到它自己裡面")
            name = os.path.basename(source.rstrip("\\/"))
            if not name:
                raise ValueError("不能直接操作磁碟根目錄")
            target_root = os.path.join(dest_dir, name)
            if _norm(target_root) == _norm(source):
                raise ValueError("來源與目標相同")
            source_dirs.add(source)
            plan.append({"kind": "dir", "src": source, "dst": target_root})
            for root, dirs, files in os.walk(extended_path(source)):
                root = strip_extended_path(root)
                if control is not None:
                    control.checkpoint()
                dirs[:] = [d for d in dirs
                           if not _is_reparse(os.path.join(root, d))]
                rel = os.path.relpath(root, source)
                if rel != ".":
                    source_dirs.add(root)
                for directory in dirs:
                    src_dir = os.path.join(root, directory)
                    source_dirs.add(src_dir)
                    plan.append({
                        "kind": "dir",
                        "src": src_dir,
                        "dst": os.path.join(target_root, rel, directory)
                        if rel != "." else os.path.join(target_root, directory),
                    })
                for filename in files:
                    if control is not None:
                        control.checkpoint()
                    src_file = os.path.join(root, filename)
                    if _is_reparse(src_file):
                        continue
                    try:
                        size = os.path.getsize(extended_path(src_file))
                    except OSError:
                        size = 0
                    rel_file = os.path.join(rel, filename) if rel != "." else filename
                    plan.append({
                        "kind": "file",
                        "src": src_file,
                        "dst": os.path.join(target_root, rel_file),
                        "size": size,
                    })
        else:
            target = os.path.join(dest_dir, os.path.basename(source))
            if _norm(source) == _norm(target):
                raise ValueError("來源與目標相同")
            plan.append({
                "kind": "file",
                "src": source,
                "dst": target,
                "size": os.path.getsize(extended_path(source)),
            })
    return plan, source_dirs


class FileOpsWorker(QThread):
    """Copy or move files/folders with progress, cancellation and verification."""

    progress = pyqtSignal(int, int, int, int, str)  # done, total, bytes, total bytes, current
    status = pyqtSignal(str)
    completed = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, operation, sources, dest_dir, conflict="skip",
                 verify=True, control=None, verify_mode=None, retries=1,
                 threads=4):
        super().__init__()
        self.operation = operation
        self.sources = list(sources)
        self.dest_dir = normalize_path(dest_dir)
        self.conflict = conflict
        self.verify = verify
        self.verify_mode = verify_mode or ("quick" if verify else "off")
        self.retries = max(0, int(retries or 0))
        self.threads = max(1, min(int(threads or 4), 16))
        self.control = control or OperationControl()

    def cancel(self):
        self.control.cancel()

    def _prepare_dest(self, entry, lock):
        dst = entry["dst"]
        with lock:
            if not os.path.exists(extended_path(dst)):
                return dst, False
            if self.conflict == "skip":
                return dst, True
            if self.conflict == "rename":
                return unique_path(dst), False
            return dst, False

    def _finish_move_source(self, source_dirs):
        for folder in sorted(
                source_dirs, key=lambda p: p.count(os.sep), reverse=True):
            try:
                os.rmdir(extended_path(folder))
            except OSError:
                pass

    def _process_file(self, entry, dest_lock):
        self.control.checkpoint()
        dst, skip = self._prepare_dest(entry, dest_lock)
        if skip:
            return "skipped", 0, ""
        if self.operation == "copy":
            try:
                copy_file(
                    entry["src"], dst, control=self.control,
                    verify=self.verify_mode, retries=self.retries,
                    conflict=self.conflict,
                )
            except DestinationExistsError:
                return "skipped", 0, "目標已存在"
        else:
            try:
                move_file(
                    entry["src"], dst, control=self.control,
                    verify=self.verify_mode, retries=self.retries,
                    conflict=self.conflict,
                )
            except DestinationExistsError:
                return "skipped", 0, "目標已存在"
        return "done", int(entry.get("size", 0) or 0), ""

    def run(self):
        started = time.time()
        summary = {
            "operation": self.operation,
            "done": 0,
            "skipped": 0,
            "failed": 0,
            "bytes": 0,
            "elapsed": 0.0,
            "errors": [],
            "cancelled": False,
        }
        try:
            self.status.emit("正在建立檔案清單...")
            plan, source_dirs = build_plan(
                self.sources, self.dest_dir, self.control
            )
            self.control.checkpoint()

            # Create the directory tree once on the worker thread.  The
            # actual file transfers then run in parallel.
            for entry in plan:
                if entry["kind"] != "dir":
                    continue
                self.control.checkpoint()
                try:
                    os.makedirs(
                        extended_path(entry["dst"]), exist_ok=True
                    )
                except OSError as exc:
                    summary["failed"] += 1
                    summary["errors"].append((entry["src"], str(exc)))

            files = [entry for entry in plan if entry["kind"] == "file"]
            files_total = len(files)
            bytes_total = sum(int(entry.get("size", 0) or 0)
                              for entry in files)
            done = 0
            moved_bytes = 0
            last_emit = 0.0
            cancelled = False

            if files:
                self.status.emit("正在複製檔案...")
                dest_lock = threading.Lock()
                pool = ThreadPoolExecutor(max_workers=self.threads)
                futures = {
                    pool.submit(self._process_file, entry, dest_lock): entry
                    for entry in files
                }
                try:
                    for future in as_completed(futures):
                        entry = futures[future]
                        if self.control.is_cancelled():
                            cancelled = True
                            for pending in futures:
                                pending.cancel()
                            break
                        try:
                            status, moved, error = future.result()
                        except CancelledError:
                            cancelled = True
                            for pending in futures:
                                pending.cancel()
                            break
                        except Exception as exc:
                            status, moved, error = "failed", 0, str(exc)

                        if status == "done":
                            summary["done"] += 1
                            summary["bytes"] += moved
                            moved_bytes += moved
                        elif status == "skipped":
                            summary["skipped"] += 1
                        else:
                            summary["failed"] += 1
                            summary["errors"].append(
                                (entry["src"], error)
                            )
                        done += 1
                        now = time.time()
                        if (now - last_emit >= 0.1
                                or done == files_total):
                            self.progress.emit(
                                done, files_total, moved_bytes,
                                bytes_total, short_path(entry["src"], 60),
                            )
                            last_emit = now
                finally:
                    pool.shutdown(wait=True, cancel_futures=True)

            if self.operation == "move":
                self._finish_move_source(source_dirs)
            summary["cancelled"] = (
                cancelled or self.control.is_cancelled()
            )
        except CancelledError:
            summary["cancelled"] = True
        except Exception as exc:  # planning failure
            self.failed.emit(str(exc))
            return
        summary["elapsed"] = time.time() - started
        self.completed.emit(summary)


class OperationDialog(QDialog):
    """Modeless progress dialog for a FileOpsWorker."""

    completed = pyqtSignal(object)

    def __init__(self, parent, operation, sources, dest_dir, conflict="skip",
                 verify=True, verify_mode=None, retries=1, threads=4):
        super().__init__(parent)
        self.setWindowTitle("複製檔案" if operation == "copy" else "搬移檔案")
        self.resize(560, 300)
        self.setModal(False)
        self.control = OperationControl()
        self.sources = list(sources)
        self.worker = FileOpsWorker(
            operation, sources, dest_dir, conflict=conflict,
            verify=verify, control=self.control, verify_mode=verify_mode,
            retries=retries, threads=threads,
        )

        layout = QVBoxLayout(self)
        self.heading = QLabel("")
        self.heading.setWordWrap(True)
        layout.addWidget(self.heading)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        layout.addWidget(self.progress)

        self.status = QLabel("準備中...")
        self.status.setProperty("role", "hint")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        self.details = QTextEdit()
        self.details.setReadOnly(True)
        self.details.setVisible(False)
        layout.addWidget(self.details, 1)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.clicked.connect(self._cancel)
        buttons.addWidget(self.cancel_btn)
        self.close_btn = QPushButton("關閉")
        self.close_btn.setEnabled(False)
        self.close_btn.clicked.connect(self.accept)
        buttons.addWidget(self.close_btn)
        layout.addLayout(buttons)

        self.worker.progress.connect(self._on_progress)
        self.worker.status.connect(self.status.setText)
        self.worker.completed.connect(self._on_completed)
        self.worker.failed.connect(self._on_failed)

    def start(self):
        total = len(self.sources)
        pairs = sum(1 for path in self.sources if os.path.isdir(path))
        source = (
            "正在複製 {total} 個項目（資料夾 {pairs} 個）至："
            if self.worker.operation == "copy"
            else "正在搬移 {total} 個項目（資料夾 {pairs} 個）至："
        )
        heading = tr(source, total=total, pairs=pairs)
        self.heading.setText(f"{heading}\n{self.worker.dest_dir}")
        self.worker.start()

    def _on_progress(self, done, total, moved, total_bytes, current):
        self.progress.setRange(0, max(1, total))
        self.progress.setValue(done)
        progress = tr(
            "{done}/{total} 個檔案 · {moved} / {total_bytes}",
            done=done, total=total,
            moved=format_size(moved),
            total_bytes=format_size(total_bytes),
        )
        self.status.setText(f"{progress}\n{current}")

    def _on_completed(self, summary):
        self.cancel_btn.setVisible(False)
        self.close_btn.setEnabled(True)
        self.progress.setRange(0, 1)
        self.progress.setValue(1)
        if summary.get("cancelled"):
            self.status.setText(tr(
                "已取消：完成 {done} · 跳過 {skipped} · 失敗 {failed}",
                done=summary["done"], skipped=summary["skipped"],
                failed=summary["failed"],
            ))
        else:
            elapsed = float(summary.get("elapsed", 0.0) or 0.0)
            self.status.setText(tr(
                "完成 {done} · 跳過 {skipped} · 失敗 {failed} · "
                "{size} · {elapsed}s",
                done=summary["done"], skipped=summary["skipped"],
                failed=summary["failed"],
                size=format_size(summary["bytes"]),
                elapsed=f"{elapsed:.1f}",
            ))
        errors = summary.get("errors") or []
        if errors:
            self.details.setVisible(True)
            self.details.setPlainText("\n".join(
                f"{path}\n  → {error}" for path, error in errors[:50]
            ))
        self.completed.emit(summary)

    def _on_failed(self, message):
        self.cancel_btn.setVisible(False)
        self.close_btn.setEnabled(True)
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.status.setText(tr("操作失敗：") + message)

    def _cancel(self):
        self.control.cancel()
        self.cancel_btn.setEnabled(False)
        self.status.setText("正在取消...")

    def closeEvent(self, event):  # noqa: N802 (Qt API)
        if self.worker.isRunning():
            self.control.cancel()
            self.worker.wait(5000)
            if self.worker.isRunning():
                event.ignore()
                return
        super().closeEvent(event)

    def request_stop(self):
        self.control.cancel()
        if self.worker.isRunning():
            self.worker.wait(5000)
