"""Pure, Qt-free deletion engine for the Remover module."""

import os
from concurrent.futures import (
    CancelledError as FutureCancelledError,
    FIRST_COMPLETED, ThreadPoolExecutor, wait,
)

from app.core.utils import send_to_trash


def delete_files(files, cancel_check=None, progress_callback=None,
                 file_deleted_callback=None, file_failed_callback=None,
                 permanent=False, threads=None):
    """Delete files with bounded parallelism and honest cancellation results.

    Only `threads` jobs are ever in flight. Cancellation prevents any
    additional submissions, including work that has not started yet.
    Running operations cannot be interrupted; their outcomes are still
    included in the returned audit lists.
    """
    from app.core.workers import CancelledError

    if threads is None:
        import multiprocessing

        threads = min(8, max(4, (multiprocessing.cpu_count() or 4)))
    threads = max(1, int(threads))
    deleted = []
    failed = []
    done = 0
    total = len(files)
    iterator = iter(files)
    cancelled = False

    def _path(item):
        return item.path if hasattr(item, "path") else item

    def _do(item):
        if cancel_check:
            cancel_check()  # Check at the last possible point before deletion.
        path = _path(item)
        if permanent:
            try:
                if os.path.isdir(path) and not os.path.islink(path):
                    os.rmdir(path)
                else:
                    os.remove(path)
                return None
            except Exception as exc:
                return str(exc)
        ok, err = send_to_trash(path)
        return None if ok else err

    with ThreadPoolExecutor(max_workers=threads) as pool:
        pending = {}

        def submit_next():
            nonlocal cancelled
            if cancelled:
                return False
            try:
                if cancel_check:
                    cancel_check()
                item = next(iterator)
            except StopIteration:
                return False
            except CancelledError:
                cancelled = True
                return False
            future = pool.submit(_do, item)
            pending[future] = item
            return True

        for _ in range(min(threads, total)):
            if not submit_next():
                break

        while pending:
            finished, _ = wait(pending, return_when=FIRST_COMPLETED)
            for future in finished:
                item = pending.pop(future)
                path = _path(item)
                try:
                    error = future.result()
                except (CancelledError, FutureCancelledError):
                    cancelled = True
                    continue
                except Exception as exc:
                    error = str(exc)

                done += 1
                if error:
                    failed.append((path, error))
                    if file_failed_callback:
                        file_failed_callback(path, error)
                else:
                    deleted.append(path)
                    if file_deleted_callback:
                        file_deleted_callback(path)
                if progress_callback:
                    progress_callback(done, total)

            if not cancelled and cancel_check:
                try:
                    cancel_check()
                except CancelledError:
                    cancelled = True

            if cancelled:
                for future in pending:
                    future.cancel()
            else:
                for _ in finished:
                    if not submit_next():
                        break

    return deleted, failed
