"""Unified operation history shared by every module."""

import os
import json
import datetime
from typing import List

from app.core.constants import MAX_HISTORY_RECORDS
from app.core.utils import normalize_path


def _history_path(settings):
    # Persist next to the QSettings INI file location.

    ini = settings.q.fileName()
    return os.path.join(os.path.dirname(ini), "operation_history.json")


def load_history(settings) -> List[dict]:
    path = _history_path(settings)
    if not os.path.isfile(path):
        return []
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def record_operation(settings, module, folder, detail,
                     files_processed=0, files_failed=0, size_freed_bytes=0,
                     log_files=None):
    """Append an operation record, pruning to MAX_HISTORY_RECORDS."""
    history = load_history(settings)
    last_id = max((r.get("id", 0) for r in history), default=0)
    record = {
        "id": last_id + 1,
        "module": module,
        "timestamp": datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "folder": normalize_path(folder),
        "detail": detail,
        "files_processed": files_processed,
        "files_failed": files_failed,
        "size_freed_bytes": size_freed_bytes,
        "log_files": log_files or [],
    }
    history.append(record)
    try:
        limit = int(settings.option("history_limit", MAX_HISTORY_RECORDS))
    except (TypeError, ValueError):
        limit = MAX_HISTORY_RECORDS
    limit = max(1, limit)
    if len(history) > limit:
        history = history[-limit:]
    path = _history_path(settings)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)
    return record


def clear_history(settings):
    path = _history_path(settings)
    if os.path.isfile(path):
        with open(path, "w", encoding="utf-8") as f:
            f.write("[]")


def prune_history(settings, limit):
    """Trim the history file to the newest *limit* records."""
    try:
        limit = max(1, int(limit))
    except (TypeError, ValueError):
        return
    history = load_history(settings)
    if len(history) <= limit:
        return
    path = _history_path(settings)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(history[-limit:], f, ensure_ascii=False, indent=2)
    except OSError:
        pass



def summarize_history(records):
    """Aggregate operation-history records for the dashboard/history dialog.

    Returns a dict with totals and a per-module breakdown. The function is
    pure and tolerant of older records that lack newer optional fields.
    """
    summary = {
        "operations": 0,
        "processed": 0,
        "failed": 0,
        "freed_bytes": 0,
        "by_module": {},
        "success_rate": 0.0,
    }
    for record in records or []:
        if not isinstance(record, dict):
            continue
        summary["operations"] += 1
        processed = int(record.get("files_processed", 0) or 0)
        failed = int(record.get("files_failed", 0) or 0)
        freed = int(record.get("size_freed_bytes", 0) or 0)
        summary["processed"] += processed
        summary["failed"] += failed
        summary["freed_bytes"] += freed

        module = str(record.get("module", "unknown"))
        bucket = summary["by_module"].setdefault(
            module, {"operations": 0, "processed": 0, "failed": 0, "freed_bytes": 0}
        )
        bucket["operations"] += 1
        bucket["processed"] += processed
        bucket["failed"] += failed
        bucket["freed_bytes"] += freed

    attempted = summary["processed"] + summary["failed"]
    if attempted:
        summary["success_rate"] = summary["processed"] / attempted
    return summary

