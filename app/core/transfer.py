"""Shared copy/move engine with retries, verification and long paths."""

import ctypes
import os
import shutil
import sys
import tempfile
import threading
import time
from ctypes import wintypes

from app.core.constants import COPY_CHUNK_SIZE
from app.core.drives import ensure_reachable
from app.core.hashing import hash_file
from app.core.utils import extended_path, normalize_path, quick_digest
from app.core.workers import CancelledError


TRANSIENT_NETWORK_ERRORS = {
    53,   # ERROR_BAD_NETPATH
    64,   # ERROR_NETNAME_DELETED
    67,   # ERROR_BAD_NET_NAME
    121,  # ERROR_SEM_TIMEOUT
    161,  # ERROR_BAD_NETPATH (network path)
    1203, # ERROR_NO_NET_OR_BAD_PATH
    1231, # ERROR_NETWORK_UNREACHABLE
    2250, # ERROR_NOT_CONNECTED
}

_NATIVE = None

_PROGRESS_CALLBACK = None

# Serialize destination commits within this process. Striped locks avoid
# unbounded memory growth from keeping one lock per target filename.
_DESTINATION_LOCKS = [threading.Lock() for _ in range(256)]


def _destination_lock(path):
    key = os.path.normcase(os.path.abspath(path))
    return _DESTINATION_LOCKS[hash(key) % len(_DESTINATION_LOCKS)]


class DestinationExistsError(OSError):
    """Raised when a skip-mode commit would overwrite an existing file."""

    def __init__(self, path):
        super().__init__(f"目標已存在: {path}")
        self.path = path


def _next_available_path(path):
    """Return a sibling path that does not exist yet (``name (1).ext``)."""
    folder, name = os.path.split(path)
    stem, ext = os.path.splitext(name)
    index = 1
    while True:
        candidate = os.path.join(folder, f"{stem} ({index}){ext}")
        if not os.path.lexists(extended_path(candidate)):
            return candidate
        index += 1


def _commit_file(temp, dst, conflict="overwrite", backup_overwrite=None,
                 on_commit=None):
    """Commit *temp* to *dst* atomically, enforcing the conflict policy.

    The decision and the commit happen under one lock, so concurrent
    transfers inside this process cannot race each other. A no-replace
    operation also protects the destination from external writers.
    """
    final = dst
    while True:
        with _destination_lock(final):
            exists = os.path.lexists(extended_path(final))
            if exists and conflict == "skip":
                raise DestinationExistsError(final)
            if exists and conflict == "rename":
                final = _next_available_path(final)
                continue
            if exists and conflict == "overwrite":
                if backup_overwrite is not None:
                    backup_overwrite(final)
                os.replace(extended_path(temp), extended_path(final))
            else:
                try:
                    if sys.platform.startswith("win"):
                        os.rename(extended_path(temp), extended_path(final))
                    else:
                        # POSIX rename replaces existing files. Link creates
                        # the destination exclusively on the same filesystem.
                        os.link(extended_path(temp), extended_path(final))
                        os.unlink(extended_path(temp))
                except FileExistsError:
                    if conflict == "rename":
                        final = _next_available_path(final)
                    elif conflict == "skip":
                        raise DestinationExistsError(final)
                    # overwrite: re-run the decision, now replacing the target.
                    continue
            if on_commit is not None:
                on_commit(final)
            return final


class _NativeApi:
    def __init__(self):
        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        global _PROGRESS_CALLBACK
        _PROGRESS_CALLBACK = ctypes.WINFUNCTYPE(
            wintypes.DWORD,
            ctypes.c_longlong, ctypes.c_longlong,
            ctypes.c_longlong, ctypes.c_longlong,
            wintypes.DWORD, wintypes.DWORD,
            wintypes.HANDLE, wintypes.HANDLE, ctypes.c_void_p,
        )
        self.kernel32.CopyFileExW.argtypes = [
            wintypes.LPCWSTR, wintypes.LPCWSTR,
            _PROGRESS_CALLBACK, ctypes.c_void_p,
            ctypes.POINTER(wintypes.BOOL), wintypes.DWORD,
        ]
        self.kernel32.CopyFileExW.restype = wintypes.BOOL


def _native_api():
    global _NATIVE
    if not sys.platform.startswith("win"):
        return None
    if _NATIVE is None:
        try:
            _NATIVE = _NativeApi()
        except OSError:
            return None
    return _NATIVE


def verify_mode(value):
    """Normalise a bool/string verification setting."""
    if isinstance(value, bool):
        return "quick" if value else "off"
    text = str(value or "quick").strip().lower()
    return text if text in {"off", "size", "quick", "full"} else "quick"


def _winerror(exc):
    return getattr(exc, "winerror", None)


def is_transient_error(exc):
    code = _winerror(exc)
    if code in TRANSIENT_NETWORK_ERRORS:
        return True
    return getattr(exc, "errno", None) in {5, 116}


def _remove_quietly(path):
    try:
        if os.path.exists(extended_path(path)):
            os.remove(extended_path(path))
    except OSError:
        pass


def _copy_native(src, dst, control):
    """Try Windows CopyFileExW. Returns True on success, False to fall back."""
    api = _native_api()
    if api is None or _PROGRESS_CALLBACK is None:
        return False

    cancel = wintypes.BOOL(False)

    def _progress(_total, _transferred, _stream_size, _stream_transferred,
                  _stream_number, _reason, _source, _dest, _data):
        if control is not None:
            if control.is_cancelled():
                cancel.value = True
                return 1  # PROGRESS_CANCEL
            while control.is_paused() and not control.is_cancelled():
                time.sleep(0.1)
            if control.is_cancelled():
                cancel.value = True
                return 1
        return 0  # PROGRESS_CONTINUE

    callback = _PROGRESS_CALLBACK(_progress)
    try:
        ok = api.kernel32.CopyFileExW(
            extended_path(src), extended_path(dst),
            callback, None, ctypes.byref(cancel), 0,
        )
    except Exception:
        return False
    if ok:
        return True
    if control is not None and control.is_cancelled():
        raise CancelledError("複製已取消")
    return False


def _copy_python(src, dst, control, chunk_size=COPY_CHUNK_SIZE):
    with open(extended_path(src), "rb") as source, \
            open(extended_path(dst), "wb") as target:
        while True:
            if control is not None:
                control.wait_if_paused()
                control.checkpoint()
            chunk = source.read(chunk_size)
            if not chunk:
                break
            target.write(chunk)


def _verify_file(src, dst, expected_size, mode="quick", control=None):
    mode = verify_mode(mode)
    if mode == "off":
        return
    try:
        size = os.path.getsize(extended_path(dst))
    except OSError as exc:
        raise RuntimeError(f"驗證失敗：{exc}") from exc
    if expected_size is not None and size != expected_size:
        raise RuntimeError("大小驗證不符")
    if mode == "size":
        return
    if mode == "quick":
        if quick_digest(src) != quick_digest(dst):
            raise RuntimeError("快速內容驗證不符")
        return
    left = hash_file(extended_path(src), "sha256", control=control)
    right = hash_file(extended_path(dst), "sha256", control=control)
    if left != right:
        raise RuntimeError("完整內容驗證不符")


def retry_operation(func, attempts=1, control=None, path_hint=""):
    """Run *func*, retrying only transient network/IO errors."""
    attempts = max(0, int(attempts or 0))
    last = None
    for attempt in range(attempts + 1):
        if control is not None:
            control.checkpoint()
        try:
            return func()
        except CancelledError:
            raise
        except Exception as exc:
            last = exc
            if attempt >= attempts or not is_transient_error(exc):
                raise
            hints = (
                path_hint if isinstance(path_hint, (list, tuple, set))
                else [path_hint]
            )
            for hint in hints:
                if not hint:
                    continue
                try:
                    ensure_reachable(hint)
                except Exception:
                    pass
            if control is not None:
                control.wait_if_paused()
            time.sleep(min(0.5 * (attempt + 1), 2.0))
    if last is not None:
        raise last


def _same_device(src, dst):
    try:
        source_stat = os.stat(extended_path(src))
        parent = os.path.dirname(normalize_path(dst)) or "."
        os.makedirs(extended_path(parent), exist_ok=True)
        target_stat = os.stat(extended_path(parent))
        return source_stat.st_dev == target_stat.st_dev
    except OSError:
        return False


def copy_file(src, dst, control=None, verify="quick", retries=1,
              preserve_metadata=True, chunk_size=COPY_CHUNK_SIZE,
              conflict="overwrite", backup_overwrite=None, on_commit=None):
    """Copy one file atomically, verify it, and return its size.

    The copy is written to a ``.tmp~`` file first so a failed verification
    never destroys an existing destination file.
    """
    src = normalize_path(src)
    dst = normalize_path(dst)
    if not src or not dst:
        raise ValueError("來源或目標路徑為空")
    source_key = os.path.normcase(os.path.abspath(src))
    target_key = os.path.normcase(os.path.abspath(dst))
    if source_key == target_key:
        raise ValueError("來源與目標相同")
    parent = os.path.dirname(dst) or "."
    os.makedirs(extended_path(parent), exist_ok=True)
    size = os.path.getsize(extended_path(src))
    # A shared .tmp~ name lets concurrent jobs delete or corrupt each other.
    fd, temp = tempfile.mkstemp(
        prefix=f".{os.path.basename(dst)}.", suffix=".tmp~",
        dir=extended_path(parent),
    )
    os.close(fd)

    def _attempt():
        try:
            native = _copy_native(src, temp, control)
            if not native:
                _copy_python(src, temp, control, chunk_size=chunk_size)
            if preserve_metadata:
                try:
                    shutil.copystat(
                        extended_path(src), extended_path(temp),
                        follow_symlinks=False,
                    )
                except OSError:
                    pass
            _verify_file(src, temp, size, mode=verify, control=control)
            if control is not None:
                control.checkpoint()
            _commit_file(
                temp, dst, conflict=conflict,
                backup_overwrite=backup_overwrite, on_commit=on_commit,
            )
        except BaseException:
            _remove_quietly(temp)
            raise
        return size

    return retry_operation(_attempt, attempts=retries, control=control,
                           path_hint=(src, dst))


def move_file(src, dst, control=None, verify="quick", retries=1,
              preserve_metadata=True, conflict="overwrite",
              backup_overwrite=None, on_commit=None):
    """Move one file, using an atomic rename on the same device."""
    src = normalize_path(src)
    dst = normalize_path(dst)
    if not src or not dst:
        raise ValueError("來源或目標路徑為空")
    source_key = os.path.normcase(os.path.abspath(src))
    target_key = os.path.normcase(os.path.abspath(dst))
    if source_key == target_key:
        raise ValueError("來源與目標相同")
    parent = os.path.dirname(dst) or "."
    os.makedirs(extended_path(parent), exist_ok=True)
    size = os.path.getsize(extended_path(src))

    if _same_device(src, dst):
        def _rename():
            final = _commit_file(
                src, dst, conflict=conflict,
                backup_overwrite=backup_overwrite, on_commit=on_commit,
            )
            # A rename does not change file content, so only the size needs
            # checking; avoid re-reading a potentially large network file.
            _verify_file(final, final, size, mode="size", control=control)
            return size

        return retry_operation(_rename, attempts=retries,
                               control=control, path_hint=(src, dst))

    copy_file(
        src, dst, control=control, verify=verify, retries=retries,
        preserve_metadata=preserve_metadata, conflict=conflict,
        backup_overwrite=backup_overwrite, on_commit=on_commit,
    )

    def _remove():
        os.remove(extended_path(src))

    retry_operation(_remove, attempts=retries, control=control,
                    path_hint=(src, dst))
    return size
