"""Pure duplicate detection logic (SHA-256 + quick prefix hash).

The size-first / quick-hash / full-hash passes are I/O bound, so both
hashing passes are executed on a thread pool to use the disk queue and
multiple cores instead of hashing one file at a time.

Progress is reported as structured :class:`ScanProgress` snapshots so the
UI can show real phases and numbers instead of a permanent busy indicator.
"""

import os
import hashlib
import threading
import time
from collections import defaultdict
from dataclasses import dataclass

from app.core.models import DuplicateGroup, FileInfo
from app.core.utils import (
    extended_path, is_hidden, matches_exclusion, normalize_path, safe_stat,
    strip_extended_path,
)

PROGRESS_INTERVAL = 0.15


@dataclass(frozen=True)
class ScanProgress:
    """One progress snapshot from :func:`find_duplicates`.

    ``phase`` is ``"scan"`` (enumerating, ``total`` unknown), ``"quick"``
    (``done``/``total`` are candidate files) or ``"full"`` (``done``/
    ``total`` are bytes hashed).
    """

    phase: str
    done: int
    total: int
    scanned: int
    detail: str = ""


def _quick_hash(path, size, prefix=65536):
    """Hash of the first ``prefix`` bytes (whole file if smaller)."""
    h = hashlib.sha256()
    try:
        with open(extended_path(path), "rb") as f:
            data = f.read(prefix)
        h.update(data)
        if size <= prefix:
            return h.hexdigest(), True  # full file already covered
        return h.hexdigest(), False
    except OSError:
        return None, False


def _full_hash(path, on_chunk=None, cancel_check=None):
    h = hashlib.sha256()
    try:
        with open(extended_path(path), "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                if cancel_check:
                    cancel_check()
                h.update(chunk)
                if on_chunk:
                    on_chunk(len(chunk))
        return h.hexdigest()
    except OSError:
        return None


def _parallel_map(func, items, cancel_check=None, workers=8,
                  on_completed=None):
    """Map *func* over hashable *items* concurrently.

    Returns ``{item: result}``; failed items map to ``None``. Raises the
    cancellation error promptly if *cancel_check* signals a stop.
    *on_completed* is called once per finished item (including failures).
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from app.core.workers import CancelledError

    results = {}
    if not items:
        return results
    if cancel_check:
        cancel_check()

    def _run(item):
        if cancel_check:
            cancel_check()
        return func(item)

    with ThreadPoolExecutor(max_workers=min(workers, len(items))) as pool:
        futures = {pool.submit(_run, item): item for item in items}
        for fut in as_completed(futures):
            if cancel_check:
                cancel_check()
            item = futures[fut]
            try:
                results[item] = fut.result()
            except CancelledError:
                for pending in futures:
                    pending.cancel()
                raise
            except Exception:
                results[item] = None
            if on_completed:
                on_completed()
    return results


def find_duplicates(folder, recursive=True, progress_callback=None,
                    cancel_check=None, min_size=1, exclude=None,
                    ignore_hardlinks=True):
    """Return a list of DuplicateGroup for files sharing identical content.

    Uses a size-first then quick-hash then full-hash strategy to minimise
    expensive full-file hashing. A ``CancelledError`` raised by
    ``cancel_check`` stops the scan and returns the groups found so far.

    ``progress_callback`` receives :class:`ScanProgress` snapshots. Calls are
    throttled, but every phase start and end is reported.
    """
    if not folder or not os.path.isdir(extended_path(folder)):
        raise FileNotFoundError(f"資料夾不存在: {folder}")

    from app.core.workers import CancelledError

    min_size = max(1, int(min_size or 1))
    exclude = list(exclude or [])
    groups = []

    emit_lock = threading.Lock()
    last_emit = 0.0

    def report(phase, done, total, scanned, detail="", force=False):
        nonlocal last_emit
        if progress_callback is None:
            return
        now = time.monotonic()
        if not force and now - last_emit < PROGRESS_INTERVAL:
            return
        with emit_lock:
            if not force and now - last_emit < PROGRESS_INTERVAL:
                return
            last_emit = now
        try:
            progress_callback(ScanProgress(
                phase=phase, done=int(done), total=int(total),
                scanned=int(scanned), detail=detail,
            ))
        except Exception:
            # A broken observer must never abort a long scan.
            pass

    try:
        report("scan", 0, 0, 0, force=True)

        # Pass 1: group by size.
        by_size = defaultdict(list)
        scanned = 0
        for root, dirs, files in os.walk(extended_path(folder)):
            root = normalize_path(strip_extended_path(root))
            if not recursive:
                dirs[:] = []
            for name in files:
                if cancel_check:
                    cancel_check()
                scanned += 1
                full = normalize_path(os.path.join(root, name))
                if is_hidden(full):
                    report("scan", scanned, 0, scanned)
                    continue
                if matches_exclusion(full, exclude):
                    report("scan", scanned, 0, scanned)
                    continue
                st = safe_stat(full)
                if st is None or st.st_size < min_size:
                    report("scan", scanned, 0, scanned)
                    continue
                if ignore_hardlinks and getattr(st, "st_nlink", 1) > 1:
                    report("scan", scanned, 0, scanned)
                    continue
                by_size[st.st_size].append((full, st.st_mtime))
                report("scan", scanned, 0, scanned)
        report("scan", scanned, 0, scanned, force=True)

        size_groups = [
            (size, items) for size, items in by_size.items() if len(items) >= 2
        ]
        candidates = [
            item for _size, items in size_groups for item in items
        ]

        # Pass 2: quick (prefix) hash within same-size groups (parallel).
        by_quick = defaultdict(list)
        quick_total = len(candidates)
        quick_done = 0
        quick_lock = threading.Lock()

        def _quick_completed():
            nonlocal quick_done
            with quick_lock:
                quick_done += 1
                done = quick_done
            report("quick", done, quick_total, scanned)

        if quick_total:
            report("quick", 0, quick_total, scanned, force=True)
        for size, items in size_groups:
            digests = _parallel_map(
                lambda it, s=size: _quick_hash(it[0], s),
                items, cancel_check, on_completed=_quick_completed)
            for full, mtime in items:
                qh, full_covered = digests.get((full, mtime), (None, False))
                if qh is None:
                    continue
                by_quick[(size, qh)].append((full, mtime, full_covered))
        if quick_total:
            report("quick", quick_total, quick_total, scanned, force=True)

        # Pass 3: confirm with full hash where needed (parallel per group).
        full_groups = []
        full_total = 0
        for (size, quick), items in by_quick.items():
            if len(items) < 2:
                continue
            needs_full = [item for item in items if not item[2]]
            full_total += size * len(needs_full)
            full_groups.append((size, quick, items, needs_full))

        full_done = 0
        full_lock = threading.Lock()

        def _full_chunk(count):
            nonlocal full_done
            with full_lock:
                full_done += count
                done = full_done
            report("full", done, full_total, scanned)

        if full_total:
            report("full", 0, full_total, scanned, force=True)

        gid = 0
        for size, quick, items, needs_full in full_groups:

            def _digest(it):
                full = it[0]
                return _full_hash(
                    full, on_chunk=_full_chunk, cancel_check=cancel_check
                )

            digests = _parallel_map(
                _digest, needs_full, cancel_check
            ) if needs_full else {}
            by_full = defaultdict(list)
            for full, mtime, full_covered in items:
                digest = quick if full_covered else digests.get(
                    (full, mtime, full_covered)
                )
                if digest is None:
                    continue
                by_full[digest].append((full, mtime))
            for digest, members in by_full.items():
                if len(members) < 2:
                    continue
                gid += 1
                infos = [
                    FileInfo(path=full, size=size, modified=mtime)
                    for full, mtime in members
                ]
                groups.append(
                    DuplicateGroup(hash=digest, size=size, files=infos)
                )

        if full_total:
            report("full", full_total, full_total, scanned, force=True)
    except CancelledError:
        return groups
    return groups
