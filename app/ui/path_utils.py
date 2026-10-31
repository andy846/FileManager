"""Qt-aware path checks for shell paths such as UNC server roots."""

import os

from PyQt6.QtCore import QFileInfo

from app.core.utils import extended_path, normalize_path


def is_dir_path(path):
    """Return True when *path* is a directory or a browsable shell folder.

    ``os.path.isdir`` cannot see a bare UNC server root (``\\\\server``)
    because it is a network namespace rather than a normal directory.  Qt's
    ``QFileInfo`` uses the Windows shell provider and can browse it.
    """
    text = normalize_path(path)
    if not text:
        return False
    try:
        if os.path.isdir(extended_path(text)):
            return True
    except OSError:
        pass
    try:
        return QFileInfo(text).isDir()
    except Exception:
        return False


def is_file_path(path):
    text = normalize_path(path)
    if not text:
        return False
    try:
        if os.path.isfile(extended_path(text)):
            return True
    except OSError:
        pass
    try:
        return QFileInfo(text).isFile()
    except Exception:
        return False


def start_directory(path):
    """Return a usable initial directory for QFileDialog."""
    text = normalize_path(path)
    return text if is_dir_path(text) else ""
