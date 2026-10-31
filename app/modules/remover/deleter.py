"""Pure, Qt-free deletion engine for the Remover module."""

import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

from app.core.utils import send_to_trash


def delete_files(files, cancel_check=None, progress_callback=None,
                 file_deleted_callback=None, file_failed_callback=None,
                 permanent=False, threads=None):
    """Delete / trash the given files, optionally in parallel.

    Returns ``(deleted, failed)`` where each is a list of paths (and
    ``failed`` holds ``(path, error)`` tuples).
    """
    if threads is None:
        import multiprocessing

        threads = min(8, max(4, (multiprocessing.cpu_count() or 4)))
    deleted = []
    failed = []
    lock = threading.Lock()
    done = 0
    total = len(files)

    def _do(path):
        if permanent:
            try:
                if os.path.isdir(path) and not os.path.islink(path):
                    os.rmdir(path)
                else:
                    os.remove(path)
                return None
            except Exception as exc:
                return str(exc)
        else:
            ok, err = send_to_trash(path)
            return None if ok else err

    from app.core.workers import CancelledError

    with ThreadPoolExecutor(max_workers=threads) as pool:
        futures = {pool.submit(_do, f.path if hasattr(f, "path") else f): f
                   for f in files}
        try:
            for fut in as_completed(futures):
                if cancel_check:
                    cancel_check()
                f = futures[fut]
                path = f.path if hasattr(f, "path") else f
                err = fut.result()
                with lock:
                    done += 1
                if err:
                    failed.append((path, err))
                    if file_failed_callback:
                        file_failed_callback(path, err)
                else:
                    deleted.append(path)
                    if file_deleted_callback:
                        file_deleted_callback(path)
                if progress_callback:
                    progress_callback(done, total)
        except CancelledError:
            # Stop collecting results; return whatever was processed so far.
            return deleted, failed
    return deleted, failed
