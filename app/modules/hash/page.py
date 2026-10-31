"""Batch checksum tool and two-file comparison."""

import csv
import os
import time

from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QAbstractItemView, QComboBox, QCheckBox, QFileDialog, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QMessageBox, QProgressBar,
    QPushButton, QStackedWidget, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from app.core.constants import MODULE_HASH
from app.core.hashing import (
    ALGORITHMS, ALGORITHM_LABELS, collect_files, hash_file, hash_tree,
)
from app.core.i18n import file_filter, tr
from app.core.utils import (
    extended_path, format_size, is_dir_fs, normalize_path, short_path,
)
from app.core.workers import CancelledError, OperationControl
from app.ui.base import ModulePage
from app.ui.components import EmptyState, PageHeader, make_button
from app.ui.icons import set_icon
from app.ui.widgets import PathField


class HashWorker(QThread):
    progress = pyqtSignal(int, int, str)
    row = pyqtSignal(object)
    completed = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, targets, recursive, algorithm, control):
        super().__init__()
        self.targets = list(targets)
        self.recursive = recursive
        self.algorithm = algorithm
        self.control = control

    def cancel(self):
        self.control.cancel()

    def run(self):
        try:
            files = list(collect_files(
                self.targets, recursive=self.recursive, control=self.control
            ))
            total = len(files)
            summary = {"done": 0, "failed": 0, "elapsed": 0.0}
            started = time.time()
            for index, (path, size) in enumerate(files, 1):
                self.control.checkpoint()
                self.progress.emit(index, total, path)
                started_file = time.time()
                try:
                    digest = hash_file(
                        path, self.algorithm, control=self.control
                    )
                    self.row.emit({
                        "path": path, "size": size, "digest": digest,
                        "error": "",
                        "elapsed": time.time() - started_file,
                    })
                    summary["done"] += 1
                except CancelledError:
                    raise
                except Exception as exc:
                    self.row.emit({
                        "path": path, "size": size, "digest": "",
                        "error": str(exc),
                        "elapsed": time.time() - started_file,
                    })
                    summary["failed"] += 1
            summary["elapsed"] = time.time() - started
            self.completed.emit(summary)
        except CancelledError:
            self.completed.emit({"done": 0, "failed": 0,
                                 "elapsed": 0.0, "cancelled": True})
        except Exception as exc:
            self.failed.emit(str(exc))


class HashCompareWorker(QThread):
    completed = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, left, right, algorithm, control):
        super().__init__()
        self.left = left
        self.right = right
        self.algorithm = algorithm
        self.control = control

    def cancel(self):
        self.control.cancel()

    def run(self):
        try:
            if is_dir_fs(self.left) and is_dir_fs(self.right):
                left = hash_tree(self.left, self.algorithm, control=self.control)
                right = hash_tree(self.right, self.algorithm, control=self.control)
            else:
                left = hash_file(self.left, self.algorithm, control=self.control)
                right = hash_file(self.right, self.algorithm, control=self.control)
            self.completed.emit((left, right))
        except CancelledError:
            self.completed.emit(None)
        except Exception as exc:
            self.failed.emit(str(exc))


class HashPage(ModulePage):
    title = "雜湊工具"
    module_id = MODULE_HASH

    def __init__(self, settings, main_window=None):
        super().__init__(settings, main_window)
        self.worker = None
        self.compare_worker = None
        self.control = None
        self._task = None
        self._build_ui()
        self.algorithm.setCurrentText(
            ALGORITHM_LABELS.get(
                self.settings.option("hash_algorithm", "sha256"), "SHA-256"
            )
        )
        self.recursive.setChecked(self.settings.option("hash_recursive", True))

    def _algorithm_key(self):
        data = self.algorithm.currentData()
        if data:
            return data
        text = self.algorithm.currentText()
        for key, label in ALGORITHM_LABELS.items():
            if label == text:
                return key
        return "sha256"

    def _build_ui(self):
        root = QVBoxLayout(self)
        self.page_header = PageHeader(
            "雜湊工具",
            "批次計算 MD5 / SHA-1 / SHA-256，或比對兩個檔案與資料夾",
            icon="hash",
            theme=self.theme(),
        )
        root.addWidget(self.page_header)
        targets_box = QGroupBox("要計算的檔案／資料夾")
        targets_layout = QVBoxLayout(targets_box)
        row = QHBoxLayout()
        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText("輸入檔案或資料夾路徑")
        row.addWidget(self.path_edit, 1)
        add_file = QPushButton("加入檔案")
        add_file.clicked.connect(self._add_file)
        add_dir = QPushButton("加入資料夾")
        add_dir.clicked.connect(self._add_folder)
        remove = QPushButton("移除選取")
        remove.clicked.connect(self._remove_selected)
        clear = QPushButton("清空")
        clear.clicked.connect(lambda: self.targets.clear())
        row.addWidget(add_file)
        row.addWidget(add_dir)
        row.addWidget(remove)
        row.addWidget(clear)
        targets_layout.addLayout(row)
        self.targets = QListWidget()
        self.targets.setMaximumHeight(100)
        targets_layout.addWidget(self.targets)
        root.addWidget(targets_box)

        options = QHBoxLayout()
        self.recursive = QCheckBox("資料夾包含子資料夾")
        options.addWidget(self.recursive)
        options.addWidget(QLabel("演算法:"))
        self.algorithm = QComboBox()
        for key in ALGORITHMS:
            self.algorithm.addItem(ALGORITHM_LABELS[key], key)
        options.addWidget(self.algorithm)
        options.addStretch(1)
        self.start_btn = QPushButton("開始計算")
        self.start_btn.setProperty("variant", "primary")
        set_icon(self.start_btn, "play", self.theme(), "primary_text", 15)
        self.start_btn.clicked.connect(self._on_start)
        self.stop_btn = QPushButton("停止")
        self.stop_btn.setEnabled(False)
        set_icon(self.stop_btn, "stop", self.theme(), "text", 14)
        self.stop_btn.clicked.connect(self._on_stop)
        options.addWidget(self.start_btn)
        options.addWidget(self.stop_btn)
        root.addLayout(options)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setVisible(False)
        root.addWidget(self.progress)
        self.status_label = QLabel("尚未計算")
        self.status_label.setProperty("role", "hint")
        root.addWidget(self.status_label)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["檔案", "大小", "雜湊", "狀態"])
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self.table.verticalHeader().setVisible(False)
        self.table.setColumnWidth(0, 300)
        self.table.setColumnWidth(1, 90)
        self.table.setColumnWidth(2, 480)
        self.table.setColumnWidth(3, 150)
        empty_action = make_button(
            "加入檔案", "plus", self.theme(), "primary"
        )
        empty_action.clicked.connect(self._add_file)
        self.empty_results = EmptyState(
            "尚未計算雜湊",
            "加入檔案或資料夾，選擇演算法後開始計算。",
            icon="hash",
            action=empty_action,
            theme=self.theme(),
        )
        self.results_stack = QStackedWidget()
        self.results_stack.addWidget(self.empty_results)
        self.results_stack.addWidget(self.table)
        root.addWidget(self.results_stack, 1)

        buttons = QHBoxLayout()
        copy_btn = QPushButton("複製選取雜湊")
        set_icon(copy_btn, "copy", self.theme(), "text", 15)
        copy_btn.clicked.connect(self._copy_digest)
        export_btn = QPushButton("匯出 CSV")
        set_icon(export_btn, "download", self.theme(), "text", 15)
        export_btn.clicked.connect(self._export)
        buttons.addWidget(copy_btn)
        buttons.addWidget(export_btn)
        buttons.addStretch(1)
        root.addLayout(buttons)

        compare_box = QGroupBox("兩檔／兩資料夾比對")
        compare_layout = QVBoxLayout(compare_box)
        self.compare_folders = QCheckBox("比對整個資料夾")
        self.compare_folders.toggled.connect(self._toggle_compare_mode)
        compare_layout.addWidget(self.compare_folders)
        left_row = QHBoxLayout()
        self.left = PathField(mode="file", settings=self.settings,
                              field_name="hash_left", placeholder="左側檔案")
        left_row.addWidget(self.left, 1)
        self.right = PathField(mode="file", settings=self.settings,
                               field_name="hash_right", placeholder="右側檔案")
        left_row.addWidget(self.right, 1)
        compare_btn = QPushButton("比對雜湊")
        compare_btn.clicked.connect(self._compare)
        left_row.addWidget(compare_btn)
        compare_layout.addLayout(left_row)
        self.compare_result = QLabel("")
        self.compare_result.setWordWrap(True)
        compare_layout.addWidget(self.compare_result)
        root.addWidget(compare_box)

    def _add_file(self):
        path, _ = QFileDialog.getOpenFileName(self, tr("選擇檔案"))
        if not path:
            return
        path = normalize_path(path)
        if path not in [self.targets.item(i).text()
                        for i in range(self.targets.count())]:
            self.targets.addItem(path)

    def _add_folder(self):
        path = QFileDialog.getExistingDirectory(self, tr("選擇資料夾"))
        if not path:
            return
        path = normalize_path(path)
        if path not in [self.targets.item(i).text()
                        for i in range(self.targets.count())]:
            self.targets.addItem(path)

    def _remove_selected(self):
        for item in self.targets.selectedItems():
            self.targets.takeItem(self.targets.row(item))

    def _targets(self):
        return [self.targets.item(i).text()
                for i in range(self.targets.count())]

    def _on_start(self):
        targets = self._targets()
        if not targets:
            text = normalize_path(self.path_edit.text())
            if text:
                targets = [text]
                self.targets.addItem(text)
        valid = [path for path in targets if os.path.exists(path)]
        if not valid:
            QMessageBox.information(self, "雜湊", "請先加入有效的檔案或資料夾。")
            return
        if self.worker is not None and self.worker.isRunning():
            return
        self.settings.set_option("hash_algorithm", self._algorithm_key())
        self.settings.set_option("hash_recursive", self.recursive.isChecked())
        self.table.setRowCount(0)
        self.control = OperationControl()
        self.worker = HashWorker(
            valid, self.recursive.isChecked(), self._algorithm_key(),
            self.control,
        )
        self.worker.progress.connect(self._on_progress)
        self.worker.row.connect(self._add_row)
        self.worker.completed.connect(self._on_complete)
        self.worker.failed.connect(self._on_failed)
        self._task = self.task_add(
            "hash", "計算雜湊", control=self.control,
        )
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.progress.setVisible(True)
        self.progress.setRange(0, 0)
        self.status_label.setText("正在收集檔案...")
        self.empty_results.set_content(
            "計算中...", "正在收集目標檔案並計算雜湊。"
        )
        self.results_stack.setCurrentWidget(self.empty_results)
        self.status("計算雜湊中...")
        self.worker.start()

    def _on_progress(self, done, total, path):
        self.progress.setRange(0, max(1, total))
        self.progress.setValue(done)
        self.status_label.setText(
            f"{done}/{total} · {short_path(path, 70)}"
        )
        self.task_update(self._task, done=done, total=total,
                         message=short_path(path, 60))

    def _add_row(self, result):
        self.results_stack.setCurrentWidget(self.table)
        row = self.table.rowCount()
        self.table.insertRow(row)
        name = os.path.basename(result["path"]) or result["path"]
        name_item = QTableWidgetItem(name)
        name_item.setToolTip(result["path"])
        self.table.setItem(row, 0, name_item)
        self.table.setItem(row, 1, QTableWidgetItem(format_size(result["size"])))
        digest_item = QTableWidgetItem(result["digest"])
        digest_item.setFont(QFont("Consolas", 9))
        self.table.setItem(row, 2, digest_item)
        status = (
            tr("完成") if not result["error"]
            else f"{tr('失敗')}: {result['error']}"
        )
        self.table.setItem(row, 3, QTableWidgetItem(status))

    def _on_complete(self, summary):
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.progress.setVisible(False)
        if summary.get("cancelled"):
            self.status_label.setText("已取消")
            self.task_finish(self._task, status="cancelled")
        else:
            self.status_label.setText(
                f"{tr('完成')} {summary['done']} · "
                f"{tr('失敗')} {summary['failed']} · "
                f"{summary['elapsed']:.1f} {tr('秒')}"
            )
            if self.table.rowCount() == 0:
                self.empty_results.set_content(
                    "沒有可計算的檔案", "請確認目標路徑存在且可讀取。"
                )
                self.results_stack.setCurrentWidget(self.empty_results)
            self.task_finish(
                self._task, message=f"完成 {summary['done']} 個檔案"
            )
            self.status(
                f"{tr('雜湊完成：')}{summary['done']} {tr('個檔案')}"
            )
        self._task = None

    def _on_failed(self, message):
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.progress.setVisible(False)
        self.task_finish(self._task, status="failed", error=message)
        self._task = None
        QMessageBox.warning(self, "雜湊失敗", message)

    def _on_stop(self):
        if self.control is not None:
            self.control.cancel()

    def _copy_digest(self):
        row = self.table.currentRow()
        if row < 0:
            return
        item = self.table.item(row, 2)
        if item is not None:
            from PyQt6.QtWidgets import QApplication

            QApplication.clipboard().setText(item.text())
            self.status("已複製雜湊值")

    def _export(self):
        if self.table.rowCount() == 0:
            QMessageBox.information(self, "匯出", "尚無雜湊結果。")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, tr("匯出雜湊結果"), "hash_report.csv", file_filter("csv")
        )
        if not path:
            return
        path = normalize_path(path)
        try:
            with open(path, "w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow([
                    tr("路徑"), tr("大小"), tr("演算法"), tr("雜湊"),
                    tr("狀態"),
                ])
                for row in range(self.table.rowCount()):
                    writer.writerow([
                        self.table.item(row, 0).toolTip(),
                        self.table.item(row, 1).text(),
                        self.algorithm.currentText(),
                        self.table.item(row, 2).text(),
                        self.table.item(row, 3).text(),
                    ])
            self.status(f"已匯出雜湊結果: {path}")
        except Exception as exc:
            QMessageBox.warning(self, "匯出失敗", str(exc))

    def _toggle_compare_mode(self, folders):
        mode = "dir" if folders else "file"
        self.left.mode = mode
        self.right.mode = mode
        self.left.line.setPlaceholderText(
            "左側資料夾" if folders else "左側檔案"
        )
        self.right.line.setPlaceholderText(
            "右側資料夾" if folders else "右側檔案"
        )

    def _compare(self):
        left, right = self.left.text(), self.right.text()
        if self.compare_folders.isChecked():
            valid = is_dir_fs(left) and is_dir_fs(right)
            message = "請選擇兩個有效資料夾。"
        else:
            valid = os.path.isfile(left) and os.path.isfile(right)
            message = "請選擇兩個有效檔案。"
        if not valid:
            QMessageBox.warning(self, "比對", message)
            return
        if self.compare_worker is not None and self.compare_worker.isRunning():
            return
        self.control = OperationControl()
        self.compare_worker = HashCompareWorker(
            left, right, self._algorithm_key(), self.control
        )
        self.compare_worker.completed.connect(self._on_compare_complete)
        self.compare_worker.failed.connect(self._on_compare_failed)
        self._task = self.task_add(
            "hash_compare", "比對檔案雜湊", control=self.control,
            total=2,
        )
        self.compare_result.setText(tr("比對中..."))
        self.compare_worker.start()

    def _on_compare_complete(self, result):
        if result is None:
            self.compare_result.setText(tr("已取消"))
            self.task_finish(self._task, status="cancelled")
            self._task = None
            return
        left, right = result
        self.task_update(self._task, done=2, total=2)
        self.task_finish(self._task, message=tr("比對完成"))
        self._task = None
        if left == right:
            self.compare_result.setText(
                f"{tr('相同')}\n{left}\n{right}"
            )
        else:
            self.compare_result.setText(
                f"{tr('不同')}\n{tr('左')}: {left}\n"
                f"{tr('右')}: {right}"
            )

    def _on_compare_failed(self, message):
        self.compare_result.setText(tr("比對失敗：") + message)
        self.task_finish(self._task, status="failed", error=message)
        self._task = None
        QMessageBox.warning(self, "比對失敗", message)

    def on_theme_changed(self):
        self.page_header.set_theme(self.theme())
        self.empty_results.set_theme(self.theme())

    def apply_payload(self, payload):
        if not isinstance(payload, dict):
            return
        for path in payload.get("files", []) or []:
            if os.path.exists(extended_path(path)) and path not in self._targets():
                self.targets.addItem(path)
        if payload.get("folder") and is_dir_fs(payload["folder"]):
            if payload["folder"] not in self._targets():
                self.targets.addItem(payload["folder"])

    def request_stop(self):
        for worker in (self.worker, self.compare_worker):
            if worker is not None and worker.isRunning():
                worker.cancel()
                worker.wait(5000)
