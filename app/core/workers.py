"""Thread-safe operation control shared by all background workers."""

import threading

from PyQt6.QtCore import QThread, pyqtSignal


class CancelledError(Exception):
    pass


class OperationControl:
    """Coordinates cancel / pause signals between the UI and worker threads."""

    def __init__(self):
        self._cancel = threading.Event()
        self._pause = threading.Event()
        self._bytes_lock = threading.Lock()
        self._count_lock = threading.Lock()

    def cancel(self):
        self._cancel.set()

    def is_cancelled(self):
        return self._cancel.is_set()

    def pause(self):
        self._pause.set()

    def resume(self):
        self._pause.clear()

    def is_paused(self):
        return self._pause.is_set()

    def wait_if_paused(self):
        while self._pause.is_set() and not self._cancel.is_set():
            self._pause.wait(0.2)

    def checkpoint(self):
        """Raise CancelledError if cancelled (call inside worker loops)."""
        if self._cancel.is_set():
            raise CancelledError("操作已取消")

    def reset(self):
        self._cancel.clear()
        self._pause.clear()


def atomic_copy(src, dst, chunk_size=512 * 1024, fsync=False, control=None):
    """Copy *src* to *dst* via a temp file and atomic replace.

    Returns the number of bytes copied. Honours *control* for cancel/pause.
    Raises on failure (caller decides rename/recovery).
    """
    import os

    tmp = f"{dst}.tmp~"
    copied = 0
    try:
        os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
        with open(src, "rb") as fin, open(tmp, "wb") as fout:
            while True:
                if control is not None:
                    control.wait_if_paused()
                    control.checkpoint()
                chunk = fin.read(chunk_size)
                if not chunk:
                    break
                fout.write(chunk)
                copied += len(chunk)
            if fsync:
                fout.flush()
                os.fsync(fout.fileno())
        os.replace(tmp, dst)
    except BaseException:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
        raise
    return copied


class BaseWorker(QThread):
    """Base background worker emitting standard progress/log signals.

    Subclasses must implement :meth:`run` and use ``self.control`` for
    cooperative cancel / pause.
    """

    log_line = pyqtSignal(str)
    progress_changed = pyqtSignal(int, int)  # done, total
    stats_changed = pyqtSignal(float, float, int)  # speed, eta, bytes
    # NOTE: do not name this ``finished`` - QThread already owns a
    # ``finished()`` signal and shadowing it with a different signature
    # breaks any connection that expects the built-in one.
    run_done = pyqtSignal(bool, object)  # cancelled, summary

    def __init__(self, control=None):
        super().__init__()
        self.control = control or OperationControl()

    def emit_log(self, message):
        import datetime

        ts = datetime.datetime.now().strftime("%H:%M:%S")
        self.log_line.emit(f"[{ts}] {message}")
