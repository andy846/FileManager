"""Base class all module pages inherit from."""

from PyQt6.QtWidgets import QWidget


class ModulePage(QWidget):
    """Common base for every module page in the sidebar shell."""

    title = "模組"
    module_id = "module"

    def __init__(self, settings, main_window=None):
        super().__init__()
        self.settings = settings
        self.main_window = main_window

    def status(self, message, timeout=0):
        if self.main_window:
            self.main_window.show_status(message, timeout)

    def theme(self):
        return self.main_window.theme if self.main_window else "dark"

    def on_show(self):
        """Hook called when this page becomes visible."""
        pass

    def apply_payload(self, payload):
        """Receive a module-specific payload from another page."""
        pass

    def on_theme_changed(self):
        """Hook called after the application theme changes."""
        pass

    def on_settings_changed(self):
        """Hook called after the settings page saves changes."""
        pass

    # ------------------------------------------------------------------
    # Shared task registry helpers (safe when the page is used standalone).
    # ------------------------------------------------------------------
    def _task_manager(self):
        return getattr(self.main_window, "tasks", None)

    def task_add(self, kind, title, control=None, cancel=None, pause=None,
                 total=0, message="", pausable=True):
        manager = self._task_manager()
        if manager is None:
            return None
        return manager.add(
            kind, title, self.module_id, control=control, cancel=cancel,
            pause=pause, total=total, message=message, pausable=pausable,
        )

    def task_update(self, task, done=None, total=None, message=None,
                    status=None, error=None):
        manager = self._task_manager()
        if manager is not None and task is not None:
            manager.update(task, done=done, total=total, message=message,
                           status=status, error=error)

    def task_finish(self, task, status="done", message=None, error=""):
        manager = self._task_manager()
        if manager is not None and task is not None:
            manager.finish(task, status=status, message=message, error=error)


