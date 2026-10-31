"""Copy module page (migrated from Batch_FileCopy, PyQt5 -> PyQt6)."""

import os
import csv

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QRadioButton, QButtonGroup,
    QStackedWidget, QSpinBox, QDoubleSpinBox, QCheckBox, QPushButton,
    QProgressBar, QLabel, QTableWidget, QTableWidgetItem, QComboBox,
    QTextEdit, QPlainTextEdit, QMessageBox, QFileDialog, QTabWidget,
)

from app.core.i18n import file_filter, tr, tr_exact
from app.ui.base import ModulePage
from app.ui.components import PageHeader
from app.ui.icons import set_icon
from app.ui.widgets import PathField, ExtensionChips, HintLabel
from app.modules.copier.worker import TransferWorker, ScanWorker
from app.core.workers import OperationControl
from app.core.utils import (
    format_size, is_dir_fs, normalize_path, short_path,
)
from app.core.constants import MODULE_COPY, MODULE_MOVE

STATUS_COLOR_LIGHT = {
    "pending": "#8a919c",
    "done": "#28a745",
    "skipped": "#e67e22",
    "failed": "#dc3545",
}

STATUS_COLOR_DARK = {
    "pending": "#9aa4b2",
    "done": "#3fb950",
    "skipped": "#e6973f",
    "failed": "#e85a6a",
}


class CopierPage(ModulePage):
    title = "批量複製 / 搬移"
    module_id = MODULE_COPY
    # The single page serves both operations through the operation switch.
    operation = "copy"
    history_module = MODULE_COPY
    verb = "複製"

    def __init__(self, settings, main_window=None):
        super().__init__(settings, main_window)
        self.tasks = []
        self.row_by_id = {}
        self.task_by_id = {}
        self._counts = {"done": 0, "skipped": 0, "failed": 0}
        self._prev_status = {}
        self.control = None
        self.worker = None
        self.scan_worker = None
        self.running = False
        self.scanning = False
        self._active_source = ""
        self._active_target = ""
        self._task = None
        self._build_ui()
        self._load_options()

    # ------------------------------------------------------------------
    def _build_ui(self):
        outer = QVBoxLayout(self)
        self.page_header = PageHeader(
            self.title,
            "複製或搬移檔案並驗證結果，支援衝突策略與背景執行",
            icon="copy",
            theme=self.theme(),
        )
        outer.addWidget(self.page_header)
        root = QHBoxLayout()
        outer.addLayout(root, 1)
        root.setSpacing(12)

        # ---- left config panel ----
        left = QWidget()
        left.setFixedWidth(380)
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)

        op_box = QGroupBox("操作")
        op_layout = QHBoxLayout(op_box)
        self.op_group = QButtonGroup(self)
        self.rb_copy = QRadioButton("複製")
        self.rb_move = QRadioButton("搬移")
        for index, radio in enumerate((self.rb_copy, self.rb_move)):
            self.op_group.addButton(radio, index)
            op_layout.addWidget(radio)
        op_layout.addStretch(1)
        self.rb_copy.setChecked(True)
        set_icon(self.rb_copy, "copy", self.theme(), "text", 14)
        set_icon(self.rb_move, "move", self.theme(), "text", 14)
        self.op_group.idClicked.connect(self._on_operation_changed)
        lv.addWidget(op_box)

        src_box = QGroupBox("來源 / 目標")
        s_layout = QVBoxLayout(src_box)
        s_layout.addWidget(QLabel("來源資料夾"))
        self.src = PathField(settings=self.settings, field_name="copy_source",
                             placeholder="來源資料夾")
        s_layout.addWidget(self.src)
        s_layout.addWidget(QLabel("目標資料夾"))
        self.dst = PathField(settings=self.settings, field_name="copy_target",
                             placeholder="目標資料夾")
        s_layout.addWidget(self.dst)
        lv.addWidget(src_box)

        mode_box = QGroupBox("選擇模式")
        m_layout = QVBoxLayout(mode_box)
        self.mode_group = QButtonGroup(self)
        self.rb_csv = QRadioButton("CSV 檔案模式")
        self.rb_ext = QRadioButton("副檔名模式")
        self.rb_custom = QRadioButton("自定義模式")
        for i, rb in enumerate((self.rb_csv, self.rb_ext, self.rb_custom)):
            self.mode_group.addButton(rb, i)
            m_layout.addWidget(rb)
        self.rb_csv.setChecked(True)

        self.mode_stack = QStackedWidget()
        # CSV
        csv_w = QWidget()
        cv = QVBoxLayout(csv_w)
        cv.setContentsMargins(0, 0, 0, 0)
        cv.addWidget(QLabel("CSV 檔案 (第一欄為檔名或萬用字元)"))
        self.csv_path = PathField(mode="file", field_name="copy_csv",
                                  settings=self.settings, placeholder="選擇 CSV")
        cv.addWidget(self.csv_path)
        # EXT
        ext_w = QWidget()
        ev = QVBoxLayout(ext_w)
        ev.setContentsMargins(0, 0, 0, 0)
        self.chips = ExtensionChips()
        ev.addWidget(self.chips)
        self.chips_hint = HintLabel("")
        self.chips_hint.setWordWrap(True)
        ev.addWidget(self.chips_hint)
        self.chips.changed.connect(self._update_chips_hint)
        # CUSTOM
        custom_w = QWidget()
        cuv = QVBoxLayout(custom_w)
        cuv.setContentsMargins(0, 0, 0, 0)
        cuv.addWidget(QLabel("每行一個檔名/萬用字元 (例如 Empf_*.xlsx)"))
        self.custom_edit = QPlainTextEdit()
        cuv.addWidget(self.custom_edit)

        self.mode_stack.addWidget(csv_w)
        self.mode_stack.addWidget(ext_w)
        self.mode_stack.addWidget(custom_w)
        m_layout.addWidget(self.mode_stack)
        self.mode_group.idClicked.connect(self.mode_stack.setCurrentIndex)
        lv.addWidget(mode_box)

        self.opt_box = QGroupBox("複製選項")
        opt_box = self.opt_box
        o_layout = QVBoxLayout(opt_box)
        hl = QHBoxLayout()
        hl.addWidget(QLabel("執行緒:"))
        self.threads = QSpinBox()
        self.threads.setRange(1, 16)
        self.threads.setValue(4)
        hl.addWidget(self.threads)
        hl.addStretch(1)
        o_layout.addLayout(hl)

        hl2 = QHBoxLayout()
        hl2.addWidget(QLabel("最小(MB):"))
        self.min_mb = QDoubleSpinBox()
        self.min_mb.setRange(0, 100000)
        self.min_mb.setValue(0)
        hl2.addWidget(self.min_mb)
        hl2.addWidget(QLabel("最大(MB):"))
        self.max_mb = QDoubleSpinBox()
        self.max_mb.setRange(0, 100000)
        self.max_mb.setValue(0)
        hl2.addWidget(self.max_mb)
        o_layout.addLayout(hl2)

        conflict_box = QGroupBox("名稱衝突處理")
        cf = QVBoxLayout(conflict_box)
        self.cf_group = QButtonGroup(self)
        self.cf_skip = QRadioButton("跳過")
        self.cf_over = QRadioButton("覆寫")
        self.cf_rename = QRadioButton("自動重新命名")
        for i, rb in enumerate((self.cf_skip, self.cf_over, self.cf_rename)):
            self.cf_group.addButton(rb, i)
            cf.addWidget(rb)
        self.cf_skip.setChecked(True)
        o_layout.addWidget(conflict_box)

        self.preserve = QCheckBox("保留資料夾結構")
        self.preserve.setChecked(True)
        o_layout.addWidget(self.preserve)
        verify_row = QHBoxLayout()
        self.verify_label = QLabel("複製後驗證")
        verify_row.addWidget(self.verify_label)
        self.verify_mode = QComboBox()
        self.verify_mode.addItem("快速驗證", "quick")
        self.verify_mode.addItem("完整驗證", "full")
        self.verify_mode.addItem("不驗證（最快）", "off")
        verify_row.addWidget(self.verify_mode, 1)
        o_layout.addLayout(verify_row)
        retry_row = QHBoxLayout()
        retry_row.addWidget(QLabel("網路錯誤重試"))
        self.retries = QSpinBox()
        self.retries.setRange(0, 5)
        self.retries.setSuffix(tr(" 次"))
        retry_row.addWidget(self.retries)
        retry_row.addStretch(1)
        o_layout.addLayout(retry_row)
        self.trash_overwrite = QCheckBox("覆寫前先送入資源回收筒 (可復原)")
        o_layout.addWidget(self.trash_overwrite)
        lv.addWidget(opt_box)
        lv.addStretch(1)

        # ---- right panel ----
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)

        btn_row = QHBoxLayout()
        self.start_btn = QPushButton(f"開始{self.verb}")
        self.start_btn.setProperty("variant", "primary")
        set_icon(self.start_btn, "play", self.theme(), "primary_text", 15)
        self.start_btn.clicked.connect(self._on_start)
        self.pause_btn = QPushButton("暫停")
        self.pause_btn.setEnabled(False)
        set_icon(self.pause_btn, "pause", self.theme(), "text", 14)
        self.pause_btn.clicked.connect(self._on_pause)
        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.setProperty("variant", "danger")
        self.cancel_btn.setEnabled(False)
        set_icon(self.cancel_btn, "stop", self.theme(), "danger_text", 14)
        self.cancel_btn.clicked.connect(self._on_cancel)
        btn_row.addWidget(self.start_btn)
        btn_row.addWidget(self.pause_btn)
        btn_row.addWidget(self.cancel_btn)
        btn_row.addStretch(1)
        rv.addLayout(btn_row)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        rv.addWidget(self.progress)

        stat_row = QHBoxLayout()
        self.stat_label = QLabel("待處理: 0")
        stat_row.addWidget(self.stat_label)
        stat_row.addStretch(1)
        self.speed_label = QLabel("")
        stat_row.addWidget(self.speed_label)
        rv.addLayout(stat_row)

        tabs = QTabWidget()
        # results
        res_w = QWidget()
        r_layout = QVBoxLayout(res_w)
        r_layout.setContentsMargins(0, 0, 0, 0)
        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("篩選:"))
        self.filter_combo = QComboBox()
        for label, key in [
            ("全部", None), ("已複製", "done"), ("已跳過", "skipped"),
            ("失敗", "failed"), ("待處理", "pending"),
        ]:
            self.filter_combo.addItem(label, key)
        self.filter_combo.currentIndexChanged.connect(
            lambda _index: self._apply_filter(self.filter_combo.currentData())
        )
        filter_row.addWidget(self.filter_combo)
        filter_row.addStretch(1)
        self.retry_btn = QPushButton("重試失敗項目")
        set_icon(self.retry_btn, "refresh", self.theme(), "text", 14)
        self.retry_btn.clicked.connect(self._on_retry)
        filter_row.addWidget(self.retry_btn)
        self.export_btn = QPushButton("匯出報告 (CSV)")
        set_icon(self.export_btn, "download", self.theme(), "text", 14)
        self.export_btn.clicked.connect(self._on_export)
        filter_row.addWidget(self.export_btn)
        r_layout.addLayout(filter_row)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["來源", "目標", "大小", "狀態", "錯誤訊息"])
        self.table.setColumnWidth(0, 280)
        self.table.setColumnWidth(1, 280)
        self.table.setColumnWidth(2, 90)
        self.table.setColumnWidth(3, 80)
        self.table.setColumnWidth(4, 220)
        self.table.setAlternatingRowColors(True)
        r_layout.addWidget(self.table)

        # log
        log_w = QWidget()
        l_layout = QVBoxLayout(log_w)
        l_layout.setContentsMargins(0, 0, 0, 0)
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        l_layout.addWidget(self.log)

        tabs.addTab(res_w, "結果")
        tabs.addTab(log_w, "日誌")
        rv.addWidget(tabs, 1)

        root.addWidget(left)
        root.addWidget(right, 1)
        self._update_operation_ui(clear=False)

    # ------------------------------------------------------------------
    def _on_operation_changed(self, index):
        operation = "move" if index == 1 else "copy"
        self._set_operation(operation, clear=True)
        self.settings.set_option("copy_operation", operation)

    def _set_operation(self, operation, clear=False):
        """Select copy or move and refresh every operation-specific label."""
        operation = "move" if operation == "move" else "copy"
        radio = self.rb_move if operation == "move" else self.rb_copy
        blocker = self.op_group.blockSignals(True)
        try:
            radio.setChecked(True)
        finally:
            self.op_group.blockSignals(blocker)
        self.operation = operation
        self._update_operation_ui(clear=clear)

    def _update_operation_ui(self, clear=False):
        is_copy = self.operation == "copy"
        self.verb = "複製" if is_copy else "搬移"
        self.history_module = MODULE_COPY if is_copy else MODULE_MOVE
        self.opt_box.setTitle(tr("複製選項" if is_copy else "搬移選項"))
        self.verify_label.setText(
            tr("複製後驗證" if is_copy else "搬移後驗證")
        )
        self.start_btn.setText(tr(f"開始{self.verb}"))
        done_index = self.filter_combo.findData("done")
        if done_index >= 0:
            self.filter_combo.setItemText(done_index, tr(f"已{self.verb}"))
        if clear and not self.running and not self.scanning:
            self.tasks = []
            self._clear_rows()
            self.filter_combo.setCurrentIndex(0)
            self.progress.setValue(0)
            self.speed_label.clear()
            self._refresh_counts()

    def _load_options(self):
        self.threads.setValue(self.settings.option("copy_threads", 4))
        self.min_mb.setValue(self.settings.option("copy_min_mb", 0.0))
        self.max_mb.setValue(self.settings.option("copy_max_mb", 0.0))
        self.preserve.setChecked(self.settings.option("copy_preserve", True))
        mode = self.settings.option(
            "copy_verify_mode",
            "quick" if self.settings.option("copy_verify", True) else "off",
        )
        index = self.verify_mode.findData(mode)
        self.verify_mode.setCurrentIndex(max(0, index))
        self.retries.setValue(self.settings.option("copy_retries", 1))
        self.trash_overwrite.setChecked(self.settings.option("copy_trash_overwrite", False))
        cf = self.settings.option("copy_conflict", "skip")
        {"skip": self.cf_skip, "overwrite": self.cf_over,
         "rename": self.cf_rename}.get(cf, self.cf_skip).setChecked(True)
        exts = self.settings.option("copy_extensions", [])
        if isinstance(exts, str):
            exts = [e for e in exts.split(",") if e]
        self.chips.set_selected(exts)
        self.custom_edit.setPlainText(self.settings.option("copy_custom", ""))
        operation = self.settings.option("copy_operation", "copy")
        self._set_operation(operation, clear=False)
        self._update_chips_hint(self.chips.selected())

    def _update_chips_hint(self, exts):
        if exts:
            self.chips_hint.setText(tr("已選副檔名: " + ", ".join(exts)))
        else:
            self.chips_hint.setText(tr("尚未選擇任何副檔名, 請點選下方按鍵"))

    def _save_options(self):
        cf = {0: "skip", 1: "overwrite", 2: "rename"}[self.cf_group.checkedId()]
        self.settings.set_options({
            "copy_threads": self.threads.value(),
            "copy_min_mb": self.min_mb.value(),
            "copy_max_mb": self.max_mb.value(),
            "copy_preserve": self.preserve.isChecked(),
            "copy_verify_mode": self.verify_mode.currentData(),
            "copy_verify": self.verify_mode.currentData() != "off",
            "copy_retries": self.retries.value(),
            "copy_trash_overwrite": self.trash_overwrite.isChecked(),
            "copy_conflict": cf,
            "copy_extensions": ",".join(self.chips.selected()),
            "copy_custom": self.custom_edit.toPlainText(),
            "copy_operation": self.operation,
        })

    # ------------------------------------------------------------------
    def _current_mode(self):
        return {0: "csv", 1: "ext", 2: "custom"}[self.mode_group.checkedId()]

    def _collect_options(self):
        mode = self._current_mode()
        options = {
            "min_mb": self.min_mb.value(),
            "max_mb": self.max_mb.value(),
            "preserve_structure": self.preserve.isChecked(),
            "conflict_mode": {0: "skip", 1: "overwrite", 2: "rename"}[self.cf_group.checkedId()],
            "verify_mode": self.verify_mode.currentData(),
            "verify": self.verify_mode.currentData() != "off",
            "retries": self.retries.value(),
            "preserve_metadata": True,
            "to_trash_on_overwrite": self.trash_overwrite.isChecked(),
            "threads": self.threads.value(),
        }
        if mode == "csv":
            options["csv_path"] = self.csv_path.text()
            if not options["csv_path"] or not os.path.isfile(options["csv_path"]):
                raise ValueError("請選擇有效的 CSV 檔案")
        elif mode == "ext":
            options["extensions"] = self.chips.selected()
            if not options["extensions"]:
                raise ValueError("請至少選擇一個副檔名")
        else:
            options["patterns_text"] = self.custom_edit.toPlainText()
            if not options["patterns_text"].strip():
                raise ValueError("請輸入自定義模式")
        return mode, options

    def _on_start(self):
        try:
            self._save_options()
            self.settings.remember_path("copy_source", self.src.text())
            self.settings.remember_path("copy_target", self.dst.text())
            mode, options = self._collect_options()
        except ValueError as exc:
            QMessageBox.warning(self, "設定錯誤", str(exc))
            return

        # Scanning a large tree can take a while, so run it off the UI thread.
        operation = self.operation
        self._active_source = self.src.text()
        self._active_target = self.dst.text()
        self.control = OperationControl()
        self.scan_worker = ScanWorker(self.control, self.src.text(),
                                      self.dst.text(), mode, options)
        self.scan_worker.tasks_ready.connect(
            lambda tasks, opts=options, op=operation:
            self._on_scan_ready(tasks, opts, op))
        self.scan_worker.scan_failed.connect(self._on_scan_failed)
        self.scan_worker.start()
        self._task = self.task_add(
            "scan", f"掃描來源：{os.path.basename(self.src.text()) or self.src.text()}",
            control=self.control, message="建立檔案清單...",
            pausable=False,
        )
        self._set_scanning_ui(True)
        self.status("掃描檔案中...")

    def _set_scanning_ui(self, scanning):
        self.scanning = bool(scanning)
        busy = self.scanning or self.running
        self.start_btn.setEnabled(not busy)
        self.pause_btn.setEnabled(False)
        self.cancel_btn.setEnabled(self.scanning)
        for radio in (self.rb_copy, self.rb_move):
            radio.setEnabled(not busy)
        self.src.setEnabled(not busy)
        self.dst.setEnabled(not busy)

    def _on_scan_failed(self, message):
        self._set_scanning_ui(False)
        if self.control and self.control.is_cancelled():
            self.task_finish(self._task, status="cancelled")
            self._task = None
            self.status("已取消")
            return
        self.task_finish(self._task, status="failed", error=message)
        self._task = None
        QMessageBox.warning(self, "掃描失敗", message)
        self.status("掃描失敗")

    def _on_scan_ready(self, tasks, options, operation=None):
        self._set_scanning_ui(False)
        if self.control and self.control.is_cancelled():
            self.task_finish(self._task, status="cancelled")
            self._task = None
            self.status("已取消")
            return
        if not tasks:
            self.task_finish(self._task, message="沒有符合條件的檔案")
            self._task = None
            QMessageBox.information(self, "無相符檔案", "沒有符合條件的檔案。")
            return
        self.task_finish(self._task, message=f"{len(tasks):,} 個檔案")
        self._task = None

        self.tasks = tasks
        self._clear_rows()
        for t in tasks:
            self._add_row(t)
        self._refresh_counts()
        self._begin_transfer(tasks, options, operation or self.operation)

    def _begin_transfer(self, tasks, options, operation=None):
        operation = operation or self.operation
        self._set_operation(operation, clear=False)
        self.control = OperationControl()
        self.worker = TransferWorker(self.control, tasks, options,
                                     operation=operation)
        self.worker.log_line.connect(self._on_log)
        self.worker.task_updated.connect(self._on_task_updated)
        self.worker.progress_changed.connect(self._on_progress)
        self.worker.stats_changed.connect(self._on_stats)
        self.worker.run_finished.connect(
            lambda cancelled, summary, op=operation:
            self._on_finished(cancelled, summary, op)
        )
        self.worker.start()
        self._task = self.task_add(
            operation, f"{self.verb} {len(tasks)} 個檔案",
            control=self.control, total=len(tasks),
            message=self._active_target,
        )

        self.running = True
        self._set_running_ui(True)
        self.status(f"開始{self.verb} {len(tasks)} 個檔案")

    def _status_color(self, status):
        palette = STATUS_COLOR_DARK if self.theme() == "dark" else STATUS_COLOR_LIGHT
        return palette.get(status, "#8a919c")

    def _add_row(self, task):
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(short_path(task.src, 60)))
        self.table.setItem(row, 1, QTableWidgetItem(short_path(task.dst, 60)))
        self.table.setItem(row, 2, QTableWidgetItem(format_size(task.size)))
        status = QTableWidgetItem(tr("待處理"))
        from PyQt6.QtGui import QBrush, QColor

        status.setForeground(QBrush(QColor(self._status_color("pending"))))
        self.table.setItem(row, 3, status)
        self.table.setItem(row, 4, QTableWidgetItem(""))
        self.table.item(row, 0).setToolTip(task.src)
        self.table.item(row, 1).setToolTip(task.dst)
        self.row_by_id[task.id] = row
        self.task_by_id[task.id] = task
        self._prev_status[task.id] = "pending"

    def _on_task_updated(self, task):
        row = self.row_by_id.get(task.id)
        if row is None:
            return
        status_item = self.table.item(row, 3)
        status_item.setText(tr({
            "done": f"已{self.verb}", "skipped": "已跳過",
            "failed": "失敗", "pending": "待處理",
        }[task.status]))
        color = self._status_color(task.status)
        from PyQt6.QtGui import QBrush, QColor
        status_item.setForeground(QBrush(QColor(color)))
        self.table.item(row, 4).setText(tr_exact(task.error))
        # Conflict handling can change the destination (auto-rename).
        target_item = self.table.item(row, 1)
        target_item.setText(short_path(task.dst, 60))
        target_item.setToolTip(task.dst)
        prev = self._prev_status.get(task.id)
        if prev in self._counts:
            self._counts[prev] -= 1
        if task.status in self._counts:
            self._counts[task.status] += 1
        self._prev_status[task.id] = task.status
        self._refresh_counts()

    def _refresh_counts(self):
        done = self._counts["done"]
        skipped = self._counts["skipped"]
        failed = self._counts["failed"]
        pending = len(self.tasks) - done - skipped - failed
        self.stat_label.setText(tr(
            f"已完成: {done} | 跳過: {skipped} | 失敗: {failed} | 待處理: {pending}"
        ))

    def _on_progress(self, done, total):
        self.progress.setValue(int(done / total * 100) if total else 0)
        self.task_update(self._task, done=done, total=total)

    def _on_stats(self, speed, eta, bytes_done):
        remaining = tr("剩餘 {seconds} 秒", seconds=int(eta))
        self.speed_label.setText(
            f"{format_size(speed)}/s | {remaining} | "
            f"{format_size(bytes_done)}"
        )

    def _on_log(self, line):
        self.log.append(line)

    def _on_pause(self):
        if not self.control:
            return
        if self.control.is_paused():
            self.control.resume()
            self.pause_btn.setText("暫停")
            self.task_update(self._task, status="running", message="繼續執行")
            self.status("繼續")
        else:
            self.control.pause()
            self.pause_btn.setText("繼續")
            self.task_update(self._task, status="paused", message="已暫停")
            self.status("已暫停")

    def _on_cancel(self):
        if self.control:
            self.control.cancel()
            self.cancel_btn.setEnabled(False)
            self.task_update(self._task, message="取消中...")
            self.status("取消中...")

    def _on_retry(self):
        if self.running:
            return
        failed = [t for t in self.tasks if t.status == "failed"]
        if not failed:
            QMessageBox.information(self, "重試", "沒有失敗的項目。")
            return
        from PyQt6.QtGui import QBrush, QColor

        for t in failed:
            t.reset()
            # Reset the row display and counters immediately.
            row = self.row_by_id.get(t.id)
            if row is not None:
                item = self.table.item(row, 3)
                item.setText("待處理")
                item.setForeground(QBrush(QColor(self._status_color("pending"))))
                self.table.item(row, 4).setText("")
            prev = self._prev_status.get(t.id)
            if prev in self._counts:
                self._counts[prev] -= 1
            self._prev_status[t.id] = "pending"
        self._refresh_counts()
        operation = self.operation
        self._active_source = self.src.text()
        self._active_target = self.dst.text()
        self.control = OperationControl()
        options = self._current_options_dict()
        self.worker = TransferWorker(
            self.control, failed, options, operation=operation
        )
        self.worker.log_line.connect(self._on_log)
        self.worker.task_updated.connect(self._on_task_updated)
        self.worker.progress_changed.connect(self._on_progress)
        self.worker.stats_changed.connect(self._on_stats)
        self.worker.run_finished.connect(
            lambda cancelled, summary, op=operation:
            self._on_finished(cancelled, summary, op)
        )
        self.worker.start()
        self._task = self.task_add(
            operation, f"重試{self.verb} {len(failed)} 個檔案",
            control=self.control, total=len(failed),
        )
        self.running = True
        self._set_running_ui(True)

    def _current_options_dict(self):
        return {
            "min_mb": self.min_mb.value(),
            "max_mb": self.max_mb.value(),
            "preserve_structure": self.preserve.isChecked(),
            "conflict_mode": {0: "skip", 1: "overwrite", 2: "rename"}[self.cf_group.checkedId()],
            "verify_mode": self.verify_mode.currentData(),
            "verify": self.verify_mode.currentData() != "off",
            "retries": self.retries.value(),
            "preserve_metadata": True,
            "to_trash_on_overwrite": self.trash_overwrite.isChecked(),
            "threads": self.threads.value(),
        }

    def _on_finished(self, cancelled, summary, operation=None):
        self.running = False
        self._set_running_ui(False)
        operation = operation or self.operation
        verb = "搬移" if operation == "move" else "複製"
        done = summary.get("done", 0) if isinstance(summary, dict) else 0
        skipped = summary.get("skipped", 0) if isinstance(summary, dict) else 0
        failed = summary.get("failed", 0) if isinstance(summary, dict) else 0
        bts = summary.get("bytes", 0) if isinstance(summary, dict) else 0
        elapsed = summary.get("elapsed", 0) if isinstance(summary, dict) else 0
        action = tr("已複製" if operation == "copy" else "已搬移")
        msg = (
            f"{tr('完成')}: {tr('成功')} {done} / {tr('已跳過')} {skipped}"
            f" / {tr('失敗')} {failed} | {action} {format_size(bts)}"
            f" | {tr('耗時')} {elapsed:.1f}s"
        )
        self.status(msg, 8000)
        if cancelled:
            self.task_finish(self._task, status="cancelled", message=msg)
        else:
            self.task_finish(self._task, message=msg)
        self._task = None
        self._on_log(f"[{'已取消' if cancelled else '完成'}] {msg}")
        # unified history
        self._record_history(done, failed, bts, operation, verb)

    def _record_history(self, done, failed, bts, operation=None, verb=None):
        try:
            from app.core.history import record_operation
            operation = operation or self.operation
            verb = verb or ("搬移" if operation == "move" else "複製")
            module = MODULE_MOVE if operation == "move" else MODULE_COPY
            source = self._active_source or self.src.text()
            target = self._active_target or self.dst.text()
            record_operation(self.settings, module, source,
                             f"{verb} {done} 個檔案至 {target}",
                             done, failed, bts)
        except Exception:
            pass

    def _on_export(self):
        if not self.tasks:
            QMessageBox.information(self, "匯出", "尚無結果可匯出。")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, tr("匯出報告"), f"{self.operation}_report.csv",
            file_filter("csv")
        )
        if not path:
            return
        path = normalize_path(path)
        try:
            with open(path, "w", encoding="utf-8-sig", newline="") as f:
                w = csv.writer(f)
                w.writerow([
                    tr("來源"), tr("目標"), tr("大小"), tr("狀態"),
                    tr("錯誤訊息"),
                ])
                completed = tr("已複製" if self.operation == "copy"
                               else "已搬移")
                status_labels = {
                    "done": completed,
                    "skipped": tr("已跳過"),
                    "failed": tr("失敗"),
                    "pending": tr("待處理"),
                }
                for t in self.tasks:
                    w.writerow([
                        t.src, t.dst, t.size,
                        status_labels.get(t.status, t.status),
                        tr_exact(t.error),
                    ])
            QMessageBox.information(self, "匯出成功", f"已匯出至 {path}")
        except Exception as exc:
            QMessageBox.warning(self, "匯出失敗", str(exc))

    def _apply_filter(self, want):
        for tid, row in self.row_by_id.items():
            task = self.task_by_id.get(tid)
            if task is None:
                continue
            show = want is None or task.status == want
            self.table.setRowHidden(row, not show)

    def _clear_rows(self):
        self.table.setRowCount(0)
        self.row_by_id = {}
        self.task_by_id = {}
        self._counts = {"done": 0, "skipped": 0, "failed": 0}
        self._prev_status = {}

    def _set_running_ui(self, running):
        self.start_btn.setEnabled(not running)
        self.pause_btn.setEnabled(running)
        self.cancel_btn.setEnabled(running)
        for radio in (self.rb_copy, self.rb_move):
            radio.setEnabled(not running and not self.scanning)
        self.src.setEnabled(not running and not self.scanning)
        self.dst.setEnabled(not running and not self.scanning)
        if not running:
            self.pause_btn.setText(tr("暫停"))

    def apply_payload(self, payload):
        if not isinstance(payload, dict):
            return
        if self.running or self.scanning:
            self.status(tr("目前有工作進行中，完成後再切換模式"))
            return
        operation = payload.get("operation")
        if operation in ("copy", "move"):
            self._set_operation(operation, clear=True)
            self.settings.set_option("copy_operation", operation)
        source = payload.get("folder") or payload.get("source")
        if source and is_dir_fs(source):
            self.src.set_path(source)
        target = payload.get("target")
        if target and is_dir_fs(target):
            self.dst.set_path(target)

    def on_settings_changed(self):
        self._load_options()

    def on_theme_changed(self):
        self.page_header.set_theme(self.theme())

    def request_stop(self):
        if self.control:
            self.control.cancel()
        for worker in (self.scan_worker, self.worker):
            if worker and worker.isRunning():
                worker.wait(3000)

