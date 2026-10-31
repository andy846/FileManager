"""Pure, Qt-free file scanning for the Remover module."""

import os

from app.core.models import FileInfo
from app.core.utils import (
    extended_path, is_hidden, matches_exclusion, normalize_path,
    parse_size_to_bytes, safe_stat, strip_extended_path,
)


def _to_timestamp(qdate):
    """Convert a QDate (or None) to a unix timestamp."""
    if qdate is None:
        return None
    try:
        import datetime

        d = qdate.getDate() if hasattr(qdate, "getDate") else qdate
        year, month, day = d[0], d[1], d[2]
        return datetime.datetime(year, month, day, 23, 59, 59).timestamp()
    except Exception:
        return None


def scan_files(folder, extensions, filters, recursive=True,
               progress_callback=None, file_found_callback=None,
               cancel_check=None):
    """Scan *folder* for files matching the given filters.

    ``filters`` keys: date_from, date_to (QDate|None), size_op
    (">=", "<=", "between"|None), size_value, size_value_max, size_unit,
    exclude_patterns (list). ``extensions`` is a list of lower-case
    extensions without dots.
    """
    if not folder or not os.path.isdir(extended_path(folder)):
        raise FileNotFoundError(f"資料夾不存在: {folder}")
    if cancel_check:
        cancel_check()

    ext_set = set(e.lower().lstrip(".") for e in (extensions or []))
    date_from = _to_timestamp(filters.get("date_from"))
    date_to = _to_timestamp(filters.get("date_to"))
    size_op = filters.get("size_op")
    size_unit = filters.get("size_unit", "MB")
    size_value = parse_size_to_bytes(filters.get("size_value", 0), size_unit)
    size_value_max = parse_size_to_bytes(filters.get("size_value_max", 0), size_unit)
    exclude = filters.get("exclude_patterns", []) or []

    results = []
    count = 0
    for root, dirs, files in os.walk(extended_path(folder)):
        root = normalize_path(strip_extended_path(root))
        if not recursive:
            dirs[:] = []
        for name in files:
            if cancel_check:
                cancel_check()
            count += 1
            if progress_callback:
                progress_callback(count)
            full = normalize_path(os.path.join(root, name))
            if is_hidden(full):
                continue
            ext = os.path.splitext(name)[1].lower().lstrip(".")
            if ext_set and ext not in ext_set:
                continue
            st = safe_stat(full)
            if st is None:
                continue
            if matches_exclusion(full, exclude):
                continue
            mtime = st.st_mtime
            if date_from is not None and mtime < date_from:
                continue
            if date_to is not None and mtime > date_to:
                continue
            size = st.st_size
            if size_op == ">=" and size < size_value:
                continue
            if size_op == "<=" and size > size_value:
                continue
            if size_op == "between" and not (size_value <= size <= size_value_max):
                continue
            info = FileInfo(path=full, name=name, size=size,
                            modified=mtime, extension=ext)
            results.append(info)
            if file_found_callback:
                file_found_callback(info)
    return results
