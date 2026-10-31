"""Shared pure utility functions used across all modules."""

import os
import re
import stat
import subprocess
import sys

try:
    import send2trash

    _HAS_SEND2TRASH = True
except Exception:  # pragma: no cover - optional dependency
    _HAS_SEND2TRASH = False


# ---------------------------------------------------------------------------
# File categories (dashboard charts, browser type column)
# ---------------------------------------------------------------------------

CATEGORY_ORDER = [
    "documents", "images", "video", "audio", "archives",
    "installers", "code", "other",
]

CATEGORY_LABELS = {
    "documents": "文件",
    "images": "圖片",
    "video": "影片",
    "audio": "音訊",
    "archives": "壓縮檔",
    "installers": "安裝程式",
    "code": "程式碼",
    "other": "其他",
}

_CATEGORY_EXTENSIONS = {
    "documents": {
        "pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "txt", "md",
        "rtf", "odt", "ods", "odp", "csv", "epub", "mobi", "ps", "djvu",
    },
    "images": {
        "jpg", "jpeg", "png", "gif", "bmp", "webp", "tif", "tiff", "heic",
        "svg", "ico", "psd", "raw", "cr2", "nef", "arw", "dng",
    },
    "video": {
        "mp4", "mkv", "avi", "mov", "wmv", "flv", "webm", "m4v", "mpg",
        "mpeg", "ts", "3gp", "ogv",
    },
    "audio": {
        "mp3", "wav", "flac", "aac", "ogg", "m4a", "wma", "opus", "aiff",
        "mid", "midi",
    },
    "archives": {
        "zip", "rar", "7z", "tar", "gz", "bz2", "xz", "iso", "cab", "lzh",
        "lzma", "arj", "wim", "z",
    },
    "installers": {
        "exe", "msi", "msix", "appx", "apk", "dmg", "pkg", "deb", "rpm",
    },
    "code": {
        "py", "js", "tsx", "jsx", "java", "c", "cpp", "h", "hpp", "cs",
        "go", "rs", "rb", "php", "html", "htm", "css", "scss", "json",
        "xml", "yaml", "yml", "ini", "toml", "sh", "ps1", "bat", "sql",
        "kt", "swift", "vue", "svelte", "lua",
    },
}

_EXT_TO_CATEGORY = {
    ext: category
    for category, extensions in _CATEGORY_EXTENSIONS.items()
    for ext in extensions
}


def file_category(name):
    """Return the display category key for a filename or path."""
    ext = os.path.splitext(str(name))[1].lower().lstrip(".")
    return _EXT_TO_CATEGORY.get(ext, "other")


def file_extension(name):
    """Return a lower-case extension without the leading dot."""
    return os.path.splitext(str(name))[1].lower().lstrip(".")



def format_size(num_bytes):
    """Return a human readable file size string (Traditional Chinese units)."""
    try:
        num_bytes = float(num_bytes)
    except (TypeError, ValueError):
        num_bytes = 0.0
    if num_bytes < 0:
        num_bytes = 0.0
    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    size = num_bytes
    idx = 0
    while size >= 1024 and idx < len(units) - 1:
        size /= 1024.0
        idx += 1
    if idx == 0:
        return f"{int(size)} {units[idx]}"
    return f"{size:.1f} {units[idx]}"


def format_datetime(timestamp):
    """Format a unix timestamp to 'YYYY-MM-DD HH:MM:SS' or '未知' on error."""
    if timestamp is None:
        return "未知"
    try:
        import datetime

        return datetime.datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return "未知"


def normalize_path(path):
    """Return *path* with native Windows separators.

    Qt file dialogs and ``QFileSystemModel`` return forward slashes, while
    ``os.path.join`` appends backslashes on Windows.  Mixed paths such as
    ``C:/Users/name/folder\\file.txt`` look wrong in the UI and are hard to
    copy into other tools.  This helper normalises separators while keeping
    drive roots, UNC paths and long-path prefixes intact.
    """
    if path is None:
        return ""
    text = str(path).strip().strip('"').strip()
    if not text:
        return ""

    if sys.platform.startswith("win"):
        prefix = ""
        if text.startswith("\\\\?\\UNC\\"):
            prefix = "\\\\?\\UNC\\"
            text = text[len(prefix):]
        elif text.startswith("\\\\?\\"):
            prefix = "\\\\?\\"
            text = text[len(prefix):]
        text = text.replace("/", "\\")
        text = os.path.normpath(text)
        result = prefix + text
        # normpath keeps the trailing separator on a UNC share root; strip it
        # so ``\\server\share\`` and ``\\server\share`` compare consistently.
        if result.endswith("\\") and not re.fullmatch(
            r"(?:\\\\\?\\)?[A-Za-z]:\\", result
        ):
            result = result.rstrip("\\") or result
        return result
    return os.path.normpath(text)


def path_name(path):
    """Return the final component of *path*, including UNC share roots."""
    text = normalize_path(path).rstrip("\\")
    if len(text) == 2 and text[1] == ":":
        return text + "\\"
    parts = [part for part in text.split("\\") if part]
    return parts[-1] if parts else text


def extended_path(path):
    """Return a Windows long-path-safe path for file-system calls.

    The ``\\\\?\\`` prefix bypasses MAX_PATH and is also required for some
    network operations.  Display paths should keep using :func:`normalize_path`;
    this helper is only for OS/API calls.
    """
    text = normalize_path(path)
    if not text or not sys.platform.startswith("win"):
        return text
    if text.startswith("\\\\?\\"):
        return text
    if text.startswith("\\\\"):
        return "\\\\?\\UNC\\" + text[2:]
    if os.path.isabs(text):
        return "\\\\?\\" + text
    return text


def strip_extended_path(path):
    """Remove a Windows ``\\\\?\\`` long-path prefix for display/storage."""
    text = str(path)
    if text.startswith("\\\\?\\UNC\\"):
        return "\\\\" + text[len("\\\\?\\UNC\\"):]
    if text.startswith("\\\\?\\"):
        return text[len("\\\\?\\"):]
    return text


def is_dir_fs(path):
    """Return True for a directory, including paths beyond MAX_PATH."""
    try:
        return os.path.isdir(extended_path(path))
    except OSError:
        return False


def is_unc_path(path):
    """Return True for a Windows UNC path (``\\\\server\\share``)."""
    return normalize_path(path).startswith("\\\\")


def is_unc_server_root(path):
    """Return True when *path* is a bare UNC server root (``\\\\server``)."""
    text = normalize_path(path)
    if not text.startswith("\\\\"):
        return False
    body = text[2:]
    if body.startswith("?\\UNC\\"):
        body = body[len("?\\UNC\\"):]
    elif body.startswith("?\\"):
        return False
    return bool(body) and "\\" not in body


def server_from_path(path):
    """Return the UNC server root for *path*, or an empty string."""
    text = normalize_path(path)
    if not text.startswith("\\\\"):
        return ""
    body = text[2:]
    if body.startswith("?\\UNC\\"):
        body = body[len("?\\UNC\\"):]
    elif body.startswith("?\\"):
        return ""
    server = body.split("\\", 1)[0]
    return f"\\\\{server}" if server else ""


def short_path(path, limit=72):
    """Truncate a long path in the middle for display."""
    path = normalize_path(path)
    if len(path) <= limit:
        return path
    head = path[: limit // 2 - 1]
    tail = path[-(limit // 2 - 1):]
    return f"{head}…{tail}"


def parse_size_to_bytes(value, unit="MB"):
    """Convert a size value + unit into bytes. Falls back to bytes on error."""
    factors = {
        "B": 1,
        "KB": 1024,
        "MB": 1024 ** 2,
        "GB": 1024 ** 3,
        "TB": 1024 ** 4,
    }
    try:
        value = float(value)
    except (TypeError, ValueError):
        value = 0.0
    if value < 0:
        value = 0.0
    unit = str(unit).upper()
    factor = factors.get(unit, factors["MB"])
    return int(value * factor)


def _glob_to_regex(pattern):
    """Convert a glob pattern to a regex, escaping special characters."""
    parts = []
    for ch in pattern:
        if ch == "*":
            parts.append(".*")
        elif ch == "?":
            parts.append(".")
        else:
            parts.append(re.escape(ch))
    return "".join(parts)


def matches_exclusion(name, patterns):
    """Return True if *name* matches any exclusion pattern.

    Patterns may be filename globs (``*.tmp``) or folder substrings
    (``temp/``) and are matched case-insensitively.
    """
    if not patterns:
        return False
    lower_name = str(name).lower().replace("\\", "/")
    base = lower_name.rsplit("/", 1)[-1]
    for raw in patterns:
        pattern = str(raw).strip().lower()
        if not pattern:
            continue
        # Folder substring matcher (ends with separator).
        if pattern.endswith("/") or pattern.endswith("\\"):
            if pattern.rstrip("/\\") in lower_name:
                return True
            continue
        if "*" in pattern or "?" in pattern:
            try:
                rx = _glob_to_regex(pattern)
                if re.fullmatch(rx, lower_name) or re.fullmatch(rx, base):
                    return True
            except re.error:
                pass
        else:
            # Plain substring matcher.
            if pattern in lower_name:
                return True
    return False


def normalize_path_for_trash(path):
    """Normalise a path so send2trash accepts long / UNC paths."""
    path = normalize_path(os.path.abspath(str(path)))
    return extended_path(path)


def send_to_trash(path):
    """Move *path* to the operating system recycle bin / trash.

    Returns ``(ok, error_message)``. If ``send2trash`` is unavailable the
    operation is refused rather than falling back to a permanent delete:
    callers (delete / duplicate cleanup / overwrite) all assume the file
    can still be recovered, so silently destroying it would be data loss.
    """
    if not _HAS_SEND2TRASH:
        return False, "send2trash 未安裝，已拒絕刪除以避免永久遺失資料"
    try:
        send2trash.send2trash(normalize_path_for_trash(path))
        return True, ""
    except Exception as exc:
        return False, str(exc)


def quick_digest(path, chunk=65536):
    """Return a cheap content digest (size + first/last chunk) or None.

    Used to verify a copy without re-reading both entire files. Reading the
    head and tail blocks catches truncated, empty or corrupted transfers
    while keeping verification close to O(1) for large files.
    """
    import hashlib

    try:
        path = extended_path(path)
        size = os.path.getsize(path)
        h = hashlib.blake2b(digest_size=16)
        with open(path, "rb") as f:
            h.update(f.read(chunk))
            if size > chunk:
                f.seek(max(0, size - chunk))
                h.update(f.read(chunk))
        h.update(str(size).encode("ascii"))
        return h.digest()
    except OSError:
        return None


def is_hidden(path):
    """Return True if *path* is a hidden file (Windows attribute or dotfile)."""
    name = os.path.basename(str(path))
    if name.startswith("."):
        return True
    if sys.platform.startswith("win"):
        try:
            return bool(
                os.stat(extended_path(path)).st_file_attributes
                & stat.FILE_ATTRIBUTE_HIDDEN
            )
        except Exception:
            return False
    return False


def safe_stat(path):
    """Return os.stat result or None on failure."""
    try:
        return os.stat(extended_path(path))
    except Exception:
        return None


def open_path(path):
    """Open a file or folder with the operating system's default handler.

    Returns ``(ok, error_message)`` and never raises, so UI callers can show a
    friendly message instead of crashing on a broken file association.
    """
    path = str(path)
    try:
        if not os.path.exists(path):
            return False, "路徑不存在"
        if sys.platform.startswith("win"):
            startfile = getattr(os, "startfile", None)
            if startfile is None:  # pragma: no cover - Windows always has it
                return False, "此系統不支援開啟檔案"
            startfile(path)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
        return True, ""
    except Exception as exc:
        return False, str(exc)


def reveal_in_explorer(path):
    """Select *path* in Windows File Explorer (or open its folder)."""
    path = os.path.abspath(str(path))
    try:
        if not os.path.exists(path):
            return False, "路徑不存在"
        if sys.platform.startswith("win"):
            if os.path.isdir(path):
                subprocess.Popen(["explorer", path])
            else:
                # explorer.exe expects the /select argument as one token.
                subprocess.Popen(f'explorer /select,"{path}"')
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", path])
        else:
            folder = path if os.path.isdir(path) else os.path.dirname(path)
            subprocess.Popen(["xdg-open", folder])
        return True, ""
    except Exception as exc:
        return False, str(exc)

