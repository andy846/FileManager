"""Small JSON cache for the last dashboard folder analysis."""

import json
import os

from app.core.utils import extended_path
from app.modules.dashboard.scanner import ScanSummary

CACHE_VERSION = 1
CACHE_FILENAME = "dashboard_cache.json"


def cache_path(settings):
    ini = settings.q.fileName()
    return os.path.join(os.path.dirname(ini), CACHE_FILENAME)


def save_cache(settings, summary):
    """Persist *summary*; failures are non-fatal (dashboard simply rescans)."""
    if not isinstance(summary, ScanSummary) or summary.cancelled:
        return False
    payload = {"version": CACHE_VERSION, "summary": summary.as_dict()}
    path = cache_path(settings)
    tmp = f"{path}.tmp"
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False)
        os.replace(tmp, path)
        return True
    except Exception:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass
        return False


def load_cache(settings):
    """Load the cached summary, or None when missing/invalid."""
    path = cache_path(settings)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
        if payload.get("version") != CACHE_VERSION:
            return None
        summary = ScanSummary.from_dict(payload.get("summary", {}))
        if not summary.root or not os.path.isdir(extended_path(summary.root)):
            return None
        return summary
    except Exception:
        return None


def clear_cache(settings):
    path = cache_path(settings)
    try:
        if os.path.isfile(path):
            os.remove(path)
    except OSError:
        pass
