"""Folder comparison and safe one-way synchronisation."""

import csv

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QFileDialog,
    QHBoxLayout, QHeaderView, QLabel, QMenu, QMessageBox, QPlainTextEdit,
    QProgressBar, QPushButton, QStackedWidget, QToolButton, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout,
)

from app.core.i18n import file_filter, tr
from app.core.compare import (
    STATUS_LABELS, STATUS_ORDER, STATUS_SAME, SyncWorker,
    build_sync_plan, compare_folders,
)
from app.core.constants import MODULE_COMPARE
from app.core.file_ops import TrashWorker
from app.core.history import record_operation
from app.core.utils import (
    format_datetime, format_size, is_dir_fs, normalize_path, short_path,
)
from app.core.workers import CancelledError, OperationControl
from app.ui.base import ModulePage
from app.ui.components import EmptyState, PageHeader, make_button
from app.ui.icons import set_icon
from app.ui.widgets import PathField


class CompareWorker(QThread):
    progress = pyqtSignal(str, int)
    completed = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, left, right, options, control):
        super().__init__()
        self.left = left
        self.right = right
        self.options = options
        self.control = control

    def run(self):
        try:
            result = compare_folders(
                self.left, self.right, control=self.control,
                progress=self.progress.emit, **self.options,
            )
            self.completed.emit(result)
        except CancelledError:
            self.completed.emit(None)
        except Exception as exc:
            self.failed.emit(str(exc))

    def cancel(self):
        self.control.cancel()


class SyncPreviewDialog(QDialog):
    """Show the planned operations before touching the filesystem."""

    def __init__(self, result, selected_entries, parent=None):
        super().__init__(parent)
        self.result = result
        self.selected_entries = list(selected_entries)
        self.actions = []
        self.setWindowTitle("同步預覽")
        self.resize(760, 520)

        layout = QVBoxLayout(self)
        row = QHBoxLayout()
        row.addWidget(QLabel("方向:"))
        self.direction = QComboBox()
        self.direction.addItem("左 → 右", "l2r")
        self.direction.addItem("右 → 左", "r2l")
        row.addWidget(self.direction)
        row.addStretch(1)
        self.use_selection = QCheckBox("只處理選取項目")
        self.use_selection.setChecked(bool(self.selected_entries))
        self.use_selection.setEnabled(bool(self.selected_entries))
        row.addWidget(self.use_selection)
        layout.addLayout(row)

        options = QHBoxLayout()
        self.only = QCheckBox("包含僅單側項目")
        self.only.setChecked(True)
        self.newer = QCheckBox("包含較新檔案")
        self.newer.setChecked(True)
        self.diff = QCheckBox("包含內容不同")
        self.diff.setChecked(True)
        self.mirror = QCheckBox("鏡像刪除目標多餘項目")
        for checkbox in (self.only, self.newer, self.diff, self.mirror):
            options.addWidget(checkbox)
        options.addStretch(1)
        layout.addLayout(options)

        warning = QLabel(
            "鏡像刪除會把目標資料夾中來源沒有的項目送至資源回收筒。"
            "執行前請先確認預覽清單。"
        )
        warning.setProperty("role", "hint")
        warning.setWordWrap(True)
        layout.addWidget(warning)

        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        layout.addWidget(self.preview, 1)

        buttons = QHBoxLayout()
        self.count_label = QLabel("")
        self.count_label.setProperty("role", "hint")
        buttons.addWidget(self.count_label, 1)
        execute = QPushButton("執行同步")
        execute.setProperty("variant", "primary")
        set_icon(
            execute, "sync",
            self.theme() if hasattr(self, "theme") else "dark",
            "primary_text", 15,
        )
        execute.clicked.connect(self._execute)
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(execute)
        buttons.addWidget(cancel)
        layout.addLayout(buttons)

        for widget in (self.direction, self.use_selection, self.only,
                       self.newer, self.diff, self.mirror):
            if isinstance(widget, QCheckBox):
                widget.toggled.connect(self._update_preview)
            else:
                widget.currentIndexChanged.connect(self._update_preview)
        self._update_preview()

    def _update_preview(self):
        entries = (self.selected_entries if self.use_selection.isChecked()
                   and self.selected_entries else self.result.entries)
        try:
            self.actions = build_sync_plan(
                self.result, self.direction.currentData(), entries=entries,
                include_only=self.only.isChecked(),
                include_newer=self.newer.isChecked(),
                include_diff=self.diff.isChecked(),
                mirror=self.mirror.isChecked(),
            )
        except ValueError as exc:
            self.actions = []
            self.preview.setPlainText(f"已停止建立同步計劃：{exc}")
            self.count_label.setText("不可執行")
            return
        lines = []
        for action in self.actions:
            kind = action["action"]
            if kind == "copy":
                lines.append(f"{tr('[複製] ')}{action['relative']}")
            elif kind == "mkdir":
                lines.append(f"{tr('[建立] ')}{action['relative']}")
            elif kind == "delete":
                lines.append(f"{tr('[刪除] ')}{action['relative']}")
            else:
                lines.append(
                    f"{tr('[衝突] ')}{action['relative']} - "
                    f"{tr(action['message'])}"
                )
        self.preview.setPlainText(
            "\n".join(lines) or tr("沒有需要執行的動作。")
        )
        self.count_label.setText(f"預計 {len(self.actions)} 個動作")

    def _execute(self):
        if not self.actions:
            QMessageBox.information(self, "同步", "沒有需要執行的動作。")
            return
        if self.mirror.isChecked():
            answer = QMessageBox.question(
                self, "確認鏡像刪除",
                "鏡像模式會刪除目標資料夾中來源沒有的項目。\n"
                "刪除會送至資源回收筒，仍要繼續嗎？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        self.accept()


class ComparePage(ModulePage):
    title = "資料夾比對"
    module_id = MODULE_COMPARE

    def __init__(self, settings, main_window=None):
        super().__init__(settings, main_window)
        self.result = None
        self.scan_worker = None
        self.control = None
        self.sync_worker = None
        self.trash_worker = None
        self._task = None
        self._build_ui()
        self._load_options()

    def _build_ui(self):
        root = QVBoxLayout(self)
        self.page_header = PageHeader(
            "資料夾比對",
            "比較兩個資料夾的差異，先預覽再同步或清理",
            icon="compare",
            theme=self.theme(),
        )
        root.addWidget(self.page_header)
        paths = QHBoxLayout()
        self.left = PathField(
            settings=self.settings, field_name="compare_left",
            placeholder="左側資料夾",
        )
        self.right = PathField(
            settings=self.settings, field_name="compare_right",
            placeholder="右側資料夾",
        )
        paths.addWidget(QLabel("左"))
        paths.addWidget(self.left, 1)
        paths.addWidget(QLabel("右"))
        paths.addWidget(self.right, 1)
        root.addLayout(paths)

        options = QHBoxLayout()
        self.recursive = QCheckBox("包含子資料夾")
        self.recursive.setChecked(True)
        self.compare_hash = QCheckBox("內容 SHA-256 比對")
        self.ignore_times = QCheckBox("忽略修改時間")
        options.addWidget(self.recursive)
        options.addWidget(self.compare_hash)
        options.addWidget(self.ignore_times)
        options.addStretch(1)
        self.scan_btn = QPushButton("開始比對")
        self.scan_btn.setProperty("variant", "primary")
        set_icon(self.scan_btn, "compare", self.theme(), "primary_text", 16)
        self.scan_btn.clicked.connect(self._on_scan)
        self.stop_btn = QPushButton("停止")
        self.stop_btn.setEnabled(False)
        set_icon(self.stop_btn, "stop", self.theme(), "text", 15)
        self.stop_btn.clicked.connect(self._on_stop)
        options.addWidget(self.scan_btn)
        options.addWidget(self.stop_btn)
        root.addLayout(options)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setVisible(False)
        root.addWidget(self.progress)
        self.summary = QLabel("選擇左右資料夾後開始比對")
        root.addWidget(self.summary)

        actions = QHBoxLayout()
        self.filter = QComboBox()
        self.filter.addItem(tr("全部差異"), "")
        for status in STATUS_ORDER:
            if status == STATUS_SAME:
                continue
            self.filter.addItem(tr(STATUS_LABELS[status]), status)
        self.filter.currentIndexChanged.connect(self._populate)
        actions.addWidget(QLabel("顯示:"))
        actions.addWidget(self.filter)
        select_all = make_button("全選", "check", self.theme(), "ghost")
        select_all.clicked.connect(lambda: self._select_all(True))
        deselect = make_button("取消全選", "x", self.theme(), "ghost")
        deselect.clicked.connect(lambda: self._select_all(False))
        copy_right = make_button("左 → 右複製", "arrow-right", self.theme())
        copy_right.clicked.connect(lambda: self._copy_selected("l2r"))
        copy_left = make_button("右 → 左複製", "arrow-left", self.theme())
        copy_left.clicked.connect(lambda: self._copy_selected("r2l"))
        sync_btn = make_button(
            "同步預覽", "sync", self.theme(), "primary"
        )
        sync_btn.clicked.connect(self._open_sync_preview)
        export_btn = make_button("匯出 CSV", "download", self.theme(), "ghost")
        export_btn.clicked.connect(self._export)
        for widget in (select_all, deselect, copy_right, copy_left):
            actions.addWidget(widget)
        actions.addStretch(1)

        self.more_btn = QToolButton()
        self.more_btn.setText("更多")
        self.more_btn.setPopupMode(
            QToolButton.ToolButtonPopupMode.InstantPopup
        )
        more_menu = QMenu(self)
        delete_left = more_menu.addAction("刪除左側選取")
        delete_left.triggered.connect(
            lambda _=False: self._delete_selected("left")
        )
        delete_right = more_menu.addAction("刪除右側選取")
        delete_right.triggered.connect(
            lambda _=False: self._delete_selected("right")
        )
        self.more_btn.setMenu(more_menu)
        actions.addWidget(self.more_btn)
        actions.addWidget(sync_btn)
        actions.addWidget(export_btn)
        root.addLayout(actions)

        self.tree = QTreeWidget()
        self.tree.setObjectName("compareTree")
        self.tree.setHeaderLabels([
            "狀態", "相對路徑", "左類型", "左大小", "左修改時間",
            "右類型", "右大小", "右修改時間",
        ])
        self.tree.setAlternatingRowColors(True)
        self.tree.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        header = self.tree.header()
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for column in (0, 2, 3, 4, 5, 6, 7):
            header.setSectionResizeMode(
                column, QHeaderView.ResizeMode.ResizeToContents
            )
        start_action = make_button(
            "開始比對", "compare", self.theme(), "primary"
        )
        start_action.clicked.connect(self._on_scan)
        self.empty_results = EmptyState(
            "尚未比對資料夾",
            "選擇左右資料夾後開始比對，差異會顯示在這裡。",
            icon="compare",
            action=start_action,
            theme=self.theme(),
        )
        self.tree_stack = QStackedWidget()
        self.tree_stack.addWidget(self.empty_results)
        self.tree_stack.addWidget(self.tree)
        root.addWidget(self.tree_stack, 1)

    def _load_options(self):
        self.recursive.setChecked(self.settings.option("compare_recursive", True))
        self.compare_hash.setChecked(
            self.settings.option("compare_hash", False)
        )
        self.ignore_times.setChecked(
            self.settings.option("compare_ignore_times", False)
        )

    def _on_scan(self):
        left, right = self.left.text(), self.right.text()
        if not left or not right or not is_dir_fs(left) or not is_dir_fs(right):
            QMessageBox.warning(self, "資料夾錯誤", "請選擇左右兩邊的有效資料夾。")
            return
        if self.scan_worker is not None and self.scan_worker.isRunning():
            return
        self.settings.set_options({
            "compare_recursive": self.recursive.isChecked(),
            "compare_hash": self.compare_hash.isChecked(),
            "compare_ignore_times": self.ignore_times.isChecked(),
        })
        self.settings.remember_path("compare_left", left)
        self.settings.remember_path("compare_right", right)
        self.tree.clear()
        self.result = None
        self.control = OperationControl()
        options = {
            "recursive": self.recursive.isChecked(),
            "compare_hash": self.compare_hash.isChecked(),
            "ignore_timestamps": self.ignore_times.isChecked(),
        }
        self.scan_worker = CompareWorker(left, right, options, self.control)
        self.scan_worker.progress.connect(self._on_progress)
        self.scan_worker.completed.connect(self._on_complete)
        self.scan_worker.failed.connect(self._on_failed)
        self._task = self.task_add(
            "compare", "比對資料夾", control=self.control,
            message="建立檔案清單...",
        )
        self.scan_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.progress.setVisible(True)
        self.progress.setRange(0, 0)
        self.summary.setText("比對中...")
        self.empty_results.set_content(
            "比對中...", "正在收集左右資料夾的檔案清單。"
        )
        self.tree_stack.setCurrentWidget(self.empty_results)
        self.status("比對資料夾中...")
        self.scan_worker.start()

    def _on_progress(self, side, count):
        label = "左側" if side == "left" else "右側"
        self.summary.setText(f"正在收集{label}項目：{count:,}")
        self.task_update(self._task, message=f"{label} {count:,} 個項目")

    def _on_complete(self, result):
        self.scan_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.progress.setVisible(False)
        if result is None:
            self.summary.setText("已取消比對")
            self.task_finish(self._task, status="cancelled")
            self._task = None
            return
        self.result = result
        self._populate()
        self._update_filter_counts()
        if self.tree.topLevelItemCount():
            self.tree_stack.setCurrentWidget(self.tree)
        else:
            self.empty_results.set_content(
                "沒有差異", "兩個資料夾在目前條件下內容相同。"
            )
            self.tree_stack.setCurrentWidget(self.empty_results)
        differences = result.total_differences()
        total_items = sum(result.counts.values())
        self.summary.setText(
            f"項目 {total_items:,} · 差異 {differences:,}"
            f" · 相同 {result.counts.get(STATUS_SAME, 0):,}"
            f" · 略過 {result.errors} 個無法讀取項目"
        )
        self.task_finish(self._task, message=f"找到 {differences} 個差異")
        self.status(f"比對完成：{differences} 個差異")
        self._task = None

    def _on_failed(self, message):
        self.scan_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.progress.setVisible(False)
        self.task_finish(self._task, status="failed", error=message)
        self._task = None
        QMessageBox.warning(self, "比對失敗", message)

    def _on_stop(self):
        if self.control is not None:
            self.control.cancel()

    def _update_filter_counts(self):
        if self.result is None:
            return
        current = self.filter.currentData()
        self.filter.blockSignals(True)
        for index in range(1, self.filter.count()):
            status = self.filter.itemData(index)
            label = STATUS_LABELS.get(status, status)
            count = self.result.counts.get(status, 0)
            self.filter.setItemText(index, f"{label} ({count})")
        found = self.filter.findData(current)
        if found >= 0:
            self.filter.setCurrentIndex(found)
        self.filter.blockSignals(False)

    def _populate(self):
        self.tree.clear()
        if self.result is None:
            return
        wanted = self.filter.currentData() or ""
        colors = {
            "only_left": "#4a90e2" if self.theme() == "dark" else "#2f6fed",
            "only_right": "#3fb950" if self.theme() == "dark" else "#28a745",
            "left_newer": "#e6973f" if self.theme() == "dark" else "#b5651d",
            "right_newer": "#d19a66" if self.theme() == "dark" else "#8a5a20",
            "content_diff": "#e85a6a" if self.theme() == "dark" else "#dc3545",
            "size_diff": "#e85a6a" if self.theme() == "dark" else "#dc3545",
            "type_conflict": "#b48ead" if self.theme() == "dark" else "#8e6bbf",
        }
        for entry in self.result.entries:
            if wanted and entry.status != wanted:
                continue
            item = QTreeWidgetItem(self.tree)
            item.setText(
                0, tr(STATUS_LABELS.get(entry.status, entry.status))
            )
            item.setForeground(0, QColor(colors.get(entry.status, "#999")))
            item.setText(1, entry.relative)
            item.setToolTip(1, entry.left_path or entry.right_path)
            item.setText(2, entry.left_kind if entry.left_path else "—")
            item.setText(3, format_size(entry.left_size)
                         if entry.left_path and not entry.left_is_dir else "—")
            item.setText(4, format_datetime(entry.left_mtime)
                         if entry.left_path else "—")
            item.setText(5, entry.right_kind if entry.right_path else "—")
            item.setText(6, format_size(entry.right_size)
                         if entry.right_path and not entry.right_is_dir else "—")
            item.setText(7, format_datetime(entry.right_mtime)
                         if entry.right_path else "—")
            item.setData(0, Qt.ItemDataRole.UserRole, entry)

    def _select_all(self, selected):
        for index in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(index)
            item.setSelected(selected)

    def _selected_entries(self):
        entries = []
        for item in self.tree.selectedItems():
            entry = item.data(0, Qt.ItemDataRole.UserRole)
            if entry is not None:
                entries.append(entry)
        return entries

    def _copy_selected(self, direction):
        entries = self._selected_entries()
        if not entries:
            QMessageBox.information(self, "複製", "請先選取要複製的差異項目。")
            return
        try:
            actions = build_sync_plan(
                self.result, direction, entries=entries, include_only=True,
                include_newer=True, include_diff=True, mirror=False,
            )
        except ValueError as exc:
            QMessageBox.warning(self, "同步已停止", str(exc))
            return
        self._run_actions(actions)

    def _open_sync_preview(self):
        if self.result is None:
            QMessageBox.information(self, "同步", "請先執行資料夾比對。")
            return
        dialog = SyncPreviewDialog(
            self.result, self._selected_entries(), self
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._run_actions(dialog.actions)

    def _run_actions(self, actions):
        executable = [a for a in actions if a["action"] in ("copy", "mkdir")]
        conflicts = [a for a in actions if a["action"] == "conflict"]
        deletes = [a for a in actions if a["action"] == "delete"]
        if not executable and not deletes:
            if conflicts:
                QMessageBox.information(
                    self, "同步", "只有類型衝突，沒有可自動執行的動作。"
                )
            else:
                QMessageBox.information(self, "同步", "沒有需要執行的動作。")
            return
        if self.sync_worker is not None and self.sync_worker.isRunning():
            return
        self.control = OperationControl()
        self.sync_worker = SyncWorker(
            actions,
            self.control, verify=self.settings.option("verify_copy", True),
        )
        self.sync_worker.progress.connect(self._on_sync_progress)
        self.sync_worker.completed.connect(self._on_sync_complete)
        total = len(self.sync_worker.actions)
        self._task = self.task_add(
            "sync", "資料夾同步", control=self.control, total=total,
        )
        self.sync_worker.start()
        self.progress.setVisible(True)
        self.progress.setRange(0, max(1, total))
        self.progress.setValue(0)
        self.status(f"同步 {total} 個動作...")

    def _on_sync_progress(self, done, total, relative):
        self.progress.setRange(0, max(1, total))
        self.progress.setValue(done)
        self.task_update(self._task, done=done, total=total,
                         message=short_path(relative, 60))
        self.status(f"同步中 {done}/{total}：{short_path(relative, 50)}")

    def _on_sync_complete(self, summary):
        self.progress.setVisible(False)
        status = "cancelled" if summary.get("cancelled") else "done"
        message = (
            f"{tr('已複製')} {summary['copied']} · "
            f"{tr('已刪除')} {summary['deleted']} · "
            f"{tr('失敗')} {summary['failed']} · "
            f"{tr('已跳過')} {summary['skipped']} · "
            f"{tr('衝突')} {summary.get('conflicts', 0)}"
        )
        self.task_finish(self._task, status=status, message=message)
        self._task = None
        record_operation(
            self.settings, MODULE_COMPARE, self.left.text(),
            f"{tr('同步')}: {message}", summary["copied"],
            summary["failed"],
        )
        if summary.get("errors"):
            QMessageBox.warning(
                self, "同步完成但有錯誤",
                message + "\n\n" + "\n".join(
                    f"{path}: {error}"
                    for path, error in summary["errors"][:10]
                ),
            )
        else:
            QMessageBox.information(self, "同步完成", message)
        self._on_scan()

    def _delete_selected(self, side):
        entries = self._selected_entries()
        paths = []
        for entry in entries:
            path = entry.left_path if side == "left" else entry.right_path
            if path:
                paths.append(path)
        if not paths:
            QMessageBox.information(self, "刪除", "選取項目在該側沒有檔案。")
            return
        answer = QMessageBox.question(
            self, "刪除選取項目",
            f"要將 {len(paths)} 個項目移至資源回收筒嗎？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.trash_worker = TrashWorker(paths, OperationControl())
        self._task = self.task_add(
            "compare_delete", "刪除比對項目", control=self.trash_worker.control,
            total=len(paths),
        )
        self.trash_worker.progress.connect(
            lambda done, total: self.task_update(
                self._task, done=done, total=total
            )
        )
        self.trash_worker.completed.connect(self._on_delete_complete)
        self.trash_worker.start()

    def _on_delete_complete(self, deleted, failed):
        self.task_finish(
            self._task,
            status="done" if not failed else "failed",
            message=f"刪除 {len(deleted)} · 失敗 {len(failed)}",
        )
        self._task = None
        record_operation(
            self.settings, MODULE_COMPARE, self.left.text(),
            f"刪除 {len(deleted)} 個比對項目", len(deleted), len(failed),
        )
        self.status(f"已刪除 {len(deleted)} 個項目，失敗 {len(failed)}")
        self._on_scan()

    def _export(self):
        if self.result is None or not self.result.entries:
            QMessageBox.information(self, "匯出", "尚無比對結果可匯出。")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, tr("匯出比對結果"), "compare_report.csv", file_filter("csv")
        )
        if not path:
            return
        path = normalize_path(path)
        try:
            with open(path, "w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow([
                    tr("狀態"), tr("相對路徑"), tr("左路徑"), tr("右路徑"),
                    tr("左大小"), tr("右大小"), tr("左修改時間"),
                    tr("右修改時間"),
                ])
                for entry in self.result.entries:
                    writer.writerow([
                        tr(STATUS_LABELS.get(entry.status, entry.status)),
                        entry.relative, entry.left_path, entry.right_path,
                        entry.left_size, entry.right_size,
                        format_datetime(entry.left_mtime),
                        format_datetime(entry.right_mtime),
                    ])
            self.status(f"已匯出比對結果: {path}")
        except Exception as exc:
            QMessageBox.warning(self, "匯出失敗", str(exc))

    def on_theme_changed(self):
        self.page_header.set_theme(self.theme())
        self.empty_results.set_theme(self.theme())
        self._populate()

    def apply_payload(self, payload):
        if not isinstance(payload, dict):
            return
        if payload.get("left"):
            self.left.set_path(payload["left"])
        if payload.get("right"):
            self.right.set_path(payload["right"])

    def request_stop(self):
        for worker in (self.scan_worker, self.sync_worker):
            if worker is not None and worker.isRunning():
                worker.cancel()
                worker.wait(3000)
        if self.trash_worker is not None and self.trash_worker.isRunning():
            self.trash_worker.cancel()
            self.trash_worker.wait(3000)
