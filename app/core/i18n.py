"""Lightweight English localization for the legacy Chinese UI strings.

The application was originally written with Chinese display strings.  Rather
than rewriting every widget call, this module keeps a display catalog and a
small localizer that is applied to visible widgets.  Chinese mode remains the
original source strings.  New code should prefer ``tr()`` for display text.
"""

import json
import os
import re
import sys

from PyQt6.QtCore import QEvent, QLibraryInfo, QLocale, QObject, QTimer, QTranslator
from PyQt6.QtWidgets import (
    QAbstractButton, QComboBox, QDoubleSpinBox, QGroupBox, QLabel, QLineEdit,
    QListWidget, QMenu, QSpinBox, QTabWidget, QTableWidget, QTreeWidget,
    QWidget,
)

LANGUAGE_EN = "en"
LANGUAGE_ZH = "zh_TW"
DEFAULT_LANGUAGE = LANGUAGE_EN

# Shared file-dialog filters.  Chinese source strings are translated by the
# English catalog, so both languages stay consistent.
FILE_FILTERS = {
    "csv": "CSV 檔案 (*.csv)",
    "excel": "Excel 活頁簿 (*.xlsx)",
    "zip": "ZIP 壓縮檔 (*.zip)",
    "archive": (
        "壓縮檔 (*.zip *.tar *.tar.gz *.tgz *.tar.bz2 *.tbz2 "
        "*.tar.xz *.txz)"
    ),
}

_language = DEFAULT_LANGUAGE
_catalog = {}
_fragment_items = []


def _catalog_path():
    names = ["en.json"]
    roots = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        roots.append(meipass)
    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(os.path.abspath(sys.executable))
        roots.extend([exe_dir, os.path.join(exe_dir, "_internal")])
    roots.append(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)
    ))))
    for root in roots:
        path = os.path.join(root, "assets", "i18n", names[0])
        if os.path.isfile(path):
            return path
    return ""


def _load_catalog():
    global _catalog, _fragment_items
    if _catalog:
        return
    path = _catalog_path()
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        _catalog = {str(key): str(value) for key, value in data.items()}
        _fragment_items = sorted(
            _catalog.items(), key=lambda item: len(item[0]), reverse=True
        )
    except Exception:
        _catalog = {}
        _fragment_items = []


def set_language(language):
    global _language
    _language = LANGUAGE_ZH if language == LANGUAGE_ZH else LANGUAGE_EN
    _load_catalog()
    return _language


def language():
    return _language


def file_filter(kind):
    """Return the localized file-dialog filter for *kind*."""
    return tr(FILE_FILTERS.get(kind, ""))


def _qt_translation_roots():
    roots = [QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)]
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        roots.append(os.path.join(meipass, "PyQt6", "Qt6", "translations"))
    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(os.path.abspath(sys.executable))
        roots.extend([
            os.path.join(exe_dir, "_internal", "PyQt6", "Qt6", "translations"),
            os.path.join(exe_dir, "PyQt6", "Qt6", "translations"),
        ])
    seen = set()
    result = []
    for root in roots:
        if root and root not in seen:
            seen.add(root)
            result.append(root)
    return result


def apply_locale():
    """Make Qt's date/number widgets follow the active interface language."""
    if _language == LANGUAGE_ZH:
        QLocale.setDefault(QLocale(
            QLocale.Language.Chinese, QLocale.Country.Taiwan
        ))
    else:
        QLocale.setDefault(QLocale(
            QLocale.Language.English, QLocale.Country.UnitedStates
        ))


def install_qt_translations(app):
    """Install Qt's built-in translations for the active language.

    Without this, QMessageBox standard buttons, line-edit context menus and
    file-dialog chrome stay in English even when the application is in
    Chinese.  The translator is kept on the application object so PyQt does
    not garbage-collect it.
    """
    remove_qt_translations(app)
    apply_locale()
    if _language != LANGUAGE_ZH:
        return None
    translator = QTranslator(app)
    for root in _qt_translation_roots():
        for name in ("qt_zh_TW", "qtbase_zh_TW"):
            if translator.load(name, root):
                app.installTranslator(translator)
                app._qt_translator = translator
                return translator
    return None


def remove_qt_translations(app):
    existing = getattr(app, "_qt_translator", None)
    if existing is not None:
        app.removeTranslator(existing)
        app._qt_translator = None


def tr(text, **kwargs):
    """Translate a display string to the active language."""
    text = str(text)
    if _language != LANGUAGE_EN or not _contains_cjk(text):
        if kwargs:
            try:
                return text.format(**kwargs)
            except (KeyError, ValueError):
                pass
        return text
    _load_catalog()
    translated = _catalog.get(text)
    if translated is None:
        translated = _translate_pattern(text)
    if translated is None:
        translated = _translate_phrases(text)
    if translated is None:
        translated = _translate_fragments(text)
    if translated is None:
        return text
    translated = _fix_plurals(translated)
    if kwargs:
        try:
            return _fix_plurals(translated.format(**kwargs))
        except (KeyError, ValueError):
            return translated
    return translated


def _fix_plurals(text):
    for plural, singular in (
        ("files", "file"), ("folders", "folder"), ("items", "item"),
        ("drives", "drive"), ("operations", "operation"),
        ("differences", "difference"), ("actions", "action"),
    ):
        text = re.sub(rf"\b1 {plural}\b", f"1 {singular}", text)
    return text


def tr_exact(text):
    """Translate only exact catalog entries (safe for file names/cells)."""
    text = str(text)
    if _language != LANGUAGE_EN:
        return text
    _load_catalog()
    return _catalog.get(text, text)


def _contains_cjk(text):
    return any("\u4e00" <= char <= "\u9fff" for char in text)


def _widget_alive(widget):
    """Return False for PyQt wrappers whose C++ object was already deleted."""
    try:
        import PyQt6.sip as sip

        return not sip.isdeleted(widget)
    except (TypeError, RuntimeError):
        return False


def _looks_like_path(text):
    return (
        "\\" in text
        or "://" in text
        or bool(re.match(r"^[A-Za-z]:[\\/]", text))
    )


_PATTERNS = [
    (r"^FileManager 檔案管理系統 v(.+)$", r"FileManager v\1"),
    (r"^檔案工作台 · (.+)$", r"File Workbench · \1"),
    (r"^已用 (.+) / (.+) · 可用 (.+)$", r"Used \1 / \2 · Free \3"),
    (r"^([A-Za-z]:\\\n)已用 (.+) / (.+) · 可用 (.+)$",
     r"\1Used \2 / \3 · Free \4"),
    (r"^可用 (.+)$", r"Free \1"),
    (r"^共 (.+) · 已用 (\d+)%$", r"Total \1 · \2% used"),
    (r"^(\d+) 顆磁碟 · 已用 (.+) · 可用 (.+)$",
     r"\1 drives · Used \2 · Free \3"),
    (r"^(\d+) 顆磁碟$", r"\1 drives"),
    (r"^(\d+) 個檔案 · (\d+) 個資料夾 · (.+)$",
     r"\1 files · \2 folders · \3"),
    (r"^(\d+) 個檔案 · (\d+) 個資料夾$", r"\1 files · \2 folders"),
    (r"^(\d+) 個檔案 · 找到 (\d+) 個$",
     r"\1 files scanned · \2 found"),
    (r"^(\d+) 個檔案$", r"\1 files"),
    (r"^(\d+) 個資料夾$", r"\1 folders"),
    (r"^(\d+) 個項目$", r"\1 items"),
    (r"^(\d+) 個差異$", r"\1 differences"),
    (r"^(\d+) 個動作$", r"\1 actions"),
    (r"^(\d+) 個動作\.\.\.$", r"\1 actions..."),
    (r"^(\d+) 筆操作$", r"\1 operations"),
    (r"^已掃描 (.+) 個檔案 · (.+) 個資料夾 · (.+)$",
     r"Scanned \1 files · \2 folders · \3"),
    (r"^已掃描 ([\d,]+) 個檔案 · 找到 ([\d,]+) 個$",
     r"Scanned \1 files · \2 found"),
    (r"^找到 ([\d,]+) 個檔案（已達顯示上限）$",
     r"Found \1 files (display limit reached)"),
    (r"^確定要『永久刪除』 ([\d,]+) 個檔案嗎？\n此操作『無法』復原！$",
     r"Permanently delete \1 files?\nThis cannot be undone!"),
    (r"^確定要將 ([\d,]+) 個檔案移入資源回收筒嗎？\n（可在資源回收筒中復原）$",
     r"Move \1 files to the Recycle Bin?\n(You can restore them from the Recycle Bin.)"),
    (r"^確定要改名 ([\d,]+) 個檔案嗎？此操作無法復原。$",
     r"Rename \1 files? This cannot be undone."),
    (r"^將 ([\d,]+) 個檔案移入資源回收筒 \(可復原\)，確定嗎？$",
     r"Move \1 files to the Recycle Bin (recoverable)?"),
    (r"^要將 ([\d,]+) 個項目移至資源回收筒嗎？$",
     r"Move \1 items to the Recycle Bin?"),
    (r"^已改名 ([\d,]+)$", r"Renamed \1"),
    (r"^已送資源回收筒: ([\d,]+)$", r"Moved to Recycle Bin: \1"),
    (r"^清理完成: ([\d,]+)$", r"Cleanup complete: \1"),
    (r"^([\d,]+) 個群組 · 浪費 (.+)$", r"\1 groups · Wasted \2"),
    (r"^已處理 ([\d,]+)$", r"Processed \1"),
    (r"^處理 ([\d,]+)$", r"Processing \1"),
    (r"^上次分析：(.+) · 花費 (.+) 秒$",
     r"Last analysis: \1 · \2 s"),
    (r"^一年以上大型檔案：(.+) 個 · (.+)$",
     r"Large files older than 1 year: \1 · \2"),
    (r"^暫存／備份檔：(.+) 個 · (.+)$",
     r"Temp/backup files: \1 · \2"),
    (r"^已選副檔名: (.+)$", r"Selected extensions: \1"),
    (r"^成功 ([\d,]+) · 失敗 (\d+) · 釋放 (.+)$",
     r"Success \1 · Failed \2 · Freed \3"),
    (r"^分析路徑：(.+)$", r"Analyzed path: \1"),
    (r"^已匯出至 (.+)$", r"Exported to \1"),
    (r"^已匯出分析結果: (.+)$", r"Analysis exported: \1"),
    (r"^已匯出搜尋結果: (.+)$", r"Search results exported: \1"),
    (r"^已匯出雜湊結果: (.+)$", r"Hash results exported: \1"),
    (r"^已匯出比對結果: (.+)$", r"Comparison exported: \1"),
    (r"^已開啟壓縮檔：([\d,]+) 個項目$", r"Archive opened: \1 items"),
    (r"^網路錯誤 \((\d+)\)$", r"Network error (\1)"),
    (r"^資料夾不存在[:：](.+)$", r"Folder does not exist: \1"),
    (r"^無法讀取資料夾：(.+)$", r"Cannot read folder: \1"),
    (r"^無法顯示資料夾：(.+)$", r"Cannot display folder: \1"),
    (r"^無法開啟：(.+)$", r"Cannot open: \1"),
    (r"^來源資料夾不存在: (.+)$", r"Source folder does not exist: \1"),
    (r"^目標資料夾不存在: (.+)$", r"Destination folder does not exist: \1"),
    (r"^來源不存在: (.+)$", r"Source does not exist: \1"),
    (r"^已移至資源回收筒：([\d,]+) 個項目$",
     r"Moved to Recycle Bin: \1 items"),
    (r"^已重新命名為 (.+)$", r"Renamed to \1"),
    (r"^已新增資料夾 (.+)$", r"Created folder \1"),
    (r"^正在分析 (.+) \.\.\.$", r"Analyzing \1..."),
    (r"^已將資料夾加入「(.+)」$", r'Added folder to "\1"'),
    (r"^成功 (.+) · 失敗 (.+)$", r"Success \1 · Failed \2"),
    (r"^進行中 (\d+) · 歷史任務 (\d+)$",
     r"Active \1 · Historical tasks \2"),
    (r"^進行中 (\d+) · 已完成／結束 (\d+) · 顯示 (\d+) 筆$",
     r"Active \1 · Completed/ended \2 · Showing \3"),
    (r"^已選 (\d+)$", r"\1 selected"),
    (r"^已選 (\d+) 個$", r"\1 selected"),
    (r"^待處理: (\d+)$", r"Pending: \1"),
    (r"^已完成: ([\d,]+) \| 跳過: ([\d,]+) \| 失敗: ([\d,]+) \| 待處理: ([\d,]+)$",
     r"Completed: \1 | Skipped: \2 | Failed: \3 | Pending: \4"),
    (r"^(\d+) 個檔案將被改名$", r"\1 files will be renamed"),
    (r"^(\d+) 個檔案待改名$", r"\1 files to rename"),
    (r"^(\d+) 個檔案 · (.+)$", r"\1 files · \2"),
    (r"^重複群組: (.+) \| 多餘檔案: (.+) \| 浪費空間: (.+)$",
     r"Duplicate groups: \1 | Extra files: \2 | Wasted: \3"),
    (r"^預計 ([\d,]+) 個動作$", r"\1 actions planned"),
    (r"^重複群組 (\d+) \((\d+) 個檔案\)$",
     r"Duplicate group \1 (\2 files)"),
    (r"^找到 (.+) 個檔案$", r"Found \1 files"),
    (r"^(\d+) 個檔案，$", r"\1 files,"),
    (r"^(\d+) 個檔案。$", r"\1 files."),
    (r"^(\d+) 個檔案嗎？$", r"\1 files?"),
    (r"^(\d+) 個檔案待處理$", r"\1 files pending"),
    (r"^(\d+) 個項目，$", r"\1 items,"),
    (r"^(\d+) 個項目。$", r"\1 items."),
    (r"^清除 (\d+) 個重複檔案$", r"Clean \1 duplicate files"),
    (r"^刪除 (\d+) 個檔案$", r"Delete \1 files"),
    (r"^刪除 (\d+) 個項目$", r"Delete \1 items"),
    (r"^清理 (\d+) 個重複檔案$", r"Clean \1 duplicate files"),
    (r"^複製 (\d+) 個項目$", r"Copy \1 items"),
    (r"^搬移 (\d+) 個項目$", r"Move \1 items"),
    (r"^同步 (\d+) 個動作\.\.\.$", r"Syncing \1 actions..."),
    (r"^(\d+) 個檔案 · (.+)$", r"\1 files · \2"),
    (r"^（根目錄檔案）$", r"(Root files)"),
    (r"^列舉檔案\.\.\. 已掃描 ([\d,]+) 個檔案 · 已執行 (.+)$",
     r"Enumerating files... \1 scanned · Elapsed \2"),
    (r"^比對檔案特徵 ([\d,]+) / ([\d,]+) 個 · 已執行 (.+)$",
     r"Checking signatures \1 / \2 · Elapsed \3"),
    (r"^計算完整雜湊 (.+) / (.+) · 已執行 (.+)$",
     r"Hashing content \1 / \2 · Elapsed \3"),
    (r"^搜尋完成: ([\d,]+) 個重複群組$",
     r"Search complete: \1 duplicate groups"),
    (r"^已開啟壓縮檔：([\d,]+) 個項目$", r"Archive opened: \1 items"),
    (r"^已選取 ([\d,]+) 個項目$", r"\1 items selected"),
    (r"^已剪下 ([\d,]+) 個項目$", r"\1 items cut"),
    (r"^已移至資源回收筒：([\d,]+) 個項目$",
     r"Moved to Recycle Bin: \1 items"),
    (r"^已將資料夾加入「(.+)」群組$", r'Added folder to "\1" group'),
    (r"^比對完成：([\d,]+) 個差異$",
     r"Comparison complete: \1 differences"),
    (r"^已刪除 ([\d,]+) 個項目，失敗 ([\d,]+)$",
     r"Deleted \1 items, \2 failed"),
    (r"^分析完成：([\d,]+) 個檔案，([\d.]+) 秒$",
     r"Analysis complete: \1 files, \2 s"),
    (r"^掃描完成: ([\d,]+) 個檔案$", r"Scan complete: \1 files"),
    (r"^清理完成: ([\d,]+) 個檔案$",
     r"Cleanup complete: \1 files"),
    (r"^改名完成: 成功 ([\d,]+), 失敗 ([\d,]+)$",
     r"Rename complete: \1 succeeded, \2 failed"),
    (r"^改名完成: ([\d,]+) 個檔案$",
     r"Rename complete: \1 files"),
    (r"^完成: 刪除 ([\d,]+) 個, 失敗 ([\d,]+) 個$",
     r"Done: deleted \1, failed \2"),
    (r"^完成 (\d+) · 跳過 (\d+) · 失敗 (\d+) · (.+) · ([\d.]+)s$",
     r"Done \1 · Skipped \2 · Failed \3 · \4 · \5s"),
    (r"^已取消：完成 (\d+) · 跳過 (\d+) · 失敗 (\d+)$",
     r"Cancelled: Done \1 · Skipped \2 · Failed \3"),
    (r"^項目 (\d+) · 差異 (\d+) · 相同 (\d+) · 略過 (\d+) 個無法讀取項目$",
     r"Items \1 · Differences \2 · Same \3 · Skipped \4 unreadable items"),
    (r"^找到 ([\d,]+) 個檔案 · ([\d.]+)s$",
     r"Found \1 files · \2s"),
    (r"^已經?處理 ([\d,]+)$", r"Processed \1"),
    (r"^正在讀取 (.+) 的共享\.\.\.$", r"Reading shares from \1..."),
    (r"^正在連線 (.+) \.\.\.$", r"Connecting to \1..."),
    (r"^已加入網路位置：(.+)$", r"Network location added: \1"),
    (r"^已移除網路位置：(.+)$", r"Network location removed: \1"),
    (r"^正在收集左側項目：([\d,]+)$", r"Collecting left items: \1"),
    (r"^正在收集右側項目：([\d,]+)$", r"Collecting right items: \1"),
    (r"^開始複製 (\d+) 個檔案$", r"Start copying \1 files"),
    (r"^開始搬移 (\d+) 個檔案$", r"Start moving \1 files"),
    (r"^同步中 (\d+)/(\d+)：(.+)$", r"Syncing \1/\2: \3"),
    (r"^加入 ([\d,]+) 個檔案 · 失敗 ([\d,]+)$",
     r"Added \1 files · Failed \2"),
    (r"^解壓 ([\d,]+) · 略過 ([\d,]+) · 失敗 ([\d,]+)$",
     r"Extracted \1 · Skipped \2 · Failed \3"),
    (r"^已複製 ([\d,]+) 個項目到剪貼簿$",
     r"Copied \1 items to clipboard"),
    (r"^分析完成：([\d,]+) 個檔案，(.+)$",
     r"Analysis complete: \1 files, \2"),
    (r"^分析資料夾：(.+)$", r"Analyze folder: \1"),
    (r"^同步: (.+)$", r"Sync: \1"),
    (r"^複製 (\d+) · 刪除 (\d+) · 失敗 (\d+) · 跳過 (\d+) · 衝突 (\d+)$",
     r"Copied \1 · Deleted \2 · Failed \3 · Skipped \4 · Conflicts \5"),
    (r"^完成: 成功 (\d+) / 跳過 (\d+) / 失敗 (\d+) \| (.+) \| 耗時 ([\d.]+)s$",
     r"Done: Success \1 / Skipped \2 / Failed \3 | \4 | Took \5s"),
    (r"^複製 ([\d,]+) 個檔案至 (.+)$", r"Copied \1 files to \2"),
    (r"^搬移 ([\d,]+) 個檔案至 (.+)$", r"Moved \1 files to \2"),
    (r"^成功刪除: (\d+) 個$", r"Successfully deleted: \1"),
    (r"^失敗: (\d+) 個$", r"Failed: \1"),
    (r"^釋放空間: (.+)$", r"Freed: \1"),
    (r"^前 5 個失敗:$", r"First 5 failures:"),
]


def _translate_pattern(text):
    for pattern, replacement in _PATTERNS:
        match = re.match(pattern, text)
        if match:
            return match.expand(replacement)
    return None


# Longest phrases first.  Used only for chrome text, never file names.
_PHRASES = [
    ("個重複檔案", "duplicate files"),
    ("個資料夾", "folders"),
    ("個檔案", "files"),
    ("個項目", "items"),
    ("個動作", "actions"),
    ("個差異", "differences"),
    ("個磁碟", "drives"),
    ("筆操作", "operations"),
    ("已用", "Used"),
    ("可用", "Free"),
    ("已選", "Selected"),
    ("已掃描", "Scanned"),
    ("已分析", "Analyzed"),
    ("已複製", "Copied"),
    ("已跳過", "Skipped"),
    ("待處理", "Pending"),
    ("成功", "Success"),
    ("失敗", "Failed"),
    ("總容量", "Total size"),
    ("浪費空間", "Wasted space"),
    ("多餘檔案", "Extra files"),
    ("重複群組", "Duplicate groups"),
    ("檔案", "files"),
    ("資料夾", "folders"),
    ("項目", "items"),
    ("大小", "Size"),
    ("路徑", "Path"),
    ("時間", "Time"),
    ("狀態", "Status"),
    ("類型", "Type"),
    ("名稱", "Name"),
    ("確定", "OK"),
    ("取消", "Cancel"),
    ("暫停", "Pause"),
    ("繼續", "Resume"),
    ("停止", "Stop"),
    ("開始", "Start"),
    ("關閉", "Close"),
    ("搜尋", "Search"),
    ("清理", "Clean"),
    ("刪除", "Delete"),
    ("複製", "Copy"),
    ("搬移", "Move"),
    ("分析", "Analyze"),
    ("重新整理", "Refresh"),
    ("個", ""),
    ("秒", "s"),
]


def _translate_phrases(text):
    if _looks_like_path(text):
        return None
    result = text
    changed = False
    for source, target in _PHRASES:
        if source in result:
            result = result.replace(source, target)
            changed = True
    if not changed or _contains_cjk(result):
        return None
    return result


def _translate_fragments(text):
    """Translate short composed strings using known catalog fragments."""
    if _looks_like_path(text):
        return None
    result = text
    changed = False
    for source, target in _fragment_items:
        if len(source) >= 2 and source in result:
            result = result.replace(source, target)
            changed = True
    if changed and not _contains_cjk(result):
        return result
    return None


class Localizer(QObject):
    """Apply English catalog translations to visible widgets and dialogs."""

    def __init__(self, app, root, interval=250):
        super().__init__(app)
        self.app = app
        self.root = root
        self.timer = QTimer(self)
        self.timer.setInterval(interval)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()
        app.installEventFilter(self)

    def translate_all(self):
        self._translate_tree(self.root, force=True)
        for top in self.app.topLevelWidgets():
            self._translate_tree(top, force=True)

    def refresh(self):
        if language() != LANGUAGE_EN:
            return
        self._translate_tree(self.root, force=False)
        for top in list(self.app.topLevelWidgets()):
            try:
                if top.isVisible():
                    self._translate_tree(top, force=False)
            except RuntimeError:
                continue

    def eventFilter(self, obj, event):
        if (event.type() == QEvent.Type.Show and isinstance(obj, QWidget)
                and obj.isWindow()):
            if language() == LANGUAGE_EN:
                # Do not capture the widget here: transient labels can be
                # deleted before the queued callback runs.
                QTimer.singleShot(0, self.refresh)
        return False

    def _translate_tree(self, root, force=False):
        if root is None:
            return
        try:
            if isinstance(root, QWidget):
                if not _widget_alive(root):
                    return
                if not force and not root.isVisible():
                    return
                self._translate_widget(root)
                widgets = root.findChildren(QWidget)
            else:
                widgets = root.findChildren(QWidget)
            for widget in widgets:
                if not _widget_alive(widget):
                    continue
                if not force and not widget.isVisible():
                    continue
                try:
                    self._translate_widget(widget)
                except RuntimeError:
                    # A transient Qt widget was deleted between discovery
                    # and translation (common for dialogs and page headers).
                    continue
        except RuntimeError:
            return

    def _translate_widget(self, widget):
        if not _widget_alive(widget):
            return
        data_label = widget.objectName() in (
            "chartDataLabel", "previewDataLabel"
        )
        title = widget.windowTitle()
        if title:
            translated = tr(title)
            if translated != title:
                widget.setWindowTitle(translated)
        tip = widget.toolTip()
        if tip and not data_label:
            translated = tr(tip)
            if translated != tip:
                widget.setToolTip(translated)
        status_tip = widget.statusTip()
        if status_tip:
            translated = tr(status_tip)
            if translated != status_tip:
                widget.setStatusTip(translated)
        accessible = widget.accessibleName()
        if accessible:
            translated = tr(accessible)
            if translated != accessible:
                widget.setAccessibleName(translated)

        if isinstance(widget, QLabel):
            if widget.objectName() == "chartDataLabel":
                text = widget.text()
                translated = tr_exact(text)
                if translated != text:
                    widget.setText(translated)
                return
            if widget.objectName() == "previewDataLabel":
                return
            text = widget.text()
            if text:
                translated = tr(text)
                if translated != text:
                    widget.setText(translated)
        elif isinstance(widget, QAbstractButton):
            text = widget.text()
            if text:
                translated = tr(text)
                if translated != text:
                    widget.setText(translated)
        elif isinstance(widget, QGroupBox):
            title = widget.title()
            if title:
                translated = tr(title)
                if translated != title:
                    widget.setTitle(translated)
        elif isinstance(widget, QLineEdit):
            placeholder = widget.placeholderText()
            if placeholder:
                translated = tr(placeholder)
                if translated != placeholder:
                    widget.setPlaceholderText(translated)
        elif isinstance(widget, (QSpinBox, QDoubleSpinBox)):
            for getter, setter in (
                (widget.prefix, widget.setPrefix),
                (widget.suffix, widget.setSuffix),
            ):
                text = getter()
                if not text:
                    continue
                translated = tr(text)
                if translated != text:
                    setter(translated)
        elif isinstance(widget, QComboBox):
            self._translate_combo(widget)
        elif isinstance(widget, QTabWidget):
            if widget.objectName() == "browserTabs":
                return
            for index in range(widget.count()):
                text = widget.tabText(index)
                translated = tr(text)
                if translated != text:
                    widget.setTabText(index, translated)
        elif isinstance(widget, QTableWidget):
            self._translate_table(widget)
        elif isinstance(widget, QTreeWidget):
            self._translate_tree_widget(widget)
        elif isinstance(widget, QListWidget):
            self._translate_list(widget)
        elif isinstance(widget, QMenu):
            for action in widget.actions():
                text = action.text()
                translated = tr(text)
                if translated != text:
                    action.setText(translated)

    def _translate_combo(self, combo):
        blocker = combo.blockSignals(True)
        try:
            for index in range(combo.count()):
                text = combo.itemText(index)
                translated = tr(text)
                if translated != text:
                    combo.setItemText(index, translated)
        finally:
            combo.blockSignals(blocker)

    def _translate_table(self, table):
        for column in range(table.columnCount()):
            header = table.horizontalHeaderItem(column)
            if header is not None:
                translated = tr(header.text())
                if translated != header.text():
                    header.setText(translated)
        first = table.rowAt(0)
        last = table.rowAt(max(0, table.viewport().height() - 2))
        if first < 0:
            first = 0
        if last < 0:
            last = min(table.rowCount() - 1, first + 40)
        pending = []
        for row in range(first, min(table.rowCount(), last + 1)):
            for column in range(table.columnCount()):
                item = table.item(row, column)
                if item is not None and _contains_cjk(item.text()):
                    pending.append(item)
        if not pending:
            return
        sorting = table.isSortingEnabled()
        if sorting:
            table.setSortingEnabled(False)
        try:
            for item in pending:
                translated = tr_exact(item.text())
                if translated != item.text():
                    item.setText(translated)
        finally:
            if sorting:
                table.setSortingEnabled(True)

    def _translate_tree_widget(self, tree):
        header = tree.headerItem()
        if header is not None:
            for column in range(tree.columnCount()):
                translated = tr(header.text(column))
                if translated != header.text(column):
                    header.setText(column, translated)
        if tree.objectName() == "duplicatesTree":
            for i in range(tree.topLevelItemCount()):
                item = tree.topLevelItem(i)
                text = item.text(0)
                translated = tr(text)
                if translated != text:
                    item.setText(0, translated)
            return
        for i in range(tree.topLevelItemCount()):
            item = tree.topLevelItem(i)
            self._translate_tree_item(tree, item)
        for i in range(tree.topLevelItemCount()):
            parent = tree.topLevelItem(i)
            for j in range(parent.childCount()):
                self._translate_tree_item(tree, parent.child(j))

    def _translate_tree_item(self, tree, item):
        name = tree.objectName()
        if name == "navTree":
            columns = range(tree.columnCount())
        elif name == "compareTree":
            columns = (0,)
        else:
            return
        for column in columns:
            text = item.text(column)
            translated = tr_exact(text)
            if translated != text:
                item.setText(column, translated)
        tip = item.toolTip(0)
        if tip and name == "navTree":
            translated = tr(tip)
            if translated != tip:
                item.setToolTip(0, translated)

    def _translate_list(self, widget):
        if widget.objectName() in ("searchRoots", "favoritesList"):
            return
        if not _widget_alive(widget):
            return
        for index in range(widget.count()):
            item = widget.item(index)
            if item is None:
                continue
            translated = tr(item.text())
            if translated != item.text():
                item.setText(translated)
            tip = item.toolTip()
            if tip:
                translated = tr(tip)
                if translated != tip:
                    item.setToolTip(translated)
