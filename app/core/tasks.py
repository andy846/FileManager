"""Lightweight, UI-independent session task registry.

Pages keep owning their workers and signals; this registry gives every long
operation one shared, observable record for the task centre and dashboard.
"""

import datetime
import itertools

from PyQt6.QtCore import QObject, pyqtSignal

STATUS_RUNNING = "running"
STATUS_PAUSED = "paused"
STATUS_DONE = "done"
STATUS_FAILED = "failed"
STATUS_CANCELLED = "cancelled"

STATUS_LABELS = {
    STATUS_RUNNING: "進行中",
    STATUS_PAUSED: "已暫停",
    STATUS_DONE: "完成",
    STATUS_FAILED: "失敗",
    STATUS_CANCELLED: "已取消",
}

MAX_TASKS = 200


class TaskRecord:
    """One observable operation."""

    _ids = itertools.count(1)

    def __init__(self, kind, title, module="", control=None,
                 cancel_callback=None, pause_callback=None,
                 total=0, message="", pausable=True):
        self.id = next(self._ids)
        self.kind = kind
        self.title = title
        self.module = module
        self.control = control
        self.cancel_callback = cancel_callback
        self.pause_callback = pause_callback
        self.pausable = bool(pausable)
        self.status = STATUS_RUNNING
        self.done = 0
        self.total = int(total or 0)
        self.message = message
        self.error = ""
        self.started_at = datetime.datetime.now()
        self.finished_at = None

    @property
    def percent(self):
        if not self.total:
            return 0
        return max(0, min(100, int(self.done / self.total * 100)))

    @property
    def elapsed(self):
        end = self.finished_at or datetime.datetime.now()
        return max(0.0, (end - self.started_at).total_seconds())

    @property
    def is_active(self):
        return self.status in (STATUS_RUNNING, STATUS_PAUSED)

    @property
    def can_pause(self):
        return self.pausable and bool(self.control or self.pause_callback)

    def __repr__(self):  # pragma: no cover - debugging aid
        return f"<TaskRecord {self.id} {self.kind} {self.status}>"


class TaskManager(QObject):
    """Session-wide task list with change notifications."""

    changed = pyqtSignal()
    task_added = pyqtSignal(object)
    task_finished = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._tasks = []
        self._active = 0

    def add(self, kind, title, module="", control=None, cancel=None,
            pause=None, total=0, message="", pausable=True):
        task = TaskRecord(
            kind=kind, title=title, module=module, control=control,
            cancel_callback=cancel, pause_callback=pause,
            total=total, message=message, pausable=pausable,
        )
        self._tasks.append(task)
        self._active += 1
        if len(self._tasks) > MAX_TASKS:
            for index, existing in enumerate(self._tasks):
                if not existing.is_active:
                    self._tasks.pop(index)
                    break
        self.task_added.emit(task)
        self.changed.emit()
        return task

    def update(self, task, done=None, total=None, message=None, status=None,
               error=None):
        if task is None:
            return
        if done is not None:
            task.done = int(done)
        if total is not None:
            task.total = int(total)
        if message is not None:
            task.message = str(message)
        if error is not None:
            task.error = str(error)
        if status is not None and task.status != status:
            if task.status in (STATUS_RUNNING, STATUS_PAUSED) and \
                    status not in (STATUS_RUNNING, STATUS_PAUSED):
                self._active = max(0, self._active - 1)
            task.status = status
        self.changed.emit()

    def finish(self, task, status=STATUS_DONE, message=None, error=""):
        if task is None:
            return
        self.update(task, status=status, message=message, error=error)
        task.finished_at = datetime.datetime.now()
        self.task_finished.emit(task)
        self.changed.emit()

    def cancel(self, task):
        if task is None or not task.is_active:
            return
        if task.cancel_callback is not None:
            task.cancel_callback()
        elif task.control is not None:
            task.control.cancel()
        self.update(task, message="正在取消...")

    def toggle_pause(self, task):
        if task is None or task.status not in (STATUS_RUNNING, STATUS_PAUSED):
            return
        if task.pause_callback is not None:
            task.pause_callback()
        elif task.control is not None:
            if task.status == STATUS_RUNNING:
                task.control.pause()
            else:
                task.control.resume()
        if task.status == STATUS_RUNNING:
            self.update(task, status=STATUS_PAUSED, message="已暫停")
        else:
            self.update(task, status=STATUS_RUNNING, message="繼續執行")

    def tasks(self):
        return list(self._tasks)

    def active_tasks(self):
        return [task for task in self._tasks if task.is_active]

    def recent(self, limit=10):
        return self._tasks[-limit:][::-1]

    def active_count(self):
        return len(self.active_tasks())

    def clear_finished(self):
        self._tasks = [task for task in self._tasks if task.is_active]
        self.changed.emit()
