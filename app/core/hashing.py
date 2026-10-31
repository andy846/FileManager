"""Streaming file hashing helpers shared by the hash and compare modules."""

import hashlib
import os

from app.core.utils import extended_path, strip_extended_path

ALGORITHMS = ["sha256", "sha1", "md5"]
ALGORITHM_LABELS = {
    "sha256": "SHA-256",
    "sha1": "SHA-1",
    "md5": "MD5",
}
CHUNK_SIZE = 1024 * 1024


def hash_file(path, algorithm="sha256", control=None, progress=None,
              chunk_size=CHUNK_SIZE):
    """Hash a file in a streaming fashion and return the hex digest."""
    digest = hashlib.new(algorithm)
    path = extended_path(path)
    total = os.path.getsize(path)
    done = 0
    with open(path, "rb") as handle:
        while True:
            if control is not None:
                control.wait_if_paused()
                control.checkpoint()
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
            done += len(chunk)
            if progress is not None:
                progress(done, total)
    return digest.hexdigest()


def collect_files(paths, recursive=True, control=None, progress=None):
    """Yield ``(path, size)`` for files under the given paths."""
    seen = set()
    for raw in paths:
        path = os.path.abspath(str(raw))
        if not os.path.exists(extended_path(path)):
            continue
        if os.path.isfile(extended_path(path)):
            key = os.path.normcase(path)
            if key not in seen:
                seen.add(key)
                yield path, os.path.getsize(extended_path(path))
            continue
        if not os.path.isdir(extended_path(path)):
            continue
        for root, dirs, files in os.walk(extended_path(path)):
            root = strip_extended_path(root)
            if control is not None:
                control.wait_if_paused()
                control.checkpoint()
            if not recursive:
                dirs[:] = []
            dirs[:] = [
                directory for directory in dirs
                if not os.path.islink(os.path.join(root, directory))
            ]
            for name in files:
                full = os.path.join(root, name)
                key = os.path.normcase(full)
                if key in seen or os.path.islink(extended_path(full)):
                    continue
                seen.add(key)
                try:
                    size = os.path.getsize(extended_path(full))
                except OSError:
                    continue
                if progress is not None:
                    progress(full, len(seen))
                yield full, size


def hash_tree(root, algorithm="sha256", control=None):
    """Hash relative names and contents of a folder into one digest."""
    root = os.path.abspath(root)
    digest = hashlib.new(algorithm)
    files = sorted(collect_files([root], control=control), key=lambda item: item[0].lower())
    for path, _size in files:
        relative = os.path.relpath(path, root).replace("\\", "/")
        digest.update(relative.encode("utf-8", errors="replace"))
        digest.update(hash_file(path, algorithm, control=control).encode("ascii"))
    return digest.hexdigest()

