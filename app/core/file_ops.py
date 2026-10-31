"""Small shared file-operation helpers used across modules."""

import os

from PyQt6.QtCore import QThread, pyqtSignal

from app.core.utils import extended_path, send_to_trash
from app.core.workers import OperationControl


def is_within(child, parent):
    child = os.path.normcase(os.path.normpath(os.path.abspath(str(child))))
    parent = os.path.normcase(os.path.normpath(os.path.abspath(str(parent))))
    if child == parent:
        return True
    try:
        return os.path.commonpath([child, parent]) == parent
    except ValueError:
        return False


def unique_path(path):
    """Return a non-existing path by appending `` (1)``, `` (2)`` ..."""
    path = str(path)
    if not os.path.exists(extended_path(path)):
        return path
    folder, name = os.path.split(path)
    stem, ext = os.path.splitext(name)
    index = 1
    while True:
        candidate = os.path.join(folder, f"{stem} ({index}){ext}")
        if not os.path.exists(extended_path(candidate)):
            return candidate
        index += 1


class TrashWorker(QThread):
    """Move a list of paths to the recycle bin without freezing the UI."""

    completed = pyqtSignal(list, list)
    progress = pyqtSignal(int, int)

    def __init__(self, paths, control=None):
        super().__init__()
        self.paths = list(paths)
        self.control = control or OperationControl()

    def cancel(self):
        self.control.cancel()

    def run(self):
        deleted = []
        failed = []
        for index, path in enumerate(self.paths, 1):
            self.control.wait_if_paused()
            if self.control.is_cancelled():
                break
            self.control.checkpoint()
            ok, error = send_to_trash(path)
            if ok:
                deleted.append(path)
            else:
                failed.append((path, error))
            self.progress.emit(index, len(self.paths))
        self.completed.emit(deleted, failed)
