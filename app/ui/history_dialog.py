"""Shared operation-history dialog used by the shell and module pages."""

import csv

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QFileDialog, QHBoxLayout,
    QHeaderView, QLabel, QMessageBox, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout,
)

from app.core.constants import MODULE_LABELS
from app.core.history import clear_history, load_history, summarize_history
from app.core.i18n import file_filter, tr
from app.core.utils import format_size, normalize_path, short_path


class HistoryDialog(QDialog):
    """Read-only table of past operations with filtering and summary stats."""

    def __init__(self, parent, settings):
        super().__init__(parent)
        self.settings = settings
        self.records = []
        self.setWindowTitle("操作歷史紀錄")
        self.resize(900, 520)

        layout = QVBoxLayout(self)

        summary_row = QHBoxLayout()
        self.summary_label = QLabel("")
        self.summary_label.setProperty("role", "hint")
        summary_row.addWidget(self.summary_label, 1)
        summary_row.addWidget(QLabel("模組:"))
        self.filter_combo = QComboBox()
        self.filter_combo.addItem(tr("全部"), "")
        self.filter_combo.currentIndexChanged.connect(self._reload)
        summary_row.addWidget(self.filter_combo)
        layout.addLayout(summary_row)

        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels([
            tr("時間"), tr("模組"), tr("資料夾"), tr("說明"),
            tr("成功"), tr("失敗"), tr("釋放空間"),
        ])
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        for col in (4, 5, 6):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.table)

        buttons = QHBoxLayout()
        export_btn = QPushButton("匯出 CSV")
        export_btn.clicked.connect(self._export)
        buttons.addWidget(export_btn)
        buttons.addStretch(1)
        clear_btn = QPushButton("清除歷史紀錄")
        clear_btn.clicked.connect(self._clear)
        buttons.addWidget(clear_btn)
        close_btn = QPushButton("關閉")
        close_btn.clicked.connect(self.accept)
        buttons.addWidget(close_btn)
        layout.addLayout(buttons)

        self._load_records()
        self._reload()

    def _load_records(self):
        self.records = load_history(self.settings)
        current = self.filter_combo.currentData()
        self.filter_combo.blockSignals(True)
        self.filter_combo.clear()
        self.filter_combo.addItem(tr("全部"), "")
        seen = []
        for record in self.records:
            module = str(record.get("module", ""))
            if module and module not in seen:
                seen.append(module)
                self.filter_combo.addItem(
                    tr(MODULE_LABELS.get(module, module)), module
                )
        index = self.filter_combo.findData(current)
        self.filter_combo.setCurrentIndex(max(0, index))
        self.filter_combo.blockSignals(False)

    def _reload(self):
        selected = self.filter_combo.currentData() or ""
        records = [
            record for record in self.records
            if not selected or str(record.get("module", "")) == selected
        ]
        summary = summarize_history(records)
        self.summary_label.setText(
            f"{summary['operations']} {tr('筆操作')} · "
            f"{tr('成功')} {summary['processed']:,} · "
            f"{tr('失敗')} {summary['failed']:,} · "
            f"{tr('釋放')} {format_size(summary['freed_bytes'])}"
        )

        self.table.setRowCount(0)
        for record in reversed(records):
            row = self.table.rowCount()
            self.table.insertRow(row)
            timestamp = str(record.get("timestamp", "")).replace("T", " ")
            module = str(record.get("module", ""))
            folder = normalize_path(record.get("folder", ""))
            self.table.setItem(row, 0, QTableWidgetItem(timestamp))
            self.table.setItem(
                row, 1,
                QTableWidgetItem(tr(MODULE_LABELS.get(module, module)))
            )
            folder_item = QTableWidgetItem(short_path(folder, 45))
            folder_item.setToolTip(folder)
            self.table.setItem(row, 2, folder_item)
            self.table.setItem(
                row, 3,
                QTableWidgetItem(tr(str(record.get("detail", ""))))
            )
            self.table.setItem(
                row, 4,
                QTableWidgetItem(str(record.get("files_processed", 0))),
            )
            self.table.setItem(
                row, 5, QTableWidgetItem(str(record.get("files_failed", 0)))
            )
            freed = int(record.get("size_freed_bytes", 0) or 0)
            freed_item = QTableWidgetItem(format_size(freed))
            freed_item.setTextAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            self.table.setItem(row, 6, freed_item)

    def _export(self):
        if not self.records:
            QMessageBox.information(self, "匯出", "尚無歷史紀錄可匯出。")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, tr("匯出歷史紀錄"), "operation_history.csv",
            file_filter("csv")
        )
        if not path:
            return
        path = normalize_path(path)
        try:
            with open(path, "w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow([
                    tr("時間"), tr("模組"), tr("資料夾"), tr("說明"),
                    tr("成功"), tr("失敗"), tr("釋放空間 (位元組)"),
                ])
                for record in self.records:
                    module = str(record.get("module", ""))
                    writer.writerow([
                        str(record.get("timestamp", "")).replace("T", " "),
                        tr(MODULE_LABELS.get(module, module)),
                        normalize_path(record.get("folder", "")),
                        tr(str(record.get("detail", ""))),
                        record.get("files_processed", 0),
                        record.get("files_failed", 0),
                        record.get("size_freed_bytes", 0),
                    ])
            QMessageBox.information(self, "匯出成功", f"已匯出至 {path}")
        except Exception as exc:
            QMessageBox.warning(self, "匯出失敗", str(exc))

    def _clear(self):
        answer = QMessageBox.question(
            self,
            "清除歷史紀錄",
            "確定要清除所有操作歷史嗎？此動作無法復原。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        clear_history(self.settings)
        self._load_records()
        self._reload()


def show_history_dialog(parent, settings):
    """Convenience helper: build and execute a HistoryDialog."""
    HistoryDialog(parent, settings).exec()
