"""Streaming filename/size/date search used by the search module."""

import fnmatch
import os
import re
import stat
from dataclasses import dataclass, field

from app.core.models import FileInfo
from app.core.utils import (
    extended_path, matches_exclusion, normalize_path, strip_extended_path,
)


@dataclass
class SearchOptions:
    roots: list = field(default_factory=list)
    name: str = ""
    use_regex: bool = False
    case_sensitive: bool = False
    min_size: int = 0
    max_size: int = 0
    modified_after: float = 0.0
    modified_before: float = 0.0
    extensions: list = field(default_factory=list)
    exclude: list = field(default_factory=list)
    recursive: bool = True
    include_hidden: bool = False


def _name_matcher(options):
    query = options.name.strip()
    if not query:
        return lambda name: True
    if options.use_regex:
        flags = 0 if options.case_sensitive else re.IGNORECASE
        try:
            regex = re.compile(query, flags)
        except re.error:
            regex = re.compile(re.escape(query), flags)
        return lambda name: bool(regex.search(name))
    query_lower = query if options.case_sensitive else query.lower()
    if "*" in query or "?" in query:
        if options.case_sensitive:
            return lambda name: fnmatch.fnmatchcase(name, query)
        return lambda name: fnmatch.fnmatch(name.lower(), query_lower)
    if options.case_sensitive:
        return lambda name: query in name
    return lambda name: query_lower in name.lower()


def _entry_is_reparse(entry):
    try:
        if entry.is_symlink():
            return True
        stat_result = entry.stat(follow_symlinks=False)
        attrs = getattr(stat_result, "st_file_attributes", 0)
        return bool(attrs & getattr(
            stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0
        ))
    except OSError:
        return True


def iter_search(options, control=None, progress=None):
    """Yield :class:`FileInfo` objects matching *options*.

    Uses ``os.scandir`` and the cached ``DirEntry.stat()`` result so each
    entry needs one filesystem round-trip instead of the old
    ``os.walk`` + separate ``os.stat`` combination.
    """
    matcher = _name_matcher(options)
    extensions = {
        str(ext).lower().lstrip(".") for ext in options.extensions
        if str(ext).strip()
    }
    scanned = 0
    matched = 0
    for root in options.roots:
        root = normalize_path(os.path.abspath(str(root)))
        if not os.path.isdir(extended_path(root)):
            continue
        stack = [root]
        while stack:
            if control is not None:
                control.wait_if_paused()
                control.checkpoint()
            current = stack.pop()
            try:
                entries = os.scandir(extended_path(current))
            except OSError:
                continue
            with entries:
                for entry in entries:
                    if control is not None:
                        control.wait_if_paused()
                        control.checkpoint()
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            if not options.recursive:
                                continue
                            if _entry_is_reparse(entry):
                                continue
                            dir_path = normalize_path(
                                strip_extended_path(entry.path)
                            )
                            if matches_exclusion(
                                    dir_path, options.exclude):
                                continue
                            stack.append(dir_path)
                            continue
                        if not entry.is_file(follow_symlinks=False):
                            continue
                        st = entry.stat(follow_symlinks=False)
                    except OSError:
                        continue

                    scanned += 1
                    if progress is not None and scanned % 500 == 0:
                        progress(scanned, matched)
                    name = entry.name
                    full = normalize_path(strip_extended_path(entry.path))
                    if not options.include_hidden:
                        attrs = getattr(st, "st_file_attributes", 0)
                        if name.startswith(".") or attrs & getattr(
                                stat, "FILE_ATTRIBUTE_HIDDEN", 0):
                            continue
                    if matches_exclusion(full, options.exclude):
                        continue
                    if not matcher(name):
                        continue
                    if options.min_size and st.st_size < options.min_size:
                        continue
                    if options.max_size and st.st_size > options.max_size:
                        continue
                    if (options.modified_after
                            and st.st_mtime < options.modified_after):
                        continue
                    if (options.modified_before
                            and st.st_mtime > options.modified_before):
                        continue
                    if extensions:
                        extension = os.path.splitext(name)[1].lower().lstrip(".")
                        if extension not in extensions:
                            continue
                    matched += 1
                    if progress is not None and matched % 25 == 0:
                        progress(scanned, matched)
                    yield FileInfo(
                        path=full, size=st.st_size, modified=st.st_mtime,
                    )
    if progress is not None:
        progress(scanned, matched)
