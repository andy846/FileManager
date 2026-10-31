"""Remover module page (migrated from File_Remover v2, EN -> ZH)."""

import csv

from PyQt6.QtCore import Qt, QDate, QDateTime
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QPushButton, QCheckBox,
    QProgressBar, QLabel, QTableWidget, QTableWidgetItem, QComboBox,
    QDoubleSpinBox, QDateEdit, QLineEdit, QMessageBox, QFileDialog,
    QDialog, QTextEdit,
)

from app.ui.base import ModulePage
from app.ui.components import PageHeader
from app.ui.icons import set_icon
from app.ui.widgets import PathField, ExtensionChips, DropArea
from app.modules.remover.worker import ScannerWorker, DeletionWorker
from app.modules.remover.logmanager import LogManager
from app.core.utils import (
    format_size, is_dir_fs, normalize_path, short_path,
)
from app.core.constants import MODULE_REMOVE
from app.core.history import record_operation
from app.core.i18n import file_filter, tr


class RemoverPage(ModulePage):
    title = "批量刪除"
    module_id = MODULE_REMOVE

    def __init__(self, settings, main_window=None):
        super().__init__(settings, main_window)
        self.files = []
        self.scan_worker = None
        self.del_worker = None
        self.scanning = False
        self.deleting = False
        self._scan_buffer = []
        self._sel_rows = set()
        self._total_size = 0
        self._pending_size = 0
        self._op_started = ""
        self._log = LogManager(settings)
        self._task = None
        self._build_ui()
        self._load_options()

    # ------------------------------------------------------------------
    def _build_ui(self):
        outer = QVBoxLayout(self)
        self.page_header = PageHeader(
            "批量刪除",
            "依條件掃描檔案並安全地送入資源回收筒",
            icon="trash",
            theme=self.theme(),
        )
        outer.addWidget(self.page_header)
        root = QHBoxLayout()
        outer.addLayout(root, 1)
        root.setSpacing(12)

        left = QWidget()
        left.setFixedWidth(320)
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)

        fbox = QGroupBox("目標資料夾")
        fl = QVBoxLayout(fbox)
        self.folder = PathField(settings=self.settings, field_name="remove_folder",
                                placeholder="選擇要清理的資料夾")
        fl.addWidget(self.folder)
        self.drop = DropArea(text="拖放資料夾到此處")
        self.drop.folder_dropped.connect(self.folder.set_path)
        fl.addWidget(self.drop)
        lv.addWidget(fbox)

        lv.addWidget(QLabel("副檔名"))
        self.chips = ExtensionChips(defaults=["pdf", "ps", "afp", "pgp", "txt", "xlsx"])
        lv.addWidget(self.chips)

        filt = QGroupBox("篩選條件")
        flx = QVBoxLayout(filt)
        self.use_date = QCheckBox("依修改日期篩選")
        flx.addWidget(self.use_date)
        dl = QHBoxLayout()
        self.date_from = QDateEdit(QDate.currentDate().addMonths(-1))
        self.date_from.setCalendarPopup(True)
        self.date_to = QDateEdit(QDate.currentDate())
        self.date_to.setCalendarPopup(True)
        dl.addWidget(QLabel("從"))
        dl.addWidget(self.date_from)
        dl.addWidget(QLabel("至"))
        dl.addWidget(self.date_to)
        flx.addLayout(dl)

        sl = QHBoxLayout()
        self.size_op = QComboBox()
        for label, key in [
            ("不限制", None), (">=", ">="), ("<=", "<="), ("介於", "between"),
        ]:
            self.size_op.addItem(label, key)
        self.size_op.currentIndexChanged.connect(
            lambda _index: self._on_size_op(self.size_op.currentData())
        )
        sl.addWidget(QLabel("大小"))
        sl.addWidget(self.size_op)
        self.size_value = QDoubleSpinBox()
        self.size_value.setRange(0, 10 ** 9)
        self.size_value.setValue(0)
        sl.addWidget(self.size_value)
        self.size_unit = QComboBox()
        self.size_unit.addItems(["KB", "MB", "GB"])
        self.size_unit.setCurrentText("MB")
        sl.addWidget(self.size_unit)
        flx.addLayout(sl)
        self.size_value_max = QDoubleSpinBox()
        self.size_value_max.setRange(0, 10 ** 9)
        self.size_value_max.setValue(0)
        self.size_value_max.setVisible(False)
        flx.addWidget(self.size_value_max)

        flx.addWidget(QLabel("排除模式 (逗號分隔, 支援 *.tmp, temp/)"))
        self.exclude = QLineEdit()
        flx.addWidget(self.exclude)

        self.recursive = QCheckBox("包含子資料夾")
        self.recursive.setChecked(True)
        flx.addWidget(self.recursive)
        lv.addWidget(filt)

        self.permanent = QCheckBox("永久刪除 (不經資源回收筒, 不可復原)")
        lv.addWidget(self.permanent)

        bl = QHBoxLayout()
        self.scan_btn = QPushButton("掃描")
        self.scan_btn.setProperty("variant", "primary")
        set_icon(self.scan_btn, "search", self.theme(), "primary_text", 15)
        self.scan_btn.clicked.connect(self._on_scan)
        self.cancel_scan_btn = QPushButton("停止掃描")
        self.cancel_scan_btn.setEnabled(False)
        set_icon(self.cancel_scan_btn, "stop", self.theme(), "text", 14)
        self.cancel_scan_btn.clicked.connect(self._on_cancel_scan)
        bl.addWidget(self.scan_btn)
        bl.addWidget(self.cancel_scan_btn)
        lv.addLayout(bl)
        lv.addStretch(1)

        # right
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)

        tl = QHBoxLayout()
        self.count_label = QLabel("0 個檔案")
        tl.addWidget(self.count_label)
        self.size_label = QLabel("0 B")
        tl.addWidget(self.size_label)
        tl.addStretch(1)
        self.sel_label = QLabel("已選 0")
        tl.addWidget(self.sel_label)
        rv.addLayout(tl)

        bl2 = QHBoxLayout()
        self.select_all_btn = QPushButton("全選")
        self.select_all_btn.clicked.connect(lambda: self._select_all(True))
        self.deselect_btn = QPushButton("取消全選")
        self.deselect_btn.clicked.connect(lambda: self._select_all(False))
        self.delete_btn = QPushButton("刪除 0 個檔案")
        self.delete_btn.setProperty("variant", "danger")
        set_icon(self.delete_btn, "trash", self.theme(), "danger_text", 15)
        self.delete_btn.clicked.connect(self._on_delete)
        self.cancel_del_btn = QPushButton("取消")
        self.cancel_del_btn.setEnabled(False)
        set_icon(self.cancel_del_btn, "stop", self.theme(), "text", 14)
        self.cancel_del_btn.clicked.connect(self._on_cancel_delete)
        bl2.addWidget(self.select_all_btn)
        bl2.addWidget(self.deselect_btn)
        bl2.addStretch(1)
        bl2.addWidget(self.delete_btn)
        bl2.addWidget(self.cancel_del_btn)
        rv.addLayout(bl2)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setVisible(False)
        rv.addWidget(self.progress)

        el = QHBoxLayout()
        self.export_csv_btn = QPushButton("匯出 CSV")
        set_icon(self.export_csv_btn, "download", self.theme(), "text", 14)
        self.export_csv_btn.clicked.connect(lambda: self._export("csv"))
        self.export_xlsx_btn = QPushButton("匯出 Excel")
        set_icon(self.export_xlsx_btn, "download", self.theme(), "text", 14)
        self.export_xlsx_btn.clicked.connect(lambda: self._export("xlsx"))
        self.history_btn = QPushButton("歷史紀錄")
        set_icon(self.history_btn, "history", self.theme(), "text", 14)
        self.history_btn.clicked.connect(self._show_history)
        el.addWidget(self.export_csv_btn)
        el.addWidget(self.export_xlsx_btn)
        el.addStretch(1)
        el.addWidget(self.history_btn)
        rv.addLayout(el)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["", "檔名", "大小", "修改時間", "路徑"])
        self.table.setColumnWidth(0, 30)
        self.table.setColumnWidth(1, 200)
        self.table.setColumnWidth(2, 90)
        self.table.setColumnWidth(3, 150)
        self.table.setColumnWidth(4, 300)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.itemChanged.connect(self._on_item_changed)
        rv.addWidget(self.table, 1)

        root.addWidget(left)
        root.addWidget(right, 1)

    # ------------------------------------------------------------------
    def _on_size_op(self, op):
        self.size_value_max.setVisible(op == "between")

    def _load_options(self):
        exts = self.settings.option("remove_extensions", ["pdf", "ps", "afp", "pgp"])
        if isinstance(exts, str):
            exts = [e for e in exts.split(",") if e]
        self.chips.set_selected(exts)
        self.recursive.setChecked(self.settings.option("remove_recursive", True))
        self.use_date.setChecked(self.settings.option("remove_use_date", False))
        unit = self.settings.option("remove_size_unit", "MB")
        idx = self.size_unit.findText(unit)
        if idx >= 0:
            self.size_unit.setCurrentIndex(idx)
        self.exclude.setText(self.settings.option("remove_exclude", ""))

    def _save_options(self):
        self.settings.set_options({
            "remove_extensions": ",".join(self.chips.selected()),
            "remove_recursive": self.recursive.isChecked(),
            "remove_use_date": self.use_date.isChecked(),
            "remove_size_unit": self.size_unit.currentText(),
            "remove_exclude": self.exclude.text(),
        })

    # ------------------------------------------------------------------
    def _collect_filters(self):
        op = self.size_op.currentData()
        return {
            "date_from": self.date_from.date() if self.use_date.isChecked() else None,
            "date_to": self.date_to.date() if self.use_date.isChecked() else None,
            "size_op": op,
            "size_value": self.size_value.value(),
            "size_value_max": self.size_value_max.value(),
            "size_unit": self.size_unit.currentText(),
            "exclude_patterns": [p.strip() for p in self.exclude.text().split(",") if p.strip()],
        }

    def _on_scan(self):
        folder = self.folder.text()
        if not folder or not is_dir_fs(folder):
            QMessageBox.warning(self, "資料夾錯誤", "請選擇有效的資料夾。")
            return
        self._save_options()
        self.settings.remember_path("remove_folder", folder)
        self.files = []
        self.table.setRowCount(0)
        self._scan_buffer = []
        self._reset_counts()
        self.scanning = True
        self.progress.setVisible(True)
        self.progress.setRange(0, 0)
        self.scan_btn.setEnabled(False)
        self.cancel_scan_btn.setEnabled(True)
        self.count_label.setText("掃描中...")
        filters = self._collect_filters()
        self.scan_worker = ScannerWorker(folder, self.chips.selected(),
                                         filters, self.recursive.isChecked())
        self.scan_worker.progress.connect(self._on_scan_progress)
        self.scan_worker.file_found.connect(self._on_file_found)
        self.scan_worker.scan_complete.connect(self._on_scan_complete)
        self.scan_worker.error.connect(self._on_scan_error)
        self.scan_worker.start()
        self._task = self.task_add(
            "scan", "掃描刪除候選", cancel=self.scan_worker.cancel,
            message=folder,
        )
        self.status("掃描中...")

    def _on_scan_progress(self, msg):
        self.progress.setFormat(msg)
        self.task_update(self._task, message=msg)

    def _on_scan_error(self, message):
        self.scanning = False
        self.progress.setVisible(False)
        self.scan_btn.setEnabled(True)
        self.cancel_scan_btn.setEnabled(False)
        self.task_finish(self._task, status="failed", error=message)
        self._task = None
        QMessageBox.warning(self, "掃描錯誤", message)
        self.status("掃描失敗")

    def _on_file_found(self, info):
        self._scan_buffer.append(info)
        if len(self._scan_buffer) >= 50:
            self._flush_buffer()

    def _reset_counts(self):
        self._sel_rows.clear()
        self._total_size = 0

    def _on_item_changed(self, item):
        if item.column() != 0:
            return
        row = item.row()
        if item.checkState() == Qt.CheckState.Checked:
            self._sel_rows.add(row)
        else:
            self._sel_rows.discard(row)
        self._update_sel_label()

    def _flush_buffer(self):
        for info in self._scan_buffer:
            self._add_row(info)
        self._scan_buffer.clear()
        self._update_counts()

    def _add_row(self, info):
        row = self.table.rowCount()
        self.table.insertRow(row)
        chk = QTableWidgetItem()
        chk.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
        chk.setCheckState(Qt.CheckState.Checked)
        self.table.setItem(row, 0, chk)
        self.table.setItem(row, 1, QTableWidgetItem(info.name))
        self.table.setItem(row, 2, QTableWidgetItem(format_size(info.size)))
        from app.core.utils import format_datetime

        self.table.setItem(row, 3, QTableWidgetItem(format_datetime(info.modified)))
        path_item = QTableWidgetItem(short_path(info.path, 60))
        path_item.setToolTip(info.path)
        self.table.setItem(row, 4, path_item)
        self.files.append(info)
        self._total_size += info.size

    def _on_scan_complete(self, results):
        self._flush_buffer()
        self.scanning = False
        self.progress.setVisible(False)
        self.scan_btn.setEnabled(True)
        self.cancel_scan_btn.setEnabled(False)
        self._update_counts()
        self.task_finish(
            self._task, message=f"找到 {len(self.files)} 個檔案",
        )
        self._task = None
        self.status(f"掃描完成: {len(self.files)} 個檔案")

    def _on_cancel_scan(self):
        if self.scan_worker:
            self.scan_worker.cancel()
            self.task_update(self._task, message="取消中...")

    def _selected_files(self):
        return [self.files[i] for i in self._sel_rows if i < len(self.files)]

    def _update_counts(self):
        self.count_label.setText(f"{len(self.files)} 個檔案")
        self.size_label.setText(format_size(self._total_size))
        self._update_sel_label()

    def _update_sel_label(self):
        n = len(self._sel_rows)
        self.sel_label.setText(f"已選 {n}")
        self.delete_btn.setText(f"刪除 {n} 個檔案")
        self.delete_btn.setEnabled(n > 0 and not self.deleting)

    def _select_all(self, state):
        chk_state = Qt.CheckState.Checked if state else Qt.CheckState.Unchecked
        for i in range(self.table.rowCount()):
            self.table.item(i, 0).setCheckState(chk_state)
        self._update_sel_label()

    # ------------------------------------------------------------------
    def _on_delete(self):
        selected = self._selected_files()
        if not selected:
            return
        permanent = self.permanent.isChecked()
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("確認刪除")
        if permanent:
            box.setText(f"確定要『永久刪除』 {len(selected)} 個檔案嗎？\n"
                        "此操作『無法』復原！")
        else:
            box.setText(f"確定要將 {len(selected)} 個檔案移入資源回收筒嗎？\n"
                        "（可在資源回收筒中復原）")
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if box.exec() != QMessageBox.StandardButton.Yes:
            return
        self._start_delete(selected, permanent)

    def _start_delete(self, selected, permanent):
        self.deleting = True
        self.delete_btn.setEnabled(False)
        self.cancel_del_btn.setEnabled(True)
        self.select_all_btn.setEnabled(False)
        self.progress.setVisible(True)
        self.progress.setRange(0, len(selected))
        self.progress.setValue(0)
        self.status("刪除中...")
        # Capture sizes BEFORE deletion - files no longer exist afterwards.
        self._pending_size = sum(f.size for f in selected)
        self._op_started = QDateTime.currentDateTime().toString("yyyy-MM-dd HH:mm:ss")
        self.del_worker = DeletionWorker(selected, permanent=permanent)
        self.del_worker.progress.connect(lambda d, t: self.progress.setValue(d))
        self.del_worker.delete_complete.connect(
            lambda d, f: self._on_delete_complete(d, f, permanent))
        self.del_worker.start()
        self._task = self.task_add(
            "delete", f"刪除 {len(selected)} 個檔案",
            cancel=self.del_worker.cancel, total=len(selected),
            message="永久刪除" if permanent else "移至資源回收筒",
        )
        self.del_worker.progress.connect(
            lambda done, total: self.task_update(
                self._task, done=done, total=total
            )
        )

    def _on_delete_complete(self, deleted, failed, permanent):
        self.deleting = False
        self.progress.setVisible(False)
        self.delete_btn.setEnabled(True)
        self.cancel_del_btn.setEnabled(False)
        self.select_all_btn.setEnabled(True)
        finished = QDateTime.currentDateTime().toString("yyyy-MM-dd HH:mm:ss")
        size_freed = self._pending_size
        log = self._log.save_logs(
            self.folder.text(), self.chips.selected(), deleted, failed,
            self._op_started, finished, size_freed=size_freed)
        # remove deleted rows from table
        deleted_set = set(deleted)
        keep = [f for f in self.files if f.path not in deleted_set]
        self.files = []
        self.table.setRowCount(0)
        self._reset_counts()
        # Iterate a snapshot: _add_row appends to self.files while we loop.
        for info in list(keep):
            self._add_row(info)
        self._update_counts()
        record_operation(self.settings, MODULE_REMOVE, self.folder.text(),
                         f"刪除 {len(deleted)} 個檔案"
                         + (" (永久)" if permanent else " (資源回收筒)"),
                         len(deleted), len(failed), size_freed,
                         [p for p in log.values() if isinstance(p, str)])
        self._show_summary(len(deleted), len(failed), size_freed, failed)
        self.task_finish(
            self._task,
            status="done" if not failed else "failed",
            message=f"刪除 {len(deleted)} · 失敗 {len(failed)}",
        )
        self._task = None
        self.status(f"完成: 刪除 {len(deleted)} 個, 失敗 {len(failed)} 個")

    def _show_summary(self, deleted, failed, size_freed, failed_list):
        dlg = QDialog(self)
        dlg.setWindowTitle("作業摘要")
        dlg.resize(420, 300)
        lay = QVBoxLayout(dlg)
        lay.addWidget(QLabel(f"成功刪除: {deleted} 個"))
        lay.addWidget(QLabel(f"失敗: {failed} 個"))
        lay.addWidget(QLabel(f"釋放空間: {format_size(size_freed)}"))
        if failed_list:
            lay.addWidget(QLabel("前 5 個失敗:"))
            txt = QTextEdit()
            txt.setReadOnly(True)
            txt.setPlainText("\n".join(f"{p}: {e}" for p, e in failed_list[:5]))
            lay.addWidget(txt)
        btn = QPushButton("關閉")
        btn.clicked.connect(dlg.accept)
        lay.addWidget(btn)
        dlg.exec()

    def _on_cancel_delete(self):
        if self.del_worker:
            self.del_worker.cancel()
            self.task_update(self._task, message="取消中...")

    # ------------------------------------------------------------------
    def _export(self, kind):
        if not self.files:
            QMessageBox.information(self, "匯出", "尚無掃描結果可匯出。")
            return
        if kind == "csv":
            path, _ = QFileDialog.getSaveFileName(
                self, tr("匯出 CSV"), "scan_result.csv", file_filter("csv")
            )
            if not path:
                return
            path = normalize_path(path)
            with open(path, "w", encoding="utf-8-sig", newline="") as f:
                w = csv.writer(f)
                w.writerow([
                    tr("檔名"), tr("大小"), tr("修改時間"), tr("路徑"),
                    tr("是否選取"),
                ])
                sel_paths = {f.path for f in self._selected_files()}
                for f_ in self.files:
                    w.writerow([f_.name, f_.size, f_.modified, f_.path,
                                tr("是") if f_.path in sel_paths else tr("否")])
            QMessageBox.information(self, "匯出成功", f"已匯出至 {path}")
        else:
            path, _ = QFileDialog.getSaveFileName(
                self, tr("匯出 Excel"), "scan_result.xlsx",
                file_filter("excel")
            )
            if not path:
                return
            path = normalize_path(path)
            try:
                from openpyxl import Workbook

                wb = Workbook()
                ws = wb.active
                ws.title = tr("掃描結果")
                ws.append([tr("檔名"), tr("大小"), tr("修改時間"), tr("路徑")])
                for f_ in self.files:
                    ws.append([f_.name, f_.size, f_.modified, f_.path])
                wb.save(path)
                QMessageBox.information(self, "匯出成功", f"已匯出至 {path}")
            except Exception as exc:
                QMessageBox.warning(self, "匯出失敗", str(exc))

    def _show_history(self):
        from app.ui.history_dialog import show_history_dialog

        show_history_dialog(self, self.settings)

    def on_theme_changed(self):
        self.page_header.set_theme(self.theme())

    def apply_payload(self, payload):
        if not isinstance(payload, dict):
            return
        folder = payload.get("folder")
        if folder and is_dir_fs(folder):
            self.folder.set_path(folder)

    def request_stop(self):
        if self.scan_worker and self.scanning:
            self.scan_worker.cancel()
        if self.del_worker and self.deleting:
            self.del_worker.cancel()
        # Bounded wait so threads do not outlive the application.
        if self.scan_worker and self.scan_worker.isRunning():
            self.scan_worker.wait(3000)
        if self.del_worker and self.del_worker.isRunning():
            self.del_worker.wait(3000)
