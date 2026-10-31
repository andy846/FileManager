"""Typed wrapper around QSettings for persistent application state."""

from PyQt6.QtCore import QSettings

from app.core.constants import ORG_NAME, APP_NAME
from app.core.utils import normalize_path


class AppSettings:
    """Thin, typed wrapper over QSettings (INI, UserScope)."""

    def __init__(self):
        self.q = QSettings(QSettings.Format.IniFormat, QSettings.Scope.UserScope,
                           ORG_NAME, APP_NAME)

    def _coerce(self, value, default):
        if isinstance(default, bool):
            if isinstance(value, bool):
                return value
            text = str(value).strip().lower()
            if text in ("1", "true", "yes", "on"):
                return True
            if text in ("0", "false", "no", "off", ""):
                return False
            return default
        try:
            if isinstance(default, int):
                return int(value)
            if isinstance(default, float):
                return float(value)
        except (TypeError, ValueError):
            return default
        return value

    def option(self, name, default):
        key = f"options/{name}"
        if self.q.contains(key):
            return self._coerce(self.q.value(key), default)
        return default

    def set_option(self, name, value):
        self.q.setValue(f"options/{name}", value)
        self.q.sync()

    def set_options(self, values):
        """Write several options and sync the INI once."""
        for name, value in values.items():
            self.q.setValue(f"options/{name}", value)
        self.q.sync()

    def value(self, name, default=None):
        return self.q.value(name, default)

    def set_value(self, name, value):
        self.q.setValue(name, value)
        self.q.sync()

    def recent(self, field_name):
        raw = self.q.value(f"recent/{field_name}")
        if raw is None:
            return []
        if isinstance(raw, str):
            raw = [raw] if raw else []
        paths = []
        seen = set()
        for item in raw:
            if item is None:
                continue
            path = normalize_path(item)
            key = path.casefold()
            if not path or key in seen:
                continue
            seen.add(key)
            paths.append(path)
        return paths

    def remember_path(self, field_name, path):
        path = normalize_path(path)
        if not path:
            return
        paths = self.recent(field_name)
        paths = [p for p in paths if p.casefold() != path.casefold()]
        paths.insert(0, path)
        from app.core.constants import MAX_RECENT

        paths = paths[:MAX_RECENT]
        self.q.setValue(f"recent/{field_name}", paths)
        self.q.sync()

    def clear_recent(self, field_name):
        self.q.setValue(f"recent/{field_name}", [])
        self.q.sync()

    def save_geometry(self, data):
        self.q.setValue("ui/geometry", data)
        self.q.sync()

    def load_geometry(self):
        return self.q.value("ui/geometry")

    def clear(self):
        self.q.clear()
        self.q.sync()

    def remove_option(self, name):
        self.q.remove(f"options/{name}")
        self.q.sync()

    def migrate(self):
        """Apply additive defaults; never overwrite existing user choices."""
        version = int(self.option("settings_version", 1) or 1)
        if version >= 2:
            return version
        defaults = {
            "start_page": "dashboard",
            "language": "en",
            "default_conflict": "skip",
            "verify_copy": True,
            "copy_verify_mode": "quick",
            "copy_retries": 1,
            "browser_dual": True,
            "browser_show_hidden": False,
            "browser_preview_default": False,
            "preview_max_mb": 20,
            "history_limit": 500,
            "task_notify": True,
        }
        added = {}
        for key, value in defaults.items():
            if not self.q.contains(f"options/{key}"):
                added[key] = value
        added["settings_version"] = 2
        self.set_options(added)
        return 2

