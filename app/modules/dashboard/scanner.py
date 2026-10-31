"""Folder scanning and aggregation for the dashboard.

The scanner is deliberately UI-free so it can be unit-tested with temporary
directories. All heavy I/O happens in ``DashboardScanWorker`` on a QThread.
"""

import datetime
import heapq
import os
import stat
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from typing import Dict, List

from app.core.utils import (
    CATEGORY_ORDER, extended_path, file_category, file_extension,
    is_unc_path, normalize_path, strip_extended_path,
)


AGE_BUCKETS = ["week", "month", "quarter", "year", "older"]
AGE_LABELS = {
    "week": "7 天內",
    "month": "7～30 天",
    "quarter": "30～90 天",
    "year": "90～365 天",
    "older": "一年以上",
}

JUNK_EXTENSIONS = {
    "tmp", "temp", "bak", "old", "log", "cache", "dmp", "chk", "part",
}
LARGE_FILE_BYTES = 100 * 1024 * 1024
OLD_SECONDS = 365 * 86400


@dataclass
class ScanSummary:
    """Serialisable result of one folder analysis."""

    root: str = ""
    scanned_at: str = ""
    duration: float = 0.0
    files: int = 0
    folders: int = 0
    total_size: int = 0
    categories: Dict[str, int] = field(default_factory=dict)
    extensions: List[dict] = field(default_factory=list)
    top_files: List[dict] = field(default_factory=list)
    top_folders: List[dict] = field(default_factory=list)
    age_buckets: Dict[str, int] = field(default_factory=dict)
    errors: int = 0
    cancelled: bool = False
    junk_files: int = 0
    junk_size: int = 0
    old_large_files: int = 0
    old_large_size: int = 0

    def as_dict(self):
        return {
            "root": self.root,
            "scanned_at": self.scanned_at,
            "duration": self.duration,
            "files": self.files,
            "folders": self.folders,
            "total_size": self.total_size,
            "categories": dict(self.categories),
            "extensions": list(self.extensions),
            "top_files": list(self.top_files),
            "top_folders": list(self.top_folders),
            "age_buckets": dict(self.age_buckets),
            "errors": self.errors,
            "cancelled": self.cancelled,
            "junk_files": self.junk_files,
            "junk_size": self.junk_size,
            "old_large_files": self.old_large_files,
            "old_large_size": self.old_large_size,
        }

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, dict):
            return cls()
        summary = cls(
            root=str(data.get("root", "")),
            scanned_at=str(data.get("scanned_at", "")),
            duration=float(data.get("duration", 0.0) or 0.0),
            files=int(data.get("files", 0) or 0),
            folders=int(data.get("folders", 0) or 0),
            total_size=int(data.get("total_size", 0) or 0),
            categories=dict(data.get("categories", {}) or {}),
            extensions=list(data.get("extensions", []) or []),
            top_files=list(data.get("top_files", []) or []),
            top_folders=list(data.get("top_folders", []) or []),
            age_buckets=dict(data.get("age_buckets", {}) or {}),
            errors=int(data.get("errors", 0) or 0),
            cancelled=bool(data.get("cancelled", False)),
            junk_files=int(data.get("junk_files", 0) or 0),
            junk_size=int(data.get("junk_size", 0) or 0),
            old_large_files=int(data.get("old_large_files", 0) or 0),
            old_large_size=int(data.get("old_large_size", 0) or 0),
        )
        for key in CATEGORY_ORDER:
            summary.categories.setdefault(key, 0)
        for key in AGE_BUCKETS:
            summary.age_buckets.setdefault(key, 0)
        return summary


def _is_reparse_dir(entry):
    """Return True for junctions/symlinks so scanning cannot loop forever."""
    try:
        st = entry.stat(follow_symlinks=False)
    except OSError:
        return True
    attrs = getattr(st, "st_file_attributes", 0)
    if attrs & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0):
        return True
    return entry.is_symlink()


def _age_key(age_seconds):
    if age_seconds < 7 * 86400:
        return "week"
    if age_seconds < 30 * 86400:
        return "month"
    if age_seconds < 90 * 86400:
        return "quarter"
    if age_seconds < 365 * 86400:
        return "year"
    return "older"


def _scan_directory(directory, control=None):
    """Read one directory and return ``(subdirs, files, errors)``.

    ``files`` contains ``(path, name, size, mtime)`` tuples.  Keeping the
    per-entry stat result avoids a second filesystem round-trip in the
    aggregation thread.
    """
    subdirs = []
    files = []
    errors = 0
    checked = 0
    try:
        entries = os.scandir(extended_path(directory))
    except OSError:
        return subdirs, files, 1
    with entries:
        for entry in entries:
            checked += 1
            if control is not None and checked % 200 == 0:
                control.wait_if_paused()
                control.checkpoint()
            try:
                if entry.is_dir(follow_symlinks=False):
                    if _is_reparse_dir(entry):
                        continue
                    subdirs.append(normalize_path(
                        strip_extended_path(entry.path)
                    ))
                    continue
                if not entry.is_file(follow_symlinks=False):
                    continue
                st = entry.stat(follow_symlinks=False)
            except OSError:
                errors += 1
                continue
            files.append((
                normalize_path(strip_extended_path(entry.path)),
                entry.name,
                int(getattr(st, "st_size", 0) or 0),
                float(getattr(st, "st_mtime", 0.0) or 0.0),
            ))
    return subdirs, files, errors


def scan_folder(root, control=None, progress=None, top_n=20,
                top_extensions=12, workers=4):
    """Recursively scan *root* and return a :class:`ScanSummary`.

    Directory reads and stat calls run in a small thread pool.  Aggregation
    stays on the calling thread so the summary and progress callbacks never
    need locks.  Network shares use fewer workers to avoid overloading the
    link. ``progress`` is called as ``progress(files, folders, total_size)``
    roughly every 250 files.
    """
    root = normalize_path(os.path.abspath(str(root)))
    if not os.path.isdir(extended_path(root)):
        raise ValueError(f"資料夾不存在: {root}")

    workers = max(1, min(int(workers or 4), 8))
    if is_unc_path(root):
        workers = min(workers, 2)

    started = time.monotonic()
    now = time.time()
    summary = ScanSummary(
        root=root,
        scanned_at=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        categories={key: 0 for key in CATEGORY_ORDER},
        age_buckets={key: 0 for key in AGE_BUCKETS},
    )
    folder_sizes: Dict[str, int] = {}
    root_loose_size = 0
    extension_stats: Dict[str, List[int]] = {}
    top_heap = []
    counter = 0
    stack = [root]
    last_file_progress = 0
    last_folder_progress = 0

    def _submit_next(pool, pending):
        while stack and len(pending) < workers:
            directory = stack.pop()
            pending[pool.submit(_scan_directory, directory, control)] = directory

    with ThreadPoolExecutor(max_workers=workers) as pool:
        pending = {}
        _submit_next(pool, pending)
        while pending:
            if control is not None:
                control.wait_if_paused()
                control.checkpoint()
            done, _unused = wait(pending, return_when=FIRST_COMPLETED)
            for future in done:
                pending.pop(future, None)
                try:
                    subdirs, files, errors = future.result()
                except Exception:
                    if control is not None and control.is_cancelled():
                        raise
                    subdirs, files, errors = [], [], 1
                summary.errors += errors
                if subdirs:
                    summary.folders += len(subdirs)
                    stack.extend(subdirs)
                for path, name, size, mtime in files:
                    category = file_category(name)
                    summary.files += 1
                    summary.total_size += size
                    summary.categories[category] = (
                        summary.categories.get(category, 0) + size
                    )
                    summary.age_buckets[
                        _age_key(max(0.0, now - mtime))
                    ] += size

                    ext = file_extension(name) or "(無副檔名)"
                    stats = extension_stats.setdefault(ext, [0, 0])
                    stats[0] += 1
                    stats[1] += size

                    age_seconds = max(0.0, now - mtime)
                    if ext in JUNK_EXTENSIONS or name.startswith("~$"):
                        summary.junk_files += 1
                        summary.junk_size += size
                    if (size >= LARGE_FILE_BYTES
                            and age_seconds >= OLD_SECONDS):
                        summary.old_large_files += 1
                        summary.old_large_size += size

                    rel = os.path.relpath(path, root)
                    parts = rel.split(os.sep)
                    if len(parts) > 1:
                        top = parts[0]
                        folder_sizes[top] = (
                            folder_sizes.get(top, 0) + size
                        )
                    else:
                        root_loose_size += size

                    counter += 1
                    item = (size, counter, path, mtime, category)
                    if len(top_heap) < top_n:
                        heapq.heappush(top_heap, item)
                    elif size > top_heap[0][0]:
                        heapq.heapreplace(top_heap, item)

                if progress is not None:
                    if summary.files - last_file_progress >= 250:
                        progress(summary.files, summary.folders,
                                 summary.total_size)
                        last_file_progress = summary.files
                    elif summary.folders - last_folder_progress >= 200:
                        progress(summary.files, summary.folders,
                                 summary.total_size)
                        last_folder_progress = summary.folders
                _submit_next(pool, pending)

    if root_loose_size:
        folder_sizes["（根目錄檔案）"] = root_loose_size

    summary.top_folders = [
        {"name": name, "size": size}
        for name, size in sorted(
            folder_sizes.items(), key=lambda pair: pair[1], reverse=True
        )[:top_n]
    ]
    summary.extensions = [
        {"extension": ext, "count": counts[0], "size": counts[1]}
        for ext, counts in sorted(
            extension_stats.items(), key=lambda pair: pair[1][1], reverse=True
        )[:top_extensions]
    ]
    summary.top_files = [
        {
            "path": path,
            "name": os.path.basename(path),
            "size": size,
            "modified": mtime,
            "category": category,
        }
        for size, _counter, path, mtime, category in sorted(
            top_heap, key=lambda item: item[0], reverse=True
        )
    ]
    summary.duration = round(time.monotonic() - started, 3)
    if progress is not None:
        progress(summary.files, summary.folders, summary.total_size)
    return summary
