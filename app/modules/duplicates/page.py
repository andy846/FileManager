"""Duplicates module page (rewritten from tkinter to PyQt6)."""

import time

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QGroupBox, QPushButton, QProgressBar,
    QLabel, QTreeWidget, QTreeWidgetItem, QCheckBox, QMessageBox,
    QFileDialog, QLineEdit, QDoubleSpinBox, QSplitter,
)

from app.core.i18n import file_filter, tr
from app.ui.base import ModulePage
from app.ui.components import PageHeader
from app.ui.icons import set_icon
from app.ui.widgets import PathField, DropArea
from app.modules.browser.preview import PreviewPanel
from app.modules.duplicates.worker import DuplicatesWorker, CleanupWorker
from app.core.workers import OperationControl
from app.core.utils import (
    format_datetime, format_size, is_dir_fs, normalize_path, short_path,
)
from app.core.constants import MODULE_DUPLICATES

from app.core.history import record_operation


def _format_elapsed(seconds):
    seconds = max(0, int(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


class DuplicatesPage(ModulePage):
    title = "重複檔案"
    module_id = MODULE_DUPLICATES

    def __init__(self, settings, main_window=None):
        super().__init__(settings, main_window)
        self.groups = []
        self.control = None
        self.worker = None
        self.cleaner = None
        self.scanning = False
        self.cleaning = False
        self._task = None
        self._scan_started = 0.0
        self._scan_info = None
        self._scan_phase = None
        self._scan_phase_done = 0
        self._scan_phase_value = 0
        self._scan_timer = QTimer(self)
        self._scan_timer.setInterval(500)
        self._scan_timer.timeout.connect(self._render_scan_status)
        self._build_ui()
        self._load_options()

    def _build_ui(self):
        root = QVBoxLayout(self)
        self.page_header = PageHeader(
            "重複檔案",
            "以大小與 SHA-256 找出重複內容，安全清理多餘副本",
            icon="duplicates",
            theme=self.theme(),
        )
        root.addWidget(self.page_header)

        top = QHBoxLayout()
        fbox = QGroupBox("搜尋資料夾")
        fl = QHBoxLayout(fbox)
        self.folder = PathField(settings=self.settings, field_name="dup_folder",
                                placeholder="選擇要搜尋重複檔案的資料夾")
        fl.addWidget(self.folder)
        self.drop = DropArea(text="拖放資料夾到此處")
        self.drop.folder_dropped.connect(self.folder.set_path)
        fl.addWidget(self.drop)
        top.addWidget(fbox, 1)
        self.scan_btn = QPushButton("開始搜尋")
        self.scan_btn.setProperty("variant", "primary")
        set_icon(self.scan_btn, "search", self.theme(), "primary_text", 15)
        self.scan_btn.clicked.connect(self._on_scan)
        self.stop_btn = QPushButton("停止")
        self.stop_btn.setEnabled(False)
        set_icon(self.stop_btn, "stop", self.theme(), "text", 14)
        self.stop_btn.clicked.connect(self._on_stop)
        top.addWidget(self.scan_btn)
        top.addWidget(self.stop_btn)
        root.addLayout(top)

        self.recursive = QCheckBox("包含子資料夾")
        self.recursive.setChecked(True)
        root.addWidget(self.recursive)

        options = QHBoxLayout()
        options.addWidget(QLabel("最小大小:"))
        self.min_size = QDoubleSpinBox()
        self.min_size.setRange(0, 1000000)
        self.min_size.setSuffix(" MB")
        self.min_size.setValue(0)
        options.addWidget(self.min_size)
        options.addWidget(QLabel("排除樣式:"))
        self.exclude = QLineEdit()
        self.exclude.setPlaceholderText("*.tmp, cache/, ...")
        options.addWidget(self.exclude, 1)
        self.ignore_hardlinks = QCheckBox("忽略硬連結")
        self.ignore_hardlinks.setChecked(True)
        options.addWidget(self.ignore_hardlinks)
        root.addLayout(options)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setVisible(False)
        root.addWidget(self.progress)

        self.stats = QLabel("尚未搜尋")
        root.addWidget(self.stats)

        bl = QHBoxLayout()
        self.sel_extra_btn = QPushButton("選取所有多餘副本")
        self.sel_extra_btn.clicked.connect(lambda: self._auto_select("extra"))
        self.keep_new_btn = QPushButton("保留最新 (選其餘)")
        self.keep_new_btn.clicked.connect(lambda: self._auto_select("newest"))
        self.keep_old_btn = QPushButton("保留最舊 (選其餘)")
        self.keep_old_btn.clicked.connect(lambda: self._auto_select("oldest"))
        self.clean_btn = QPushButton("清理選取檔案")
        self.clean_btn.setProperty("variant", "danger")
        set_icon(self.clean_btn, "trash", self.theme(), "danger_text", 15)
        self.clean_btn.clicked.connect(self._on_clean)
        self.export_btn = QPushButton("匯出 Excel")
        set_icon(self.export_btn, "download", self.theme(), "text", 14)
        self.export_btn.clicked.connect(self._on_export)
        self.preview_check = QCheckBox("預覽")
        self.preview_check.toggled.connect(self._toggle_preview)
        bl.addWidget(self.sel_extra_btn)
        bl.addWidget(self.keep_new_btn)
        bl.addWidget(self.keep_old_btn)
        bl.addWidget(self.preview_check)
        bl.addStretch(1)
        bl.addWidget(self.export_btn)
        bl.addWidget(self.clean_btn)
        root.addLayout(bl)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.tree = QTreeWidget()
        self.tree.setObjectName("duplicatesTree")
        self.tree.setHeaderLabels(["檔案", "大小", "修改時間", "路徑"])
        self.tree.setColumnWidth(0, 200)
        self.tree.setColumnWidth(1, 90)
        self.tree.setColumnWidth(2, 150)
        self.tree.setColumnWidth(3, 320)
        self.tree.setAlternatingRowColors(True)
        self.tree.currentItemChanged.connect(self._on_tree_current)
        self.splitter.addWidget(self.tree)
        self.preview = PreviewPanel()
        self.preview.setVisible(False)
        self.preview.setMinimumWidth(260)
        self.splitter.addWidget(self.preview)
        self.splitter.setStretchFactor(0, 1)
        root.addWidget(self.splitter, 1)

    def _toggle_preview(self, enabled):
        self.preview.setVisible(enabled)
        if enabled:
            self._on_tree_current(self.tree.currentItem())

    def _on_tree_current(self, item):
        if item is None or not self.preview.isVisible():
            return
        path = item.data(0, Qt.ItemDataRole.UserRole)
        if path:
            self.preview.show_path(path)

    def _load_options(self):
        self.recursive.setChecked(self.settings.option("dup_recursive", True))
        self.min_size.setValue(self.settings.option("dup_min_mb", 0.0))
        self.exclude.setText(self.settings.option("dup_exclude", ""))
        self.ignore_hardlinks.setChecked(
            self.settings.option("dup_ignore_hardlinks", True)
        )

    def _on_scan(self):
        folder = self.folder.text()
        if not folder or not is_dir_fs(folder):
            QMessageBox.warning(self, "資料夾錯誤", "請選擇有效的資料夾。")
            return
        self.settings.remember_path("dup_folder", folder)
        self.settings.set_option("dup_recursive", self.recursive.isChecked())
        self.settings.set_option("dup_min_mb", self.min_size.value())
        self.settings.set_option("dup_exclude", self.exclude.text())
        self.settings.set_option(
            "dup_ignore_hardlinks", self.ignore_hardlinks.isChecked()
        )
        self.tree.clear()
        self.groups = []
        self.scanning = True
        self.scan_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.clean_btn.setEnabled(False)
        self.progress.setVisible(True)
        self.progress.setRange(0, 0)
        self.progress.setValue(0)
        self.progress.setFormat(tr("掃描中..."))
        self.stats.setText(tr("搜尋重複檔案中..."))
        self._scan_started = time.monotonic()
        self._scan_info = None
        self._scan_phase = None
        self._scan_phase_done = 0
        self._scan_phase_value = 0
        self._scan_timer.start()
        self.control = OperationControl()
        self.worker = DuplicatesWorker(
            self.control, folder, self.recursive.isChecked(),
            min_size=int(self.min_size.value() * 1024 * 1024),
            exclude=[x.strip() for x in self.exclude.text().split(",")
                     if x.strip()],
            ignore_hardlinks=self.ignore_hardlinks.isChecked(),
        )
        self.worker.scan_progress.connect(self._on_scan_progress)
        self.worker.scan_complete.connect(self._on_complete)
        self.worker.scan_cancelled.connect(self._on_scan_cancelled)
        self.worker.scan_failed.connect(self._on_scan_failed)
        self._task = self.task_add(
            "duplicates", "搜尋重複檔案", control=self.control,
            message=folder, pausable=False,
        )
        self.worker.start()
        self.status(tr("搜尋重複檔案中..."))

    def _on_scan_progress(self, info):
        self._scan_info = info
        self._render_scan_status()

    def _render_scan_status(self):
        if not self.scanning:
            return
        elapsed = _format_elapsed(time.monotonic() - self._scan_started)
        info = self._scan_info
        if info is None or info.phase == "scan":
            if self.progress.maximum() != 0:
                self.progress.setRange(0, 0)
            self.progress.setFormat(tr("掃描中..."))
            scanned = info.scanned if info is not None else 0
            text = tr(
                f"列舉檔案... 已掃描 {scanned:,} 個檔案 · 已執行 {elapsed}"
            )
            self.stats.setText(text)
            self.task_update(
                self._task, message=tr(f"已掃描 {scanned:,} 個檔案")
            )
            return

        if info.phase != self._scan_phase:
            self._scan_phase = info.phase
            self._scan_phase_done = 0
            self._scan_phase_value = 0
        done = max(info.done, self._scan_phase_done)
        self._scan_phase_done = done
        total = max(1, info.total)
        ratio = min(1.0, max(0.0, done / total))
        value = max(self._scan_phase_value, int(ratio * 1000))
        self._scan_phase_value = value
        if self.progress.maximum() != 1000:
            self.progress.setRange(0, 1000)
        self.progress.setValue(value)
        self.progress.setFormat(f"{value // 10}%")
        if info.phase == "quick":
            text = tr(
                f"比對檔案特徵 {done:,} / {info.total:,} 個"
                f" · 已執行 {elapsed}"
            )
            self.task_update(
                self._task, done=done, total=info.total,
                message=tr(f"比對檔案特徵 {done:,} / {info.total:,} 個"),
            )
        else:
            text = tr(
                f"計算完整雜湊 {format_size(done)} / "
                f"{format_size(info.total)} · 已執行 {elapsed}"
            )
            self.task_update(
                self._task, done=done, total=info.total,
                message=tr(
                    f"計算完整雜湊 {format_size(done)} / "
                    f"{format_size(info.total)}"
                ),
            )
        self.stats.setText(text)

    def _finish_scan_ui(self):
        self._scan_timer.stop()
        self.scanning = False
        self._scan_info = None
        self._scan_phase = None
        self._scan_phase_done = 0
        self._scan_phase_value = 0
        self.progress.setVisible(False)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setFormat("%p%")
        self.scan_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.clean_btn.setEnabled(True)

    def _on_stop(self):
        if self.control:
            self.control.cancel()
            self.stop_btn.setEnabled(False)
            self.stats.setText(tr("取消中..."))
            self.task_update(self._task, message=tr("取消中..."))

    def _on_scan_cancelled(self):
        self._finish_scan_ui()
        self.stats.setText(tr("已取消搜尋"))
        self.task_finish(
            self._task, status="cancelled", message=tr("已取消搜尋")
        )
        self._task = None
        self.status(tr("已取消搜尋"))

    def _on_scan_failed(self, message):
        self._finish_scan_ui()
        self.stats.setText(tr("搜尋失敗"))
        self.task_finish(
            self._task, status="failed", error=message,
            message=tr("搜尋失敗"),
        )
        self._task = None
        QMessageBox.warning(self, tr("搜尋失敗"), message)
        self.status(tr("搜尋失敗"))

    def _on_complete(self, groups):
        if self.control and self.control.is_cancelled():
            self._on_scan_cancelled()
            return
        self._finish_scan_ui()
        self.groups = [g for g in groups if g.is_duplicate]
        self._populate()
        total_groups = len(self.groups)
        total_dups = sum(len(g.files) - 1 for g in self.groups)
        wasted = sum(g.wasted_space for g in self.groups)
        self.stats.setText(tr(
            f"重複群組: {total_groups} | 多餘檔案: {total_dups} | "
            f"浪費空間: {format_size(wasted)}"
        ))
        self.task_finish(
            self._task,
            status="done",
            message=f"{total_groups} 個群組 · 浪費 {format_size(wasted)}",
        )
        self._task = None
        self.status(tr(f"搜尋完成: {total_groups} 個重複群組"))

    def _populate(self):
        self.tree.clear()
        from PyQt6.QtGui import QBrush, QColor

        # Theme-aware group header background.
        bg = QColor("#2f4468") if self.theme() == "dark" else QColor("#e1f5fe")
        for gi, group in enumerate(self.groups):
            parent = QTreeWidgetItem(self.tree)
            parent.setText(0, f"重複群組 {gi + 1} ({len(group.files)} 個檔案)")
            brush = QBrush(bg)
            for col in range(4):
                parent.setBackground(col, brush)
            for fi in group.files:
                child = QTreeWidgetItem(parent)
                child.setFlags(child.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                child.setCheckState(0, Qt.CheckState.Unchecked)
                child.setText(0, fi.name)
                child.setText(1, format_size(fi.size))
                child.setText(2, format_datetime(fi.modified))
                child.setText(3, short_path(fi.path, 60))
                child.setToolTip(3, fi.path)
                child.setData(0, Qt.ItemDataRole.UserRole, fi.path)
            parent.setExpanded(True)

    def _iter_children(self):
        for i in range(self.tree.topLevelItemCount()):
            parent = self.tree.topLevelItem(i)
            for j in range(parent.childCount()):
                yield parent, parent.child(j)

    def _auto_select(self, mode):
        for parent, child in self._iter_children():
            path = child.data(0, Qt.ItemDataRole.UserRole)
            group = self.groups[self.tree.indexOfTopLevelItem(parent)]
            siblings = group.files
            if mode == "extra":
                keep = siblings[0].path
            elif mode == "newest":
                keep = max(siblings, key=lambda f: f.modified).path
            elif mode == "oldest":
                keep = min(siblings, key=lambda f: f.modified).path
            else:
                keep = None
            child.setCheckState(0, Qt.CheckState.Unchecked
                                if path == keep else Qt.CheckState.Checked)

    def _selected_paths(self):
        out = []
        for _parent, child in self._iter_children():
            if child.checkState(0) == Qt.CheckState.Checked:
                out.append(child.data(0, Qt.ItemDataRole.UserRole))
        return out

    def _on_clean(self):
        paths = self._selected_paths()
        if not paths:
            QMessageBox.information(self, "清理", "請先選取要清理的檔案。")
            return
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("確認清理")
        box.setText(f"將 {len(paths)} 個檔案移入資源回收筒 (可復原)，確定嗎？")
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if box.exec() != QMessageBox.StandardButton.Yes:
            return
        # Capture sizes BEFORE deletion - files no longer exist afterwards.
        self._size_map = {}
        for g in self.groups:
            for f in g.files:
                self._size_map[f.path] = f.size
        self.cleaning = True
        self.clean_btn.setEnabled(False)
        self.progress.setVisible(True)
        self.progress.setRange(0, len(paths))
        self.progress.setValue(0)
        self.control = OperationControl()
        self.cleaner = CleanupWorker(self.control, paths)
        self.cleaner.cleanup_progress.connect(lambda d, t: self.progress.setValue(d))
        self.cleaner.cleanup_complete.connect(self._on_clean_complete)
        self._task = self.task_add(
            "duplicates_clean", f"清理 {len(paths)} 個重複檔案",
            control=self.control, total=len(paths), pausable=False,
        )
        self.cleaner.cleanup_progress.connect(
            lambda done, total: self.task_update(
                self._task, done=done, total=total
            )
        )
        self.cleaner.start()

    def _on_clean_complete(self, deleted, failed):
        self.cleaning = False
        self.progress.setVisible(False)
        self.clean_btn.setEnabled(True)
        size_freed = sum(self._size_map.get(p, 0) for p in deleted)
        self._size_map = {}
        record_operation(self.settings, MODULE_DUPLICATES, self.folder.text(),
                         f"清理 {len(deleted)} 個重複檔案", len(deleted),
                         len(failed), size_freed)
        self.task_finish(
            self._task,
            status="done" if not failed else "failed",
            message=f"清理 {len(deleted)} · 失敗 {len(failed)}"
                    f" · {format_size(size_freed)}",
        )
        self._task = None
        QMessageBox.information(self, "清理完成",
                                f"已送資源回收筒: {len(deleted)} 個\n失敗: {len(failed)} 個")
        # Refresh group list, then rebuild the tree so it always matches
        # self.groups. Manually pruning by childCount()==0 was wrong: a group
        # reduced to one remaining file was dropped from self.groups but its
        # single-child tree row survived, desynchronising index lookups.
        deleted_set = set(deleted)
        for g in self.groups:
            g.files = [f for f in g.files if f.path not in deleted_set]
        self.groups = [g for g in self.groups if len(g.files) > 1]
        self._populate()
        total_dups = sum(len(g.files) - 1 for g in self.groups)
        wasted = sum(g.wasted_space for g in self.groups)
        self.stats.setText(f"重複群組: {len(self.groups)} | 多餘檔案: {total_dups} | "
                           f"浪費空間: {format_size(wasted)}")
        self.status(f"清理完成: {len(deleted)} 個檔案")

    def _on_export(self):
        if not self.groups:
            QMessageBox.information(self, "匯出", "尚無搜尋結果可匯出。")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, tr("匯出 Excel"), "duplicate_report.xlsx",
            file_filter("excel")
        )
        if not path:
            return
        path = normalize_path(path)
        try:
            from openpyxl import Workbook

            wb = Workbook()
            ws = wb.active
            ws.title = tr("搜尋摘要")
            ws.append([tr("搜尋路徑"), self.folder.text()])
            ws.append([tr("重複群組數"), len(self.groups)])
            ws.append([
                tr("多餘檔案數"),
                sum(len(g.files) - 1 for g in self.groups),
            ])
            ws.append([
                tr("浪費空間"),
                format_size(sum(g.wasted_space for g in self.groups)),
            ])
            det = wb.create_sheet(tr("重複檔案詳細"))
            det.append([
                tr("群組"), tr("檔名"), tr("大小"), tr("修改時間"),
                tr("路徑"), tr("是否重複"), tr("雜湊"),
            ])
            for gi, g in enumerate(self.groups, 1):
                for fi in g.files:
                    det.append([
                        gi, fi.name, fi.size,
                        format_datetime(fi.modified), fi.path, tr("是"),
                        g.hash,
                    ])
            wb.save(path)
            QMessageBox.information(self, "匯出成功", f"已匯出至 {path}")
        except Exception as exc:
            QMessageBox.warning(self, "匯出失敗", str(exc))

    def on_theme_changed(self):
        self.page_header.set_theme(self.theme())

    def apply_payload(self, payload):
        if not isinstance(payload, dict):
            return
        folder = payload.get("folder")
        if folder and is_dir_fs(folder):
            self.folder.set_path(folder)
            if payload.get("autostart") and not self.scanning:
                QTimer.singleShot(0, self._on_scan)

    def request_stop(self):
        self._scan_timer.stop()
        if self.control and (self.scanning or self.cleaning):
            self.control.cancel()
        if self.worker and self.worker.isRunning():
            self.worker.wait(3000)
        if self.cleaner and self.cleaner.isRunning():
            self.cleaner.wait(3000)
