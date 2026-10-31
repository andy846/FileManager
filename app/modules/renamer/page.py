"""Batch rename module: find & replace / add prefix-suffix / numbering / case.

Preview and apply both run on background threads and the apply step reuses
the exact mapping produced by the preview, so the names shown are exactly
the names written.
"""

import os

from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QGroupBox, QPushButton, QLineEdit,
    QLabel, QTableWidget, QTableWidgetItem, QComboBox, QCheckBox,
    QMessageBox, QProgressBar,
)

from app.ui.base import ModulePage
from app.ui.components import PageHeader
from app.ui.icons import set_icon
from app.ui.widgets import PathField
from app.core.utils import is_dir_fs, short_path
from app.core.constants import MODULE_RENAME
from app.core.history import record_operation


def rename_path(path, pattern):
    """Return the new path for *path* under *pattern* (no filesystem writes)."""
    name = os.path.basename(path)
    base, ext = os.path.splitext(name)
    mode = pattern["mode"]
    if mode == "replace":
        new_base = base.replace(pattern["find"], pattern["replace"])
    elif mode == "prefix":
        new_base = pattern["prefix"] + base
    elif mode == "suffix":
        new_base = base + pattern["suffix"]
    elif mode == "number":
        idx = pattern["start"] + pattern.get("_i", 0)
        new_base = f"{pattern['prefix']}{idx:0{pattern['pad']}d}{pattern['suffix']}"
        pattern["_i"] = pattern.get("_i", 0) + 1
    elif mode == "upper":
        new_base = base.upper()
    elif mode == "lower":
        new_base = base.lower()
    else:
        new_base = base
    new_name = new_base + (ext if pattern.get("keep_ext", True) else "")
    return os.path.join(os.path.dirname(path), new_name)


def _scan_files(folder, recursive):
    files = []
    for root, dirs, names in os.walk(folder):
        if not recursive:
            dirs[:] = []
        for name in names:
            files.append(os.path.join(root, name))
    return files


class RenameScanWorker(QThread):
    """Walks the folder and emits the ``(old, new)`` rename pairs."""

    preview_ready = pyqtSignal(list)
    error = pyqtSignal(str)

    def __init__(self, folder, pattern, recursive):
        super().__init__()
        self.folder = folder
        self.pattern = pattern
        self.recursive = recursive
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        try:
            pattern = dict(self.pattern)
            pairs = []
            for path in _scan_files(self.folder, self.recursive):
                if self._cancelled:
                    break
                new_path = rename_path(path, pattern)
                if new_path != path:
                    pairs.append((path, new_path))
            self.preview_ready.emit(pairs)
        except Exception as exc:
            self.error.emit(str(exc))


class RenameApplyWorker(QThread):
    """Renames the previewed ``(old, new)`` pairs on a background thread."""

    progress = pyqtSignal(int, int)
    done = pyqtSignal(int, list)  # changed, [(path, error), ...]

    def __init__(self, pairs):
        super().__init__()
        self.pairs = list(pairs)
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        changed = 0
        failures = []
        total = len(self.pairs)
        for i, (old, new) in enumerate(self.pairs):
            if self._cancelled:
                break
            # On case-insensitive filesystems a case-only rename has a
            # "target" that already exists (it is the same file), so it must
            # not be rejected as a collision.
            same_file = (os.path.normcase(os.path.abspath(old))
                         == os.path.normcase(os.path.abspath(new)))
            if os.path.exists(new) and not same_file:
                failures.append((old, "目標已存在，已略過"))
            else:
                try:
                    os.rename(old, new)
                    changed += 1
                except OSError as exc:
                    failures.append((old, str(exc)))
            self.progress.emit(i + 1, total)
        self.done.emit(changed, failures)


class RenamerPage(ModulePage):
    title = "批次改名"
    module_id = MODULE_RENAME

    def __init__(self, settings, main_window=None):
        super().__init__(settings, main_window)
        self.preview = []
        self.scan_worker = None
        self.apply_worker = None
        self._task = None
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        self.page_header = PageHeader(
            "批次改名",
            "以尋找取代、前後綴、編號或大小寫規則批次改名",
            icon="rename",
            theme=self.theme(),
        )
        root.addWidget(self.page_header)

        top = QHBoxLayout()
        fbox = QGroupBox("目標資料夾")
        fl = QHBoxLayout(fbox)
        self.folder = PathField(settings=self.settings, field_name="rename_folder",
                                placeholder="選擇要改名的資料夾")
        fl.addWidget(self.folder)
        top.addWidget(fbox, 1)
        self.recursive = QCheckBox("包含子資料夾")
        self.recursive.setChecked(True)
        top.addWidget(self.recursive)
        root.addLayout(top)

        mode_box = QGroupBox("改名規則")
        ml = QVBoxLayout(mode_box)
        self.mode = QComboBox()
        for label, key in [
            ("尋找並取代", "replace"),
            ("加入前綴", "prefix"),
            ("加入後綴", "suffix"),
            ("編號", "number"),
            ("轉大寫", "upper"),
            ("轉小寫", "lower"),
        ]:
            self.mode.addItem(label, key)
        self.mode.currentIndexChanged.connect(self._on_mode)
        ml.addWidget(self.mode)

        self.row1 = QHBoxLayout()
        self.label1 = QLabel("尋找:")
        self.field1 = QLineEdit()
        self.row1.addWidget(self.label1)
        self.row1.addWidget(self.field1, 1)
        ml.addLayout(self.row1)

        self.row2 = QHBoxLayout()
        self.label2 = QLabel("取代為:")
        self.field2 = QLineEdit()
        self.row2.addWidget(self.label2)
        self.row2.addWidget(self.field2, 1)
        ml.addLayout(self.row2)

        self.row3 = QHBoxLayout()
        self.keep_ext = QCheckBox("保留副檔名")
        self.keep_ext.setChecked(True)
        self.row3.addWidget(self.keep_ext)
        ml.addLayout(self.row3)
        root.addWidget(mode_box)

        bl = QHBoxLayout()
        self.preview_btn = QPushButton("預覽")
        self.preview_btn.setProperty("variant", "primary")
        set_icon(self.preview_btn, "eye", self.theme(), "primary_text", 15)
        self.preview_btn.clicked.connect(self._on_preview)
        self.apply_btn = QPushButton("套用改名")
        self.apply_btn.setProperty("variant", "success")
        set_icon(self.apply_btn, "check", self.theme(), "primary_text", 15)
        self.apply_btn.setEnabled(False)
        self.apply_btn.clicked.connect(self._on_apply)
        bl.addWidget(self.preview_btn)
        bl.addWidget(self.apply_btn)
        bl.addStretch(1)
        root.addLayout(bl)

        self.progress = QProgressBar()
        self.progress.setVisible(False)
        root.addWidget(self.progress)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["原始檔名", "新檔名", "路徑"])
        self.table.setColumnWidth(0, 220)
        self.table.setColumnWidth(1, 220)
        self.table.setColumnWidth(2, 320)
        self.table.setAlternatingRowColors(True)
        root.addWidget(self.table, 1)

    # ------------------------------------------------------------------
    def _on_mode(self, _index=None):
        mode = self.mode.currentData()
        self.label1.setText("尋找:" if mode == "replace" else (
            "前綴:" if mode in ("prefix", "number") else (
                "後綴:" if mode == "suffix" else "")))
        self.field1.setVisible(mode in ("replace", "prefix", "number"))
        self.label1.setVisible(self.field1.isVisible())
        self.label2.setText("取代為:")
        self.field2.setVisible(mode == "replace")
        self.label2.setVisible(self.field2.isVisible())
        if mode == "number":
            self.label2.setText("後綴:")
            self.label2.setVisible(True)
            self.field2.setVisible(True)

    def _collect_pattern(self):
        m = self.mode.currentData() or "replace"
        p = {"mode": m, "keep_ext": self.keep_ext.isChecked(), "start": 1, "pad": 3}
        if m == "replace":
            p["find"] = self.field1.text()
            p["replace"] = self.field2.text()
        elif m == "prefix":
            p["prefix"] = self.field1.text()
        elif m == "suffix":
            p["suffix"] = self.field1.text()
        elif m == "number":
            p["prefix"] = self.field1.text()
            p["suffix"] = self.field2.text()
        return p

    # ------------------------------------------------------------------
    def _on_preview(self):
        folder = self.folder.text()
        if not folder or not is_dir_fs(folder):
            QMessageBox.warning(self, "資料夾錯誤", "請選擇有效的資料夾。")
            return
        pattern = self._collect_pattern()
        if pattern["mode"] == "replace" and not pattern["find"]:
            QMessageBox.warning(self, "規則錯誤", "「尋找」字串不可為空。")
            return
        self.settings.remember_path("rename_folder", folder)
        self.table.setRowCount(0)
        self.preview = []
        self.apply_btn.setEnabled(False)
        self.preview_btn.setEnabled(False)
        self.progress.setVisible(True)
        self.progress.setRange(0, 0)
        self.status("掃描中...")

        self.scan_worker = RenameScanWorker(folder, pattern,
                                            self.recursive.isChecked())
        self.scan_worker.preview_ready.connect(self._on_preview_ready)
        self.scan_worker.error.connect(self._on_preview_error)
        self.scan_worker.start()
        self._task = self.task_add(
            "rename_preview", "預覽批次改名",
            cancel=self.scan_worker.cancel, message=folder,
        )

    def _on_preview_error(self, message):
        self.preview_btn.setEnabled(True)
        self.progress.setVisible(False)
        self.task_finish(self._task, status="failed", error=message)
        self._task = None
        QMessageBox.warning(self, "掃描錯誤", message)
        self.status("掃描失敗")

    def _on_preview_ready(self, pairs):
        self.preview_btn.setEnabled(True)
        self.progress.setVisible(False)
        self.preview = pairs
        for old, new in pairs:
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(os.path.basename(old)))
            self.table.setItem(row, 1, QTableWidgetItem(os.path.basename(new)))
            pitem = QTableWidgetItem(short_path(old, 60))
            pitem.setToolTip(old)
            self.table.setItem(row, 2, pitem)
        self.apply_btn.setEnabled(bool(pairs))
        self.task_finish(self._task, message=f"{len(pairs)} 個檔案待改名")
        self._task = None
        self.status(f"預覽: {len(pairs)} 個檔案將被改名")

    def _on_apply(self):
        if not self.preview:
            QMessageBox.information(self, "套用", "請先執行預覽。")
            return
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("確認改名")
        box.setText(f"確定要改名 {len(self.preview)} 個檔案嗎？此操作無法復原。")
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if box.exec() != QMessageBox.StandardButton.Yes:
            return

        self.apply_btn.setEnabled(False)
        self.preview_btn.setEnabled(False)
        self.progress.setVisible(True)
        self.progress.setRange(0, len(self.preview))
        self.progress.setValue(0)
        self.status("改名中...")

        self.apply_worker = RenameApplyWorker(self.preview)
        self.apply_worker.progress.connect(
            lambda d, t: self.progress.setValue(d))
        self.apply_worker.done.connect(self._on_apply_done)
        self.apply_worker.start()
        self._task = self.task_add(
            "rename", f"批次改名 {len(self.preview)} 個檔案",
            cancel=self.apply_worker.cancel, total=len(self.preview),
        )
        self.apply_worker.progress.connect(
            lambda done, total: self.task_update(
                self._task, done=done, total=total
            )
        )

    def _on_apply_done(self, changed, failures):
        self.preview_btn.setEnabled(True)
        self.progress.setVisible(False)
        self.task_finish(
            self._task,
            status="done" if not failures else "failed",
            message=f"改名 {changed} · 失敗 {len(failures)}",
        )
        self._task = None
        if failures:
            self.status(f"改名完成: 成功 {changed}, 失敗 {len(failures)}")
        else:
            self.status(f"改名完成: {changed} 個檔案")
        record_operation(self.settings, MODULE_RENAME, self.folder.text(),
                         f"改名 {changed} 個檔案", changed,
                         len(failures))
        QMessageBox.information(self, "完成", f"已改名 {changed} 個檔案。")
        self._on_preview()

    def on_theme_changed(self):
        self.page_header.set_theme(self.theme())

    def apply_payload(self, payload):
        if not isinstance(payload, dict):
            return
        folder = payload.get("folder")
        if folder and is_dir_fs(folder):
            self.folder.set_path(folder)

    def request_stop(self):
        for worker in (self.scan_worker, self.apply_worker):
            if worker and worker.isRunning():
                worker.cancel()
                worker.wait(3000)

    # Kept for backward compatibility with existing callers/tests.
    _rename_one = staticmethod(rename_path)
