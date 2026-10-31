"""ZIP/TAR browsing, extraction and ZIP creation."""

import os

from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView, QCheckBox, QFileDialog, QGroupBox, QHBoxLayout,
    QLabel, QMessageBox, QProgressBar, QPushButton, QStackedWidget,
    QTabWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from app.core.archive import (
    create_zip, extract_archive, list_archive,
)
from app.core.constants import MODULE_ARCHIVE
from app.core.history import record_operation
from app.core.i18n import file_filter, tr
from app.core.utils import (
    format_datetime, format_size, is_dir_fs, short_path,
)
from app.core.workers import CancelledError, OperationControl
from app.ui.base import ModulePage
from app.ui.components import EmptyState, PageHeader, make_button
from app.ui.icons import set_icon
from app.ui.widgets import PathField


class ArchiveListWorker(QThread):
    completed = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, path):
        super().__init__()
        self.path = path

    def run(self):
        try:
            self.completed.emit(list_archive(self.path))
        except Exception as exc:
            self.failed.emit(str(exc))


class ExtractWorker(QThread):
    progress = pyqtSignal(int, int, str)
    completed = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, path, dest, members, overwrite, control):
        super().__init__()
        self.path = path
        self.dest = dest
        self.members = members
        self.overwrite = overwrite
        self.control = control

    def cancel(self):
        self.control.cancel()

    def run(self):
        try:
            result = extract_archive(
                self.path, self.dest, self.members,
                overwrite=self.overwrite, control=self.control,
                progress=self.progress.emit,
            )
            self.completed.emit(result)
        except CancelledError:
            self.completed.emit({"cancelled": True, "extracted": 0,
                                 "skipped": 0, "failed": 0, "errors": []})
        except Exception as exc:
            self.failed.emit(str(exc))


class CreateZipWorker(QThread):
    progress = pyqtSignal(int, int, str)
    completed = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, output, sources, control):
        super().__init__()
        self.output = output
        self.sources = sources
        self.control = control

    def cancel(self):
        self.control.cancel()

    def run(self):
        try:
            result = create_zip(
                self.output, self.sources, control=self.control,
                progress=self.progress.emit,
            )
            self.completed.emit(result)
        except CancelledError:
            self.completed.emit({"cancelled": True, "added": 0,
                                 "failed": 0, "output": self.output})
        except Exception as exc:
            self.failed.emit(str(exc))


class ArchivePage(ModulePage):
    title = "壓縮檔"
    module_id = MODULE_ARCHIVE

    def __init__(self, settings, main_window=None):
        super().__init__(settings, main_window)
        self.members = []
        self.list_worker = None
        self.worker = None
        self.control = None
        self._task = None
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        self.page_header = PageHeader(
            "壓縮檔",
            "安全地瀏覽、解壓 ZIP／TAR，或將資料夾建立為 ZIP",
            icon="archive",
            theme=self.theme(),
        )
        root.addWidget(self.page_header)
        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_browse_tab(), "瀏覽／解壓")
        self.tabs.addTab(self._build_create_tab(), "建立 ZIP")
        root.addWidget(self.tabs)

    def _build_browse_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        row = QHBoxLayout()
        self.archive_path = PathField(
            mode="file", settings=self.settings, field_name="archive_path",
            placeholder="選擇 ZIP／TAR 壓縮檔",
        )
        row.addWidget(self.archive_path, 1)
        open_btn = QPushButton("開啟")
        set_icon(open_btn, "folder-open", self.theme(), "text", 15)
        open_btn.clicked.connect(self._open_archive)
        row.addWidget(open_btn)
        layout.addLayout(row)

        self.member_info = QLabel("尚未開啟壓縮檔")
        self.member_info.setProperty("role", "hint")
        layout.addWidget(self.member_info)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["名稱", "大小", "類型", "修改時間"])
        self.tree.setAlternatingRowColors(True)
        self.tree.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self.tree.setColumnWidth(0, 420)
        self.tree.setColumnWidth(1, 100)
        self.tree.setColumnWidth(2, 90)
        self.tree.setColumnWidth(3, 160)
        empty_action = make_button(
            "開啟壓縮檔", "folder-open", self.theme(), "primary"
        )
        empty_action.clicked.connect(self._choose_archive)
        self.empty_results = EmptyState(
            "尚未開啟壓縮檔",
            "選擇 ZIP／TAR 檔案，或切換到「建立 ZIP」分頁。",
            icon="archive",
            action=empty_action,
            theme=self.theme(),
        )
        self.tree_stack = QStackedWidget()
        self.tree_stack.addWidget(self.empty_results)
        self.tree_stack.addWidget(self.tree)
        layout.addWidget(self.tree_stack, 1)

        dest_box = QGroupBox("解壓設定")
        dest_layout = QVBoxLayout(dest_box)
        dest_row = QHBoxLayout()
        self.dest = PathField(
            settings=self.settings, field_name="archive_dest",
            placeholder="解壓目標資料夾",
        )
        dest_row.addWidget(self.dest, 1)
        layout.addWidget(dest_box)
        dest_layout.addLayout(dest_row)
        options = QHBoxLayout()
        self.overwrite = QCheckBox("覆寫同名檔案")
        options.addWidget(self.overwrite)
        self.select_all_btn = QPushButton("全選")
        self.select_all_btn.clicked.connect(lambda: self._select_all(True))
        self.select_btn = QPushButton("取消全選")
        self.select_btn.clicked.connect(lambda: self._select_all(False))
        extract_selected = QPushButton("解壓選取")
        extract_selected.clicked.connect(lambda: self._extract(True))
        extract_all = QPushButton("解壓全部")
        extract_all.setProperty("variant", "primary")
        extract_all.clicked.connect(lambda: self._extract(False))
        options.addWidget(self.select_all_btn)
        options.addWidget(self.select_btn)
        options.addStretch(1)
        options.addWidget(extract_selected)
        options.addWidget(extract_all)
        dest_layout.addLayout(options)

        self.progress = QProgressBar()
        self.progress.setVisible(False)
        layout.addWidget(self.progress)
        self.status_label = QLabel("")
        self.status_label.setProperty("role", "hint")
        layout.addWidget(self.status_label)
        return tab

    def _build_create_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        source_box = QGroupBox("來源資料夾")
        source_layout = QVBoxLayout(source_box)
        self.source = PathField(
            settings=self.settings, field_name="zip_source",
            placeholder="選擇要壓縮的資料夾",
        )
        source_layout.addWidget(self.source)
        layout.addWidget(source_box)

        output_box = QGroupBox("輸出 ZIP")
        output_layout = QHBoxLayout(output_box)
        self.output = PathField(
            mode="file", settings=self.settings, field_name="zip_output",
            placeholder="輸出 ZIP 路徑",
        )
        output_layout.addWidget(self.output, 1)
        browse = QPushButton("另存新檔")
        browse.clicked.connect(self._choose_output)
        output_layout.addWidget(browse)
        layout.addWidget(output_box)

        create_btn = QPushButton("建立 ZIP")
        create_btn.setProperty("variant", "primary")
        set_icon(create_btn, "archive", self.theme(), "primary_text", 16)
        create_btn.clicked.connect(self._create_zip)
        layout.addWidget(create_btn)
        self.create_status = QLabel("")
        self.create_status.setProperty("role", "hint")
        layout.addWidget(self.create_status)
        layout.addStretch(1)
        return tab

    def _select_all(self, selected):
        for index in range(self.tree.topLevelItemCount()):
            self.tree.topLevelItem(index).setSelected(selected)

    def _choose_archive(self):
        path, _ = QFileDialog.getOpenFileName(
            self, tr("選擇壓縮檔"), "", file_filter("archive"),
        )
        if not path:
            return
        self.archive_path.set_path(path)
        self._open_archive()

    def _open_archive(self):
        path = self.archive_path.text()
        if not path or not os.path.isfile(path):
            QMessageBox.warning(self, "壓縮檔", "請選擇有效的壓縮檔。")
            return
        self.settings.remember_path("archive_path", path)
        self.list_worker = ArchiveListWorker(path)
        self.list_worker.completed.connect(self._on_listed)
        self.list_worker.failed.connect(
            lambda message: QMessageBox.warning(self, "開啟失敗", message)
        )
        self.member_info.setText("讀取壓縮檔中...")
        self.list_worker.start()

    def _on_listed(self, members):
        self.members = members
        self.tree.clear()
        for member in members:
            item = QTreeWidgetItem(self.tree)
            name = member.name.rstrip("/\\")
            item.setText(0, name)
            item.setToolTip(0, member.name)
            item.setText(1, "—" if member.is_dir else format_size(member.size))
            item.setText(
                2, tr("資料夾") if member.is_dir else tr("檔案")
            )
            item.setText(3, format_datetime(member.mtime))
            item.setData(0, 0x0100, member.name)
        total = sum(member.size for member in members if not member.is_dir)
        count_text = tr(f"{len(members):,} 個項目")
        self.member_info.setText(
            f"{count_text} · {tr('解壓後約')} {format_size(total)}"
        )
        if members:
            self.tree_stack.setCurrentWidget(self.tree)
        else:
            self.empty_results.set_content(
                "壓縮檔是空的", "這個壓縮檔沒有可顯示的項目。"
            )
            self.tree_stack.setCurrentWidget(self.empty_results)
        self.status(f"已開啟壓縮檔：{len(members)} 個項目")

    def _extract(self, selected_only):
        path = self.archive_path.text()
        dest = self.dest.text()
        if not path or not os.path.isfile(path):
            QMessageBox.warning(self, "壓縮檔", "請先開啟有效的壓縮檔。")
            return
        if not dest:
            QMessageBox.warning(self, "解壓", "請選擇解壓目標資料夾。")
            return
        members = None
        if selected_only:
            members = [
                item.data(0, 0x0100) for item in self.tree.selectedItems()
            ]
            if not members:
                QMessageBox.information(self, "解壓", "請先選取要解壓的項目。")
                return
        if self.worker is not None and self.worker.isRunning():
            return
        self.control = OperationControl()
        self.worker = ExtractWorker(
            path, dest, members, self.overwrite.isChecked(), self.control
        )
        self.worker.progress.connect(self._on_progress)
        self.worker.completed.connect(self._on_extracted)
        self.worker.failed.connect(self._on_failed)
        total = len(members) if members else len(self.members)
        self._task = self.task_add(
            "extract", "解壓縮", control=self.control, total=total,
        )
        self.progress.setVisible(True)
        self.progress.setRange(0, max(1, total))
        self.progress.setValue(0)
        self.status("解壓縮中...")
        self.worker.start()

    def _on_progress(self, done, total, name):
        self.progress.setRange(0, max(1, total))
        self.progress.setValue(done)
        self.status_label.setText(f"{done}/{total} · {short_path(name, 70)}")
        self.task_update(self._task, done=done, total=total,
                         message=short_path(name, 60))

    def _on_extracted(self, summary):
        self.progress.setVisible(False)
        status = "cancelled" if summary.get("cancelled") else "done"
        message = (
            f"解壓 {summary['extracted']} · 略過 {summary['skipped']}"
            f" · 失敗 {summary['failed']}"
        )
        self.task_finish(self._task, status=status, message=message)
        self._task = None
        record_operation(
            self.settings, MODULE_ARCHIVE, self.dest.text(),
            message, summary["extracted"], summary["failed"],
        )
        if summary.get("errors"):
            QMessageBox.warning(
                self, "解壓完成但有錯誤",
                message + "\n" + "\n".join(
                    f"{path}: {error}" for path, error in summary["errors"][:10]
                ),
            )
        else:
            QMessageBox.information(self, "解壓完成", message)
        self.status(message)

    def _on_failed(self, message):
        self.progress.setVisible(False)
        self.task_finish(self._task, status="failed", error=message)
        self._task = None
        QMessageBox.warning(self, "操作失敗", message)

    def _choose_output(self):
        path, _ = QFileDialog.getSaveFileName(
            self, tr("建立 ZIP"), "archive.zip", file_filter("zip")
        )
        if path:
            if not path.lower().endswith(".zip"):
                path += ".zip"
            self.output.set_path(path)

    def _create_zip(self):
        source = self.source.text()
        output = self.output.text()
        if not source or not is_dir_fs(source):
            QMessageBox.warning(self, "建立 ZIP", "請選擇來源資料夾。")
            return
        if not output:
            self._choose_output()
            output = self.output.text()
        if not output:
            return
        if not output.lower().endswith(".zip"):
            output += ".zip"
            self.output.set_path(output)
        if self.worker is not None and self.worker.isRunning():
            return
        self.control = OperationControl()
        self.worker = CreateZipWorker(output, [source], self.control)
        self.worker.progress.connect(
            lambda done, total, path: self.create_status.setText(
                f"{done}/{total} · {short_path(path, 60)}"
            )
        )
        self.worker.completed.connect(self._on_created)
        self.worker.failed.connect(self._on_failed)
        self._task = self.task_add(
            "zip", "建立 ZIP", control=self.control,
        )
        self.create_status.setText("建立 ZIP 中...")
        self.worker.start()

    def _on_created(self, summary):
        status = (
            "cancelled" if summary.get("cancelled")
            else "done" if summary.get("committed")
            else "failed"
        )
        message = f"加入 {summary['added']} 個檔案 · 失敗 {summary['failed']}"
        if not summary.get("committed"):
            message += " · 未更新輸出 ZIP（保留舊檔）"
        self.task_finish(self._task, status=status, message=message)
        self._task = None
        record_operation(
            self.settings, MODULE_ARCHIVE, os.path.dirname(summary["output"]),
            message, summary["added"], summary["failed"],
        )
        self.create_status.setText(message)
        self.status(message)
        QMessageBox.information(self, "建立 ZIP", message)

    def on_theme_changed(self):
        self.page_header.set_theme(self.theme())
        self.empty_results.set_theme(self.theme())

    def apply_payload(self, payload):
        if not isinstance(payload, dict):
            return
        path = payload.get("archive")
        if path and os.path.isfile(path):
            self.archive_path.set_path(path)
            self._open_archive()

    def request_stop(self):
        for worker in (self.list_worker, self.worker):
            if worker is not None and worker.isRunning():
                if hasattr(worker, "cancel"):
                    worker.cancel()
                worker.wait(5000)
