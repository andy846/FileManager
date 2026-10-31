"""Safe ZIP / TAR archive helpers (standard library only)."""

import os
import stat
import tarfile
import zipfile
from dataclasses import dataclass
from pathlib import PurePosixPath

from app.core.workers import CancelledError

MAX_EXTRACT_BYTES = 10 * 1024 ** 3
MAX_RATIO = 500


@dataclass
class ArchiveMember:
    name: str
    size: int = 0
    is_dir: bool = False
    mtime: float = 0.0


def archive_kind(path):
    lower = str(path).lower()
    if lower.endswith(".zip"):
        return "zip"
    if lower.endswith((".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tbz2",
                       ".tar.xz", ".txz")):
        return "tar"
    return ""


def list_archive(path):
    kind = archive_kind(path)
    members = []
    if kind == "zip":
        with zipfile.ZipFile(path) as archive:
            for info in archive.infolist():
                members.append(ArchiveMember(
                    name=info.filename,
                    size=info.file_size,
                    is_dir=info.is_dir(),
                    mtime=info.date_time and _zip_time(info.date_time) or 0.0,
                ))
    elif kind == "tar":
        with tarfile.open(path) as archive:
            for info in archive.getmembers():
                members.append(ArchiveMember(
                    name=info.name,
                    size=info.size,
                    is_dir=info.isdir(),
                    mtime=info.mtime,
                ))
    else:
        raise ValueError("不支援的壓縮檔格式（僅支援 ZIP／TAR）")
    return members


def _zip_time(date_time):
    import datetime

    try:
        return datetime.datetime(*date_time).timestamp()
    except Exception:
        return 0.0


def sanitize_member(name):
    """Return a safe relative path, or None for traversal/absolute paths."""
    text = str(name).replace("\\", "/").strip()
    if not text:
        return None
    pure = PurePosixPath(text)
    if pure.is_absolute():
        return None
    parts = [part for part in pure.parts if part not in ("", ".")]
    if not parts or any(part == ".." for part in parts):
        return None
    if any(":" in part for part in parts):
        return None
    return "/".join(parts)


def _safe_target(dest, member_name):
    relative = sanitize_member(member_name)
    if relative is None:
        return None
    target = os.path.abspath(os.path.join(dest, *relative.split("/")))
    dest_abs = os.path.abspath(dest)
    try:
        if os.path.commonpath([target, dest_abs]) != dest_abs:
            return None
    except ValueError:
        return None
    return target


def _check_bomb(path, members):
    archive_size = max(1, os.path.getsize(path))
    total = sum(member.size for member in members if not member.is_dir)
    if total > MAX_EXTRACT_BYTES:
        raise ValueError("壓縮檔解壓後超過安全大小上限")
    if total > 200 * 1024 ** 2 and total / archive_size > MAX_RATIO:
        raise ValueError("壓縮比異常，已拒絕解壓（可能的 zip bomb）")


def extract_archive(path, dest, members=None, overwrite=False,
                    control=None, progress=None):
    kind = archive_kind(path)
    if not kind:
        raise ValueError("不支援的壓縮檔格式（僅支援 ZIP／TAR）")
    selected = set(members) if members else None
    all_members = [
        member for member in list_archive(path)
        if not selected or member.name in selected
    ]
    _check_bomb(path, all_members)
    os.makedirs(dest, exist_ok=True)
    summary = {"extracted": 0, "skipped": 0, "failed": 0,
               "errors": [], "cancelled": False}
    total = len(all_members)
    try:
        if kind == "zip":
            with zipfile.ZipFile(path) as archive:
                for index, member in enumerate(all_members, 1):
                    if control is not None:
                        control.wait_if_paused()
                        control.checkpoint()
                    target = _safe_target(dest, member.name)
                    if target is None:
                        summary["skipped"] += 1
                        continue
                    if member.is_dir:
                        os.makedirs(target, exist_ok=True)
                    else:
                        if os.path.exists(target) and not overwrite:
                            summary["skipped"] += 1
                        else:
                            os.makedirs(os.path.dirname(target) or dest,
                                        exist_ok=True)
                            with archive.open(member.name) as source, \
                                    open(target, "wb") as output:
                                while True:
                                    chunk = source.read(1024 * 1024)
                                    if not chunk:
                                        break
                                    if control is not None:
                                        control.checkpoint()
                                    output.write(chunk)
                            summary["extracted"] += 1
                    if progress is not None:
                        progress(index, total, member.name)
        else:
            with tarfile.open(path) as archive:
                for index, member in enumerate(all_members, 1):
                    if control is not None:
                        control.wait_if_paused()
                        control.checkpoint()
                    target = _safe_target(dest, member.name)
                    info = archive.getmember(member.name)
                    if target is None or not (info.isfile() or info.isdir()):
                        summary["skipped"] += 1
                        continue
                    if info.isdir():
                        os.makedirs(target, exist_ok=True)
                    else:
                        if os.path.exists(target) and not overwrite:
                            summary["skipped"] += 1
                        else:
                            os.makedirs(os.path.dirname(target) or dest,
                                        exist_ok=True)
                            source = archive.extractfile(info)
                            if source is None:
                                summary["skipped"] += 1
                                continue
                            with source, open(target, "wb") as output:
                                while True:
                                    chunk = source.read(1024 * 1024)
                                    if not chunk:
                                        break
                                    if control is not None:
                                        control.checkpoint()
                                    output.write(chunk)
                            summary["extracted"] += 1
                    if progress is not None:
                        progress(index, total, member.name)
    except CancelledError:
        summary["cancelled"] = True
    return summary


def create_zip(output, sources, control=None, progress=None):
    """Create a ZIP from files/folders, preserving each source's name."""
    output = os.path.abspath(output)
    entries = []
    for source in sources:
        source = os.path.abspath(str(source))
        if not os.path.exists(source):
            continue
        if os.path.isfile(source):
            entries.append((source, os.path.basename(source)))
            continue
        if not os.path.isdir(source):
            continue
        parent = os.path.dirname(source.rstrip("\\/"))
        for root, dirs, files in os.walk(source):
            if control is not None:
                control.checkpoint()
            dirs[:] = [
                directory for directory in dirs
                if not os.path.islink(os.path.join(root, directory))
            ]
            for name in files:
                full = os.path.join(root, name)
                if os.path.islink(full) or os.path.abspath(full) == output:
                    continue
                try:
                    attrs = os.stat(full).st_file_attributes
                except OSError:
                    attrs = 0
                if attrs & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0):
                    continue
                entries.append((full, os.path.relpath(full, parent)))

    os.makedirs(os.path.dirname(output) or ".", exist_ok=True)
    summary = {"added": 0, "failed": 0, "output": output,
               "cancelled": False}
    try:
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
            for index, (path, arcname) in enumerate(entries, 1):
                if control is not None:
                    control.wait_if_paused()
                    control.checkpoint()
                try:
                    archive.write(path, arcname=arcname)
                    summary["added"] += 1
                except Exception:
                    summary["failed"] += 1
                if progress is not None:
                    progress(index, len(entries), path)
    except CancelledError:
        summary["cancelled"] = True
    return summary
