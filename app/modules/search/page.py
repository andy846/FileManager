"""Background file search with filters and cross-module hand-off."""

import csv
import datetime
import os

from PyQt6.QtCore import QDate, QThread, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView, QCheckBox, QDateEdit, QFileDialog,
    QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QMenu,
    QMessageBox, QProgressBar, QPushButton, QSpinBox, QStackedWidget,
    QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from app.core.constants import (
    MODULE_DUPLICATES, MODULE_REMOVE, MODULE_RENAME, MODULE_SEARCH,
)
from app.core.history import record_operation
from app.core.i18n import file_filter, tr
from app.core.search import SearchOptions, iter_search
from app.core.utils import (
    CATEGORY_LABELS, file_category, format_datetime, format_size,
    is_dir_fs, normalize_path, open_path, reveal_in_explorer, short_path,
)
from app.core.workers import CancelledError, OperationControl
from app.ui.base import ModulePage
from app.ui.components import EmptyState, PageHeader, make_button
from app.ui.icons import set_icon
from app.ui.widgets import PathField


class _SortItem(QTableWidgetItem):
    def __init__(self, text, value):
        super().__init__(text)
        self.value = value

    def __lt__(self, other):
        try:
            return self.value < other.value
        except AttributeError:
            return super().__lt__(other)


class SearchWorker(QThread):
    batch = pyqtSignal(list)
    progress = pyqtSignal(int, int)
    completed = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, options, control):
        super().__init__()
        self.options = options
        self.control = control

    def cancel(self):
        self.control.cancel()

    def run(self):
        buffer = []
        summary = {"matched": 0, "cancelled": False, "elapsed": 0.0}
        last_emit = 0.0
        import time

        started = time.time()
        try:
            for info in iter_search(
                self.options, control=self.control,
                progress=self.progress.emit,
            ):
                buffer.append(info)
                summary["matched"] += 1
                now = time.time()
                if len(buffer) >= 200 or now - last_emit >= 0.25:
                    self.batch.emit(buffer)
                    buffer = []
                    last_emit = now
            if buffer:
                self.batch.emit(buffer)
            summary["elapsed"] = time.time() - started
            self.completed.emit(summary)
        except CancelledError:
            if buffer:
                self.batch.emit(buffer)
            summary["cancelled"] = True
            summary["elapsed"] = time.time() - started
            self.completed.emit(summary)
        except Exception as exc:
            self.failed.emit(str(exc))


class SearchPage(ModulePage):
    title = "檔案搜尋"
    module_id = MODULE_SEARCH

    def __init__(self, settings, main_window=None):
        super().__init__(settings, main_window)
        self.worker = None
        self.control = None
        self._task = None
        self._results = []
        self._limit = 10000
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        self.page_header = PageHeader(
            "檔案搜尋",
            "跨多個資料夾搜尋檔案，支援大小、日期、類型與排除樣式",
            icon="search",
            theme=self.theme(),
        )
        root.addWidget(self.page_header)
        roots_box = QGroupBox("搜尋資料夾")
        roots_layout = QVBoxLayout(roots_box)
        row = QHBoxLayout()
        self.root_path = PathField(
            settings=self.settings, field_name="search_root",
            placeholder="選擇搜尋根目錄",
        )
        row.addWidget(self.root_path, 1)
        add_btn = QPushButton("加入根目錄")
        add_btn.clicked.connect(self._add_root)
        remove_btn = QPushButton("移除")
        remove_btn.clicked.connect(self._remove_root)
        row.addWidget(add_btn)
        row.addWidget(remove_btn)
        roots_layout.addLayout(row)
        self.roots = QListWidget()
        self.roots.setObjectName("searchRoots")
        self.roots.setMaximumHeight(86)
        roots_layout.addWidget(self.roots)
        root.addWidget(roots_box)

        filters = QGroupBox("搜尋條件")
        filters_layout = QVBoxLayout(filters)
        name_row = QHBoxLayout()
        self.name = QLineEdit()
        self.name.setPlaceholderText("檔名（支援 * ? 或正規表示式）")
        self.regex = QCheckBox("正規表示式")
        self.case_sensitive = QCheckBox("區分大小寫")
        name_row.addWidget(QLabel("名稱:"))
        name_row.addWidget(self.name, 1)
        name_row.addWidget(self.regex)
        name_row.addWidget(self.case_sensitive)
        filters_layout.addLayout(name_row)

        meta_row = QHBoxLayout()
        self.extensions = QLineEdit()
        self.extensions.setPlaceholderText("副檔名，例如 pdf, jpg, docx")
        self.exclude = QLineEdit()
        self.exclude.setPlaceholderText("排除樣式，例如 *.tmp, node_modules/")
        meta_row.addWidget(QLabel("類型:"))
        meta_row.addWidget(self.extensions, 1)
        meta_row.addWidget(QLabel("排除:"))
        meta_row.addWidget(self.exclude, 1)
        filters_layout.addLayout(meta_row)

        size_row = QHBoxLayout()
        self.min_mb = QSpinBox()
        self.min_mb.setRange(0, 1000000)
        self.max_mb = QSpinBox()
        self.max_mb.setRange(0, 1000000)
        size_row.addWidget(QLabel("大小 ≥"))
        size_row.addWidget(self.min_mb)
        size_row.addWidget(QLabel("MB ≤"))
        size_row.addWidget(self.max_mb)
        size_row.addWidget(QLabel("MB"))
        size_row.addSpacing(12)
        self.use_date = QCheckBox("修改日期")
        self.date_from = QDateEdit(QDate.currentDate().addYears(-1))
        self.date_to = QDateEdit(QDate.currentDate())
        for widget in (self.date_from, self.date_to):
            widget.setCalendarPopup(True)
        size_row.addWidget(self.use_date)
        size_row.addWidget(self.date_from)
        size_row.addWidget(QLabel("至"))
        size_row.addWidget(self.date_to)
        size_row.addStretch(1)
        self.recursive = QCheckBox("包含子資料夾")
        self.recursive.setChecked(True)
        self.hidden = QCheckBox("包含隱藏檔案")
        size_row.addWidget(self.recursive)
        size_row.addWidget(self.hidden)
        filters_layout.addLayout(size_row)
        root.addWidget(filters)

        actions = QHBoxLayout()
        self.search_btn = QPushButton("開始搜尋")
        self.search_btn.setProperty("variant", "primary")
        set_icon(self.search_btn, "search", self.theme(), "primary_text", 16)
        self.search_btn.clicked.connect(self._on_search)
        self.stop_btn = QPushButton("停止")
        self.stop_btn.setEnabled(False)
        set_icon(self.stop_btn, "stop", self.theme(), "text", 15)
        self.stop_btn.clicked.connect(self._on_stop)
        self.export_btn = QPushButton("匯出 CSV")
        set_icon(self.export_btn, "download", self.theme(), "text", 15)
        self.export_btn.clicked.connect(self._export)
        actions.addWidget(self.search_btn)
        actions.addWidget(self.stop_btn)
        actions.addWidget(self.export_btn)
        actions.addStretch(1)
        root.addLayout(actions)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setVisible(False)
        root.addWidget(self.progress)
        self.summary = QLabel("加入資料夾後開始搜尋")
        self.summary.setProperty("role", "hint")
        root.addWidget(self.summary)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["檔名", "大小", "類型", "修改時間", "資料夾", "路徑"]
        )
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(True)
        self.table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self.table.verticalHeader().setVisible(False)
        self.table.setColumnWidth(0, 220)
        self.table.setColumnWidth(1, 90)
        self.table.setColumnWidth(2, 90)
        self.table.setColumnWidth(3, 150)
        self.table.setColumnWidth(4, 220)
        self.table.setColumnWidth(5, 400)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._context_menu)
        self.table.cellDoubleClicked.connect(lambda _r, _c: self._open_selected())

        start_action = make_button("開始搜尋", "search", self.theme(), "primary")
        start_action.clicked.connect(self._on_search)
        self.empty_results = EmptyState(
            "尚無搜尋結果",
            "加入搜尋資料夾與條件，然後開始搜尋。",
            icon="search",
            action=start_action,
            theme=self.theme(),
        )
        self.results_stack = QStackedWidget()
        self.results_stack.addWidget(self.empty_results)
        self.results_stack.addWidget(self.table)
        root.addWidget(self.results_stack, 1)

    def _add_root(self):
        path = self.root_path.text()
        if not path or not is_dir_fs(path):
            QMessageBox.warning(self, "搜尋", "請選擇有效的資料夾。")
            return
        existing = [self.roots.item(i).text() for i in range(self.roots.count())]
        if path not in existing:
            self.roots.addItem(path)
        self.settings.remember_path("search_root", path)

    def _remove_root(self):
        removed = []
        for item in self.roots.selectedItems():
            removed.append(item.text())
            self.roots.takeItem(self.roots.row(item))
        if self.root_path.text() in removed:
            self.root_path.line.clear()

    def _root_list(self):
        return [self.roots.item(i).text() for i in range(self.roots.count())]

    def _options(self):
        self._add_root_from_field()
        roots = self._root_list()
        after = before = 0.0
        if self.use_date.isChecked():
            start = self.date_from.date().toPyDate()
            end = self.date_to.date().toPyDate()
            after = datetime.datetime.combine(start, datetime.time.min).timestamp()
            before = datetime.datetime.combine(end, datetime.time.max).timestamp()
        return SearchOptions(
            roots=roots,
            name=self.name.text(),
            use_regex=self.regex.isChecked(),
            case_sensitive=self.case_sensitive.isChecked(),
            min_size=self.min_mb.value() * 1024 * 1024,
            max_size=self.max_mb.value() * 1024 * 1024,
            modified_after=after,
            modified_before=before,
            extensions=[x.strip() for x in self.extensions.text().split(",")
                        if x.strip()],
            exclude=[x.strip() for x in self.exclude.text().split(",")
                     if x.strip()],
            recursive=self.recursive.isChecked(),
            include_hidden=self.hidden.isChecked(),
        )

    def _add_root_from_field(self):
        path = self.root_path.text()
        if path and is_dir_fs(path):
            existing = self._root_list()
            if path not in existing:
                self.roots.addItem(path)

    def _on_search(self):
        options = self._options()
        if not options.roots:
            QMessageBox.information(self, "搜尋", "請先加入至少一個資料夾。")
            return
        if self.worker is not None and self.worker.isRunning():
            return
        self.table.setRowCount(0)
        self._results = []
        self.control = OperationControl()
        self.worker = SearchWorker(options, self.control)
        self.worker.batch.connect(self._add_rows)
        self.worker.progress.connect(self._on_progress)
        self.worker.completed.connect(self._on_complete)
        self.worker.failed.connect(self._on_failed)
        self._task = self.task_add(
            "search", "檔案搜尋", control=self.control,
            message="搜尋中...",
        )
        self.empty_results.set_content(
            "搜尋中...", "正在掃描資料夾，結果會即時顯示。"
        )
        self.results_stack.setCurrentWidget(self.empty_results)
        self.search_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.progress.setVisible(True)
        self.progress.setRange(0, 0)
        self.summary.setText("搜尋中...")
        self.status("搜尋檔案中...")
        self.worker.start()

    def _on_progress(self, scanned, matched):
        self.summary.setText(
            f"已掃描 {scanned:,} 個檔案 · 找到 {matched:,} 個"
        )
        self.task_update(self._task, message=f"已找到 {matched:,} 個")

    def _add_rows(self, infos):
        if infos:
            self.results_stack.setCurrentWidget(self.table)
        self.table.setSortingEnabled(False)
        for info in infos:
            if len(self._results) >= self._limit:
                break
            self._results.append(info)
            row = self.table.rowCount()
            self.table.insertRow(row)
            name = _SortItem(info.name, info.name.lower())
            name.setData(Qt.ItemDataRole.UserRole, info.path)
            name.setToolTip(info.path)
            self.table.setItem(row, 0, name)
            self.table.setItem(
                row, 1, _SortItem(format_size(info.size), info.size)
            )
            self.table.setItem(
                row, 2,
                QTableWidgetItem(tr(CATEGORY_LABELS.get(
                    file_category(info.name), "其他"
                ))),
            )
            self.table.setItem(
                row, 3, _SortItem(format_datetime(info.modified),
                                 info.modified)
            )
            self.table.setItem(
                row, 4, QTableWidgetItem(short_path(os.path.dirname(info.path), 50))
            )
            path_item = QTableWidgetItem(short_path(info.path, 80))
            path_item.setToolTip(info.path)
            self.table.setItem(row, 5, path_item)
        self.table.setSortingEnabled(True)

    def _on_complete(self, summary):
        self.search_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.progress.setVisible(False)
        status = "cancelled" if summary.get("cancelled") else "done"
        elapsed = float(summary.get("elapsed", 0.0) or 0.0)
        message = (
            f"找到 {summary['matched']:,} 個檔案 · {elapsed:.1f}s"
        )
        self.summary.setText(message + ("（已達顯示上限）"
                                       if len(self._results) >= self._limit else ""))
        if not self._results:
            self.empty_results.set_content(
                "找不到符合條件的檔案",
                "試著放寬名稱、大小或日期條件，或加入更多搜尋資料夾。",
            )
            self.results_stack.setCurrentWidget(self.empty_results)
        self.task_finish(self._task, status=status, message=message)
        self._task = None
        self.status(message)
        record_operation(
            self.settings, MODULE_SEARCH,
            "；".join(self._root_list()[:3]), message,
            summary["matched"], 0,
        )

    def _on_failed(self, message):
        self.search_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.progress.setVisible(False)
        self.task_finish(self._task, status="failed", error=message)
        self._task = None
        QMessageBox.warning(self, "搜尋失敗", message)

    def _on_stop(self):
        if self.control is not None:
            self.control.cancel()

    def _selected_paths(self):
        paths = []
        for row in {index.row() for index in self.table.selectedIndexes()}:
            item = self.table.item(row, 0)
            if item is not None:
                paths.append(item.data(Qt.ItemDataRole.UserRole))
        return paths

    def _open_selected(self):
        paths = self._selected_paths()
        if not paths:
            return
        ok, error = open_path(paths[0])
        if not ok:
            QMessageBox.warning(self, "無法開啟", error)

    def _reveal_selected(self):
        paths = self._selected_paths()
        if paths:
            reveal_in_explorer(paths[0])

    def _copy_path(self):
        paths = self._selected_paths()
        if not paths:
            return
        from PyQt6.QtWidgets import QApplication

        QApplication.clipboard().setText("\n".join(paths))
        self.status("已複製路徑")

    def _context_menu(self, pos):
        row = self.table.rowAt(pos.y())
        if row < 0:
            return
        self.table.selectRow(row)
        paths = self._selected_paths()
        if not paths:
            return
        menu = QMenu(self)
        open_action = menu.addAction(tr("開啟"))
        open_action.triggered.connect(self._open_selected)
        reveal_action = menu.addAction(tr("在檔案總管中顯示"))
        reveal_action.triggered.connect(self._reveal_selected)
        copy_action = menu.addAction(tr("複製路徑"))
        copy_action.triggered.connect(self._copy_path)
        menu.addSeparator()
        folder = os.path.dirname(paths[0])
        submenu = menu.addMenu(tr("以資料夾開啟"))
        for label, module_id, autostart in (
            ("重複檔案掃描", MODULE_DUPLICATES, True),
            ("批次改名", MODULE_RENAME, False),
            ("批量刪除", MODULE_REMOVE, False),
        ):
            action = submenu.addAction(tr(label))
            action.triggered.connect(
                lambda _=False, mid=module_id, auto=autostart, path=folder:
                self.main_window.goto_module(
                    mid, {"folder": path, "autostart": auto}
                ) if self.main_window else None
            )
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def _export(self):
        if not self._results:
            QMessageBox.information(self, "匯出", "尚無搜尋結果。")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, tr("匯出搜尋結果"), "search_results.csv", file_filter("csv")
        )
        if not path:
            return
        path = normalize_path(path)
        try:
            with open(path, "w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow([
                    tr("檔名"), tr("大小"), tr("修改時間"), tr("路徑"),
                ])
                for info in self._results:
                    writer.writerow([
                        info.name, info.size,
                        format_datetime(info.modified), info.path,
                    ])
            self.status(f"已匯出搜尋結果: {path}")
        except Exception as exc:
            QMessageBox.warning(self, "匯出失敗", str(exc))

    def apply_payload(self, payload):
        if not isinstance(payload, dict):
            return
        folder = payload.get("folder")
        if folder and is_dir_fs(folder):
            self.root_path.set_path(folder)
            if folder not in self._root_list():
                self.roots.addItem(folder)

    def on_theme_changed(self):
        self.page_header.set_theme(self.theme())
        self.empty_results.set_theme(self.theme())

    def request_stop(self):
        if self.worker is not None and self.worker.isRunning():
            self.worker.cancel()
            self.worker.wait(5000)
