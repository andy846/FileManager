"""Shared constants for the unified File Manager application."""

import os

APP_NAME = "FileManager 檔案管理系統"
APP_TITLE = "檔案管理系統"
APP_VERSION = "2.1.0"
# Must stay in sync with filevers/prodvers in version_info.txt; enforced by
# tests/test_packaging.py so the exe metadata cannot drift from the UI.
APP_VERSION_TUPLE = (2, 1, 0, 0)
ORG_NAME = "FileManager"
APP_ID = "FileManager/2.1"

ASSETS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets")

# Maximum number of recent paths kept per field.
MAX_RECENT = 10

# Default number of worker threads.
DEFAULT_THREADS = 4
MIN_THREADS = 1
MAX_THREADS = 16

# Throttle interval (seconds) for stats emission.
STATS_INTERVAL = 0.25

# Chunk size for atomic copy (512 KiB).
COPY_CHUNK_SIZE = 512 * 1024

# Default history cap.
MAX_HISTORY_RECORDS = 500

# Module identifiers (for history typing).
MODULE_DASHBOARD = "dashboard"
MODULE_BROWSER = "browser"
MODULE_COPY = "copy"
MODULE_MOVE = "move"
MODULE_REMOVE = "remove"
MODULE_DUPLICATES = "duplicates"
MODULE_RENAME = "rename"
MODULE_SEARCH = "search"
MODULE_COMPARE = "compare"
MODULE_HASH = "hash"
MODULE_ARCHIVE = "archive"
MODULE_SETTINGS = "settings"

# Human-readable module names shared by the dashboard and history dialog.
MODULE_LABELS = {
    MODULE_DASHBOARD: "儀表板",
    MODULE_BROWSER: "檔案瀏覽器",
    MODULE_SEARCH: "檔案搜尋",
    MODULE_COPY: "批量複製",
    MODULE_MOVE: "批量搬移",
    MODULE_REMOVE: "批量刪除",
    MODULE_DUPLICATES: "重複檔案",
    MODULE_RENAME: "批次改名",
    MODULE_COMPARE: "資料夾比對",
    MODULE_HASH: "雜湊工具",
    MODULE_ARCHIVE: "壓縮檔",
    MODULE_SETTINGS: "設定",
}

# Titles used by navigation surfaces (settings start page, command palette).
# History records intentionally keep MODULE_LABELS so copy/move stay distinct.
MODULE_NAV_LABELS = dict(MODULE_LABELS)
MODULE_NAV_LABELS[MODULE_COPY] = "批量複製 / 搬移"

MODULE_ICONS = {
    MODULE_DASHBOARD: "dashboard",
    MODULE_BROWSER: "browser",
    MODULE_SEARCH: "search",
    MODULE_COPY: "copy",
    MODULE_MOVE: "move",
    MODULE_REMOVE: "trash",
    MODULE_DUPLICATES: "duplicates",
    MODULE_RENAME: "rename",
    MODULE_COMPARE: "compare",
    MODULE_HASH: "hash",
    MODULE_ARCHIVE: "archive",
    MODULE_SETTINGS: "settings",
}

# Sidebar groups: (heading, module ids)
NAV_GROUPS = [
    ("工作區", [MODULE_DASHBOARD, MODULE_BROWSER, MODULE_SEARCH]),
    ("批量處理", [MODULE_COPY, MODULE_REMOVE,
                  MODULE_DUPLICATES, MODULE_RENAME]),
    ("工具", [MODULE_COMPARE, MODULE_HASH, MODULE_ARCHIVE, MODULE_SETTINGS]),
]

SETTINGS_VERSION = 2
