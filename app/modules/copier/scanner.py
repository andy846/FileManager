"""Pure, Qt-free logic for selecting source files to copy/move."""

import os
import csv
import fnmatch

from app.core.models import CopyTask
from app.core.utils import (
    extended_path, normalize_path, strip_extended_path,
)


def parse_patterns_text(text):
    """Parse a multiline / comma separated pattern list."""
    patterns = []
    for line in (text or "").splitlines():
        for part in line.split(","):
            part = part.strip()
            if part:
                patterns.append(part)
    return patterns


def read_csv_patterns(path):
    """Read first-column patterns from a CSV in multiple encodings."""
    encodings = ["utf-8-sig", "utf-8", "big5", "cp950", "gbk", "latin-1"]
    last_error = None
    for enc in encodings:
        try:
            with open(path, encoding=enc, newline="") as f:
                reader = csv.reader(f)
                return [row[0].strip() for row in reader if row and row[0].strip()]
        except (UnicodeDecodeError, LookupError) as exc:
            last_error = exc
    # Final fallback: ignore errors.
    try:
        with open(path, encoding="utf-8", errors="ignore", newline="") as f:
            reader = csv.reader(f)
            return [row[0].strip() for row in reader if row and row[0].strip()]
    except Exception:
        raise last_error or OSError(f"無法讀取 CSV: {path}")


def is_under(base, path):
    """Return True if *path* is inside *base* (or equal)."""
    base = os.path.normcase(os.path.abspath(base))
    path = os.path.normcase(os.path.abspath(path))
    return path == base or path.startswith(base + os.sep)


def passes_size_filter(size, min_mb, max_mb):
    if min_mb and min_mb > 0 and size < min_mb * 1024 * 1024:
        return False
    if max_mb and max_mb > 0 and size > max_mb * 1024 * 1024:
        return False
    return True


def _scan_files(root, recursive=True, cancel_check=None):
    results = []
    if recursive:
        for dirpath, _dirnames, filenames in os.walk(extended_path(root)):
            if cancel_check:
                cancel_check()
            dirpath = strip_extended_path(dirpath)
            for name in filenames:
                if cancel_check:
                    cancel_check()
                results.append(os.path.join(dirpath, name))
    else:
        with os.scandir(extended_path(root)) as it:
            for entry in it:
                if cancel_check:
                    cancel_check()
                if entry.is_file():
                    results.append(
                        normalize_path(strip_extended_path(entry.path))
                    )
    return results


def _unique_dest(base_dst, relname, used):
    """Return a free destination path, auto-renaming on collision."""
    candidate = os.path.join(base_dst, relname)
    if candidate not in used:
        used.add(candidate)
        return candidate
    name, ext = os.path.splitext(relname)
    i = 1
    while True:
        cand = os.path.join(base_dst, f"{name} ({i}){ext}")
        if cand not in used:
            used.add(cand)
            return cand
        i += 1


def build_tasks(source, target, mode, options, cancel_check=None):
    """Build the list of CopyTask objects for a copy/move operation.

    ``options`` keys: csv_path, patterns_text, extensions (list), min_mb,
    max_mb, preserve_structure (bool). ``cancel_check`` is called while
    walking the source tree so a long scan can be cancelled promptly.
    """
    if not source or not os.path.isdir(extended_path(source)):
        raise FileNotFoundError(f"來源資料夾不存在: {source}")
    if not target:
        raise ValueError("請指定目標資料夾")

    if mode == "csv":
        patterns = read_csv_patterns(options["csv_path"])
    elif mode == "ext":
        patterns = [f"*.{e.lower()}" for e in options.get("extensions", [])]
    else:  # custom
        patterns = parse_patterns_text(options.get("patterns_text", ""))

    if not patterns:
        return []

    files = _scan_files(source, recursive=True, cancel_check=cancel_check)
    used = set()
    tasks = []
    tid = 0
    for path in files:
        if cancel_check:
            cancel_check()
        # Exclude the destination directory to avoid copying into itself and
        # skip temp files produced by atomic copy.
        if path.endswith(".tmp~"):
            continue
        if is_under(target, path):
            continue
        name = os.path.basename(path)
        rel = os.path.relpath(path, source)
        low_rel = rel.lower()
        # Normalise separators so patterns like "sub/file.pdf" match on Windows.
        low_rel_norm = low_rel.replace("\\", "/")
        low_name = name.lower()
        matched = False
        for pat in patterns:
            low_pat = pat.lower().replace("\\", "/")
            if (fnmatch.fnmatch(low_rel_norm, low_pat)
                    or fnmatch.fnmatch(low_name, low_pat)):
                matched = True
                break
        if not matched:
            continue
        try:
            size = os.path.getsize(extended_path(path))
        except OSError:
            size = 0
        if not passes_size_filter(size, options.get("min_mb", 0), options.get("max_mb", 0)):
            continue
        if options.get("preserve_structure", False):
            relname = rel
        else:
            relname = name
        dst = _unique_dest(target, relname, used)
        tid += 1
        tasks.append(CopyTask(id=tid, src=path, dst=dst, size=size))
    return tasks
