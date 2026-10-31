"""Windows drive metadata and UNC network helpers.

The module is intentionally UI-free so it can be tested and reused from
background workers.  All Windows APIs are loaded lazily through ``ctypes``;
on other platforms the drive list falls back to a single root.
"""

import ctypes
import os
import shutil
import sys
from ctypes import wintypes

from app.core.i18n import tr
from app.core.utils import (
    extended_path, is_unc_path, is_unc_server_root, normalize_path,
    strip_extended_path,
)

DRIVE_TYPE_KEYS = {
    2: "removable",
    3: "fixed",
    4: "network",
    5: "cdrom",
    6: "ram",
}

NETWORK_ERROR_MESSAGES = {
    5: "存取被拒，請確認帳號權限",
    53: "找不到網路路徑，請確認伺服器名稱或 IP",
    67: "找不到網路名稱，共享資料夾可能不存在",
    86: "帳號或密碼錯誤",
    121: "網路連線逾時",
    64: "網路名稱已中斷，請重新連線",
    161: "找不到網路路徑，請確認伺服器與共享名稱",
    1203: "找不到可用的網路提供者或路徑",
    1219: "此伺服器已有使用其他帳號的連線，請先中斷原連線",
    1231: "網路無法連線，請確認網路狀態",
    1326: "登入失敗，請確認帳號與密碼",
    2250: "找不到網路連線，請確認網路磁碟仍存在",
}


class NetworkError(RuntimeError):
    """A Windows network error with an actionable message."""

    def __init__(self, code, message):
        self.code = int(code or 0)
        super().__init__(message or f"網路錯誤 ({self.code})")


class _NETRESOURCEW(ctypes.Structure):
    _fields_ = [
        ("dwScope", wintypes.DWORD),
        ("dwType", wintypes.DWORD),
        ("dwDisplayType", wintypes.DWORD),
        ("dwUsage", wintypes.DWORD),
        ("lpLocalName", wintypes.LPWSTR),
        ("lpRemoteName", wintypes.LPWSTR),
        ("lpComment", wintypes.LPWSTR),
        ("lpProvider", wintypes.LPWSTR),
    ]


class _SHARE_INFO_1(ctypes.Structure):
    _fields_ = [
        ("shi50_netname", wintypes.LPWSTR),
        ("shi50_type", wintypes.DWORD),
        ("shi50_remark", wintypes.LPWSTR),
    ]


class _WindowsApi:
    def __init__(self):
        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self.mpr = ctypes.WinDLL("mpr", use_last_error=True)
        self.netapi32 = ctypes.WinDLL("netapi32", use_last_error=True)

        self.kernel32.GetLogicalDrives.restype = wintypes.DWORD
        self.kernel32.GetDriveTypeW.argtypes = [wintypes.LPCWSTR]
        self.kernel32.GetDriveTypeW.restype = wintypes.UINT
        self.kernel32.GetVolumeInformationW.argtypes = [
            wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.DWORD),
            ctypes.POINTER(wintypes.DWORD), wintypes.LPWSTR, wintypes.DWORD,
        ]
        self.kernel32.GetVolumeInformationW.restype = wintypes.BOOL

        self.mpr.WNetGetConnectionW.argtypes = [
            wintypes.LPCWSTR, wintypes.LPWSTR,
            ctypes.POINTER(wintypes.DWORD),
        ]
        self.mpr.WNetGetConnectionW.restype = wintypes.DWORD
        self.mpr.WNetAddConnection2W.argtypes = [
            ctypes.POINTER(_NETRESOURCEW), wintypes.LPCWSTR,
            wintypes.LPCWSTR, wintypes.DWORD,
        ]
        self.mpr.WNetAddConnection2W.restype = wintypes.DWORD
        self.mpr.WNetCancelConnection2W.argtypes = [
            wintypes.LPCWSTR, wintypes.DWORD, wintypes.BOOL,
        ]
        self.mpr.WNetCancelConnection2W.restype = wintypes.DWORD

        self.netapi32.NetShareEnum.argtypes = [
            wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p),
            wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
            ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.DWORD),
        ]
        self.netapi32.NetShareEnum.restype = wintypes.DWORD
        self.netapi32.NetApiBufferFree.argtypes = [ctypes.c_void_p]
        self.netapi32.NetApiBufferFree.restype = wintypes.DWORD


_API = None


def _api():
    global _API
    if not sys.platform.startswith("win"):
        return None
    if _API is None:
        try:
            _API = _WindowsApi()
        except OSError:
            return None
    return _API


def friendly_network_error(code):
    """Return a readable message for a Windows network error code."""
    try:
        code = int(code)
    except (TypeError, ValueError):
        code = 0
    return tr(NETWORK_ERROR_MESSAGES.get(
        code, f"網路錯誤 ({code})" if code else "網路錯誤"
    ))


def normalize_unc_server(value):
    """Normalise user input such as ``10.8.17.66`` to ``\\\\10.8.17.66``."""
    text = str(value or "").strip().strip('"').strip()
    if not text:
        return ""
    if text.startswith("\\\\?\\UNC\\"):
        text = text[len("\\\\?\\UNC\\"):]
    text = text.replace("/", "\\").strip("\\")
    server = text.split("\\", 1)[0]
    return f"\\\\{server}" if server else ""


def _share_name(path):
    text = normalize_path(path).rstrip("\\")
    parts = [part for part in text.split("\\") if part]
    return parts[-1] if parts else text


def _volume_info(root):
    """Return ``(label, filesystem)`` for a drive or UNC share."""
    api = _api()
    text = normalize_path(root)
    if api is None or not text or is_unc_server_root(text):
        return "", ""
    if not text.endswith("\\"):
        text += "\\"
    label = ctypes.create_unicode_buffer(261)
    filesystem = ctypes.create_unicode_buffer(261)
    serial = wintypes.DWORD()
    max_length = wintypes.DWORD()
    flags = wintypes.DWORD()
    try:
        ok = api.kernel32.GetVolumeInformationW(
            text, label, 261, ctypes.byref(serial),
            ctypes.byref(max_length), ctypes.byref(flags),
            filesystem, 261,
        )
    except OSError:
        return "", ""
    if not ok:
        return "", ""
    return label.value, filesystem.value


def _mapped_unc(letter):
    api = _api()
    if api is None:
        return ""
    buffer = ctypes.create_unicode_buffer(2048)
    size = wintypes.DWORD(len(buffer))
    try:
        result = api.mpr.WNetGetConnectionW(
            f"{letter}:", buffer, ctypes.byref(size)
        )
    except OSError:
        return ""
    if result != 0:
        return ""
    return normalize_path(buffer.value)


def _make_entry(root, letter="", label="", filesystem="",
                kind="fixed", unc="", is_extra=False):
    root = normalize_path(root)
    display_label = label or (_share_name(unc) if unc else "")
    if letter:
        display_name = (
            f"{display_label} ({letter}:)" if display_label else f"{letter}:"
        )
    else:
        display_name = display_label or root
    return {
        "root": root,
        "letter": letter,
        "label": label,
        "display_name": display_name,
        "filesystem": filesystem,
        "kind": kind,
        "unc": normalize_path(unc) if unc else "",
        "is_network": kind == "network",
        "is_extra": bool(is_extra),
        "total": 0,
        "used": 0,
        "free": 0,
        "error": "",
    }


def list_drive_entries(extra_roots=()):
    """List local, mapped and explicitly configured network locations.

    The call only reads metadata; disk usage is collected by
    :func:`collect_drive_infos` inside a worker thread.
    """
    api = _api()
    entries = []
    if api is None:
        entry = _make_entry("/", label="Root", kind="fixed")
        entries.append(entry)
        return entries

    try:
        mask = int(api.kernel32.GetLogicalDrives())
    except OSError:
        mask = 0

    seen_roots = set()
    seen_uncs = set()
    for index in range(26):
        if not mask & (1 << index):
            continue
        letter = chr(ord("A") + index)
        root = f"{letter}:\\"
        try:
            drive_type = int(api.kernel32.GetDriveTypeW(root))
        except OSError:
            continue
        if drive_type == 1:  # DRIVE_NO_ROOT_DIR
            continue
        kind = DRIVE_TYPE_KEYS.get(drive_type, "unknown")
        label, filesystem = _volume_info(root)
        unc = _mapped_unc(letter) if kind == "network" else ""
        entry = _make_entry(
            root, letter=letter, label=label, filesystem=filesystem,
            kind=kind, unc=unc,
        )
        entries.append(entry)
        seen_roots.add(os.path.normcase(os.path.normpath(root)))
        if unc:
            seen_uncs.add(os.path.normcase(os.path.normpath(unc)))

    for raw in extra_roots or ():
        root = normalize_path(raw)
        if not root:
            continue
        key = os.path.normcase(os.path.normpath(root))
        if key in seen_roots:
            continue
        if is_unc_path(root) and key in seen_uncs:
            continue
        label, filesystem = _volume_info(root)
        entry = _make_entry(
            root, label=label, filesystem=filesystem, kind="network",
            unc=root, is_extra=True,
        )
        entries.append(entry)
        seen_roots.add(key)
        if is_unc_path(root):
            seen_uncs.add(key)
    return entries


def collect_drive_infos(extra_roots=()):
    """Return drive metadata plus usage; safe to call from a QThread."""
    entries = list_drive_entries(extra_roots)
    for entry in entries:
        try:
            total, used, free = shutil.disk_usage(entry["root"])
            entry.update(total=total, used=used, free=free, error="")
        except Exception as exc:
            code = getattr(exc, "winerror", None)
            message = friendly_network_error(code) if code else str(exc)
            entry.update(total=0, used=0, free=0, error=message)
    return entries


def list_server_shares(server, include_special=False):
    """Return disk shares exposed by *server*.

    Admin/IPC shares (``C$``, ``ADMIN$``, ``IPC$`` ...) are hidden unless
    *include_special* is true.  Raises :class:`NetworkError` on failure.
    """
    api = _api()
    server = normalize_unc_server(server)
    if api is None:
        raise NetworkError(0, "此系統不支援 Windows 網路共享")
    if not server:
        raise NetworkError(0, "請輸入伺服器名稱或 IP")

    buffer = ctypes.c_void_p()
    read = wintypes.DWORD()
    total = wintypes.DWORD()
    resume = wintypes.DWORD()
    try:
        result = api.netapi32.NetShareEnum(
            server, 1, ctypes.byref(buffer), 0xFFFFFFFF,
            ctypes.byref(read), ctypes.byref(total), ctypes.byref(resume),
        )
        if result != 0:
            raise NetworkError(result, friendly_network_error(result))
        shares = []
        if buffer.value:
            array = ctypes.cast(buffer, ctypes.POINTER(_SHARE_INFO_1))
            for index in range(read.value):
                item = array[index]
                name = item.shi50_netname or ""
                share_type = int(item.shi50_type)
                special = bool(share_type & 0x80000000) or name.endswith("$")
                is_disk = (share_type & 0xFF) == 0
                if not is_disk:
                    continue
                if special and not include_special:
                    continue
                shares.append({
                    "name": name,
                    "path": f"{server}\\{name}",
                    "comment": item.shi50_remark or "",
                    "special": special,
                })
        shares.sort(key=lambda item: item["name"].casefold())
        return shares
    finally:
        if buffer.value:
            api.netapi32.NetApiBufferFree(buffer)


def connect_network_share(path, username="", password=""):
    """Connect to a UNC share, optionally with credentials.

    Returns ``(ok, error_message)``.  The password is only passed to Windows
    for this temporary connection and is never stored by the application.
    """
    path = normalize_path(path)
    if not is_unc_path(path):
        return False, "請輸入 UNC 網路路徑（\\\\server\\share）"
    if is_unc_server_root(path):
        return False, "這是伺服器根目錄，請選擇共享資料夾"
    if os.path.isdir(path):
        return True, ""

    api = _api()
    if api is None:
        return False, "此系統不支援 Windows 網路共享"
    resource = _NETRESOURCEW()
    resource.dwType = 1  # RESOURCETYPE_DISK
    resource.lpRemoteName = path
    try:
        result = api.mpr.WNetAddConnection2W(
            ctypes.byref(resource),
            password or None,
            username or None,
            0x00000004,  # CONNECT_TEMPORARY
        )
    except OSError as exc:
        return False, str(exc)
    if result == 0:
        if os.path.isdir(path):
            return True, ""
        return False, "已建立連線，但仍無法讀取此共享"
    if result == 1219 and os.path.isdir(path):
        return True, ""
    return False, friendly_network_error(result)


def ensure_network_share(path):
    """Make sure a UNC share is reachable before an operation starts."""
    path = normalize_path(path)
    if not is_unc_path(path):
        return False, "不是網路路徑"
    if is_unc_server_root(path):
        return False, "這是伺服器根目錄，請選擇共享資料夾"
    if os.path.isdir(path):
        return True, ""
    return connect_network_share(path)


def unc_for_path(path):
    """Return the mapped UNC target for a drive path, or an empty string."""
    text = normalize_path(path)
    if not text or not text[1:2] == ":":
        return ""
    return _mapped_unc(text[0].upper())


def unc_share_root(path):
    """Return ``\\\\server\\share`` for a UNC path, or an empty string."""
    text = strip_extended_path(normalize_path(path))
    if not is_unc_path(text):
        return ""
    parts = [part for part in text[2:].split("\\") if part]
    if len(parts) < 2:
        return ""
    return f"\\\\{parts[0]}\\{parts[1]}"


def ensure_reachable(path):
    """Best-effort reconnect for a mapped drive or UNC share."""
    text = normalize_path(path)
    if not text:
        return False
    if is_unc_path(text):
        share = unc_share_root(text) or text
        ok, _error = ensure_network_share(share)
        return ok or os.path.exists(extended_path(text))
    unc = unc_for_path(text)
    if unc:
        ok, _error = ensure_network_share(unc)
        return ok
    return os.path.exists(extended_path(text))
