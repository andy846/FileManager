"""Dashboard: storage insight, favourite folders, recent work and quick actions."""

import csv
import os
import time

from PyQt6.QtCore import QThread, Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView, QFileDialog, QFrame, QGridLayout, QGroupBox,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMenu, QMessageBox, QProgressBar, QPushButton, QScrollArea, QTabWidget,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from app.core.constants import (
    MODULE_BROWSER, MODULE_COMPARE, MODULE_COPY, MODULE_DASHBOARD,
    MODULE_DUPLICATES, MODULE_ICONS, MODULE_LABELS,
    MODULE_REMOVE, MODULE_RENAME, MODULE_SEARCH,
)
from app.core.favorites import add_favorite, favorite_group, list_favorites, remove_favorite
from app.core.history import load_history, summarize_history
from app.core.i18n import file_filter, tr
from app.core.tasks import STATUS_LABELS
from app.core.drives import (
    collect_drive_infos, ensure_network_share, unc_share_root,
)
from app.core.utils import (
    CATEGORY_LABELS, CATEGORY_ORDER, extended_path, format_datetime,
    format_size, is_unc_path, is_unc_server_root, normalize_path, open_path,
    path_name, reveal_in_explorer, short_path,
)
from app.core.workers import OperationControl
from app.modules.dashboard.cache import load_cache, save_cache
from app.modules.dashboard.scanner import AGE_BUCKETS, AGE_LABELS
from app.modules.dashboard.worker import DashboardScanWorker
from app.ui.base import ModulePage
from app.ui.charts import (
    CATEGORY_COLORS, BarList, DonutChart, StatCard,
)
from app.ui.components import EmptyState, PageHeader, make_button
from app.ui.icons import get_icon, icon_color, set_icon
from app.ui.path_utils import is_dir_path
from app.ui.widgets import PathField


class DriveInfoWorker(QThread):
    """Read drive metadata and usage off the UI thread.

    Network drives can block for several seconds; the dashboard must stay
    responsive while Windows resolves them.
    """

    completed = pyqtSignal(list)

    def __init__(self, extra_roots=None):
        super().__init__()
        self.extra_roots = list(extra_roots or ())

    def run(self):
        try:
            infos = collect_drive_infos(self.extra_roots)
        except Exception:
            infos = []
        self.completed.emit(infos)


class _SortItem(QTableWidgetItem):
    """Table item that sorts by a numeric/string key stored per column."""

    def __init__(self, text, sort_value):
        super().__init__(text)
        self.sort_value = sort_value

    def __lt__(self, other):
        try:
            return self.sort_value < other.sort_value
        except AttributeError:
            return super().__lt__(other)


class DashboardPage(ModulePage):
    title = "儀表板"
    module_id = MODULE_DASHBOARD

    def __init__(self, settings, main_window=None):
        super().__init__(settings, main_window)
        self.worker = None
        self.control = None
        self.summary = None
        self._task = None
        self.drive_worker = None
        self._last_drive_refresh = 0.0
        self._task_timer = QTimer(self)
        self._task_timer.setSingleShot(True)
        self._task_timer.setInterval(200)
        self._task_timer.timeout.connect(self._refresh_tasks)
        self._build_ui()
        self._refresh_all()
        if not self.folder.text():
            home = os.path.expanduser("~")
            if home and os.path.isdir(home):
                self.folder.set_path(home)
        manager = self._task_manager()
        if manager is not None:
            manager.changed.connect(self._schedule_task_refresh)
        self._refresh_tasks()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        content = QWidget()
        content.setObjectName("scrollContent")
        scroll.setWidget(content)
        outer.addWidget(scroll)

        root = QVBoxLayout(content)
        root.setContentsMargins(4, 4, 8, 8)
        root.setSpacing(12)

        refresh_btn = make_button(
            "重新整理", "refresh", self.theme(), "ghost",
            "重新整理磁碟與歷史資訊",
        )
        refresh_btn.clicked.connect(self._refresh_all)
        self.page_header = PageHeader(
            "檔案工作台",
            "磁碟、資料夾分析與最近工作一次掌握",
            icon="dashboard",
            actions=[refresh_btn],
            theme=self.theme(),
        )
        root.addWidget(self.page_header)

        kpis = QHBoxLayout()
        kpis.setSpacing(10)
        self.kpi_space = StatCard("磁碟可用空間", "—", "正在讀取...")
        self.kpi_scan = StatCard("已分析資料", "—", "尚未分析資料夾")
        self.kpi_freed = StatCard("累計釋放空間", "—", "尚無操作紀錄")
        self.kpi_success = StatCard("操作成功率", "—", "尚無操作紀錄")
        self.kpi_space.setToolTip(
            "來源：所有本機與網路磁碟的即時可用空間"
        )
        self.kpi_scan.setToolTip(
            "來源：上次「資料夾深入分析」的結果（會保留快取）"
        )
        self.kpi_freed.setToolTip(
            "來源：操作歷史中所有模組累計釋放的空間"
        )
        self.kpi_success.setToolTip(
            "來源：操作歷史中成功與失敗項目計算出的比例"
        )
        for card in (self.kpi_space, self.kpi_scan, self.kpi_freed, self.kpi_success):
            kpis.addWidget(card)
        root.addLayout(kpis)

        main = QHBoxLayout()
        main.setSpacing(12)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(12)
        self._build_analysis_group(left_layout)
        self._build_disk_group(left_layout)
        left_layout.addStretch(1)
        main.addWidget(left, 1)

        right = QWidget()
        right.setFixedWidth(300)
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(12)
        self._build_quick_group(right_layout)
        self._build_cleanup_group(right_layout)
        self.side_tabs = QTabWidget()
        self.side_tabs.setDocumentMode(True)
        self.side_tabs.addTab(self._build_task_group(), "任務")
        self.side_tabs.addTab(self._build_favorites_group(), "最愛")
        self.side_tabs.addTab(self._build_activity_group(), "最近")
        right_layout.addWidget(self.side_tabs)
        right_layout.addStretch(1)
        main.addWidget(right)

        root.addLayout(main)
        self.footer = QLabel("")
        self.footer.setProperty("role", "hint")
        self.footer.setWordWrap(True)
        root.addWidget(self.footer)

    def _build_disk_group(self, parent_layout):
        box = QGroupBox("磁碟概況")
        layout = QVBoxLayout(box)
        head = QHBoxLayout()
        self.disk_summary = QLabel("")
        self.disk_summary.setProperty("role", "hint")
        head.addWidget(self.disk_summary, 1)
        network_btn = make_button(
            "網路位置", "drive", self.theme(), "ghost",
            "新增或移除 UNC 網路共享資料夾",
        )
        network_btn.clicked.connect(self._add_network_location)
        head.addWidget(network_btn)
        refresh = QPushButton()
        refresh.setToolTip("重新整理磁碟資訊")
        refresh.setAccessibleName("重新整理磁碟資訊")
        refresh.setFixedSize(30, 30)
        set_icon(refresh, "refresh", self.theme(), "text", 15)
        refresh.clicked.connect(self._refresh_drives)
        head.addWidget(refresh)
        layout.addLayout(head)
        self.disk_container = QWidget()
        self.disk_layout = QGridLayout(self.disk_container)
        self.disk_layout.setContentsMargins(0, 0, 0, 0)
        self.disk_layout.setSpacing(8)
        self.disk_layout.setColumnStretch(0, 1)
        self.disk_layout.setColumnStretch(1, 1)
        self.disk_layout.setColumnStretch(2, 1)
        disk_scroll = QScrollArea()
        disk_scroll.setWidgetResizable(True)
        disk_scroll.setFrameShape(QFrame.Shape.NoFrame)
        disk_scroll.setMaximumHeight(300)
        disk_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        disk_scroll.setWidget(self.disk_container)
        self.disk_scroll = disk_scroll
        layout.addWidget(disk_scroll)
        parent_layout.addWidget(box)

    def _build_analysis_group(self, parent_layout):
        box = QGroupBox("資料夾深入分析")
        layout = QVBoxLayout(box)

        row = QHBoxLayout()
        self.folder = PathField(settings=self.settings, field_name="dash_folder",
                                placeholder="選擇資料夾後按「分析」")
        row.addWidget(self.folder, 1)
        self.analyze_btn = QPushButton("分析")
        self.analyze_btn.setProperty("variant", "primary")
        self.analyze_btn.clicked.connect(self._on_analyze)
        set_icon(self.analyze_btn, "search", self.theme(), "primary_text", 16)
        row.addWidget(self.analyze_btn)
        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self._on_cancel)
        set_icon(self.cancel_btn, "x", self.theme(), "text", 16)
        row.addWidget(self.cancel_btn)
        layout.addLayout(row)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setVisible(False)
        layout.addWidget(self.progress)

        self.scan_status = QLabel("選擇資料夾後按「分析」，掃描會在背景執行。")
        self.scan_status.setProperty("role", "hint")
        self.scan_status.setWordWrap(True)
        layout.addWidget(self.scan_status)

        self.summary_label = QLabel("")
        layout.addWidget(self.summary_label)

        self.analysis_tabs = QTabWidget()
        self.analysis_tabs.addTab(self._build_overview_tab(), "總覽")
        self.analysis_tabs.addTab(self._build_files_tab(), "最大檔案")
        layout.addWidget(self.analysis_tabs)
        parent_layout.addWidget(box)

    def _build_overview_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(6, 8, 6, 6)
        layout.setSpacing(10)

        analyze_action = make_button(
            "分析目前資料夾", "search", self.theme(), "primary"
        )
        analyze_action.clicked.connect(self._on_analyze)
        self.overview_empty = EmptyState(
            "尚未分析資料夾",
            "選擇資料夾並按「分析」，即可查看容量、類型與檔案年齡。",
            icon="folder-open",
            action=analyze_action,
            theme=self.theme(),
        )
        layout.addWidget(self.overview_empty, 1)

        self.overview_content = QWidget()
        content_layout = QVBoxLayout(self.overview_content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(10)

        categories = QGroupBox("檔案類型")
        cat_layout = QHBoxLayout(categories)
        self.donut = DonutChart()
        self.donut.set_theme(self.theme())
        cat_layout.addWidget(self.donut)
        legend_widget = QWidget()
        self.category_legend = QVBoxLayout(legend_widget)
        self.category_legend.setContentsMargins(4, 4, 4, 4)
        self.category_legend.setSpacing(5)
        cat_layout.addWidget(legend_widget, 1)
        content_layout.addWidget(categories)

        folders = QGroupBox("最大子資料夾")
        folder_layout = QVBoxLayout(folders)
        self.folders_chart = BarList()
        folder_layout.addWidget(self.folders_chart)
        content_layout.addWidget(folders)

        ages = QGroupBox("檔案年齡")
        age_layout = QVBoxLayout(ages)
        self.age_chart = BarList()
        age_layout.addWidget(self.age_chart)
        content_layout.addWidget(ages)
        self.overview_content.setVisible(False)
        layout.addWidget(self.overview_content, 1)
        return tab

    def _build_files_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(6, 8, 6, 6)

        filter_row = QHBoxLayout()
        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("篩選檔名或路徑...")
        self.filter_edit.textChanged.connect(self._filter_files)
        filter_row.addWidget(self.filter_edit, 1)
        export_btn = QPushButton("匯出 CSV")
        export_btn.clicked.connect(self._export_csv)
        filter_row.addWidget(export_btn)
        layout.addLayout(filter_row)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["檔名", "大小", "類型", "修改時間", "路徑"])
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(True)
        self.table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._table_context_menu)
        self.table.cellDoubleClicked.connect(lambda _row, _col: self._open_selected())
        header = self.table.horizontalHeader()
        for col in range(4):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table)
        return tab

    def _build_quick_group(self, parent_layout):
        box = QGroupBox("快速開始")
        layout = QVBoxLayout(box)
        hint = QLabel("僅開啟模組，不會套用上方資料夾。")
        hint.setProperty("role", "hint")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        grid = QGridLayout()
        grid.setSpacing(6)
        layout.addLayout(grid)
        actions = [
            ("瀏覽器", MODULE_BROWSER, "檔案瀏覽器"),
            ("搜尋", MODULE_SEARCH, "檔案搜尋"),
            ("複製 / 搬移", MODULE_COPY, "批量複製 / 搬移"),
            ("刪除", MODULE_REMOVE, "批量刪除"),
            ("重複", MODULE_DUPLICATES, "重複檔案"),
            ("改名", MODULE_RENAME, "批次改名"),
            ("比對", MODULE_COMPARE, "資料夾比對"),
        ]
        for index, (label, module_id, tooltip) in enumerate(actions):
            button = make_button(
                label, MODULE_ICONS.get(module_id), self.theme(), None, tooltip
            )
            button.setMinimumHeight(32)
            button.clicked.connect(
                lambda _=False, mid=module_id: self._goto(mid)
            )
            grid.addWidget(button, index // 2, index % 2)
        parent_layout.addWidget(box)

    def _build_task_group(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(8, 8, 8, 8)
        self.task_list = QListWidget()
        self.task_list.setObjectName("taskList")
        self.task_list.itemDoubleClicked.connect(
            lambda _item: self._show_tasks()
        )
        layout.addWidget(self.task_list, 1)
        view_btn = make_button(
            "開啟任務中心", "task", self.theme(), None, "查看所有任務"
        )
        view_btn.clicked.connect(self._show_tasks)
        layout.addWidget(view_btn)
        self.task_group = tab
        if self._task_manager() is None:
            tab.setEnabled(False)
        return tab

    def _schedule_task_refresh(self):
        if not self._task_timer.isActive():
            self._task_timer.start()

    def _refresh_tasks(self):
        manager = self._task_manager()
        if manager is None:
            return
        self.task_list.clear()
        tasks = manager.recent(6)
        if not tasks:
            item = QListWidgetItem("目前沒有任務")
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.task_list.addItem(item)
            return
        for task in tasks:
            progress = f"{task.percent}%" if task.total else ""
            status = tr(STATUS_LABELS.get(task.status, task.status))
            item = QListWidgetItem(
                f"{tr(task.title)}\n{status} {progress}".strip()
            )
            item.setIcon(get_icon(
                MODULE_ICONS.get(task.module, "task"), self.theme(),
                icon_color(self.theme(), "text"), 16,
            ))
            item.setToolTip(task.message or task.error)
            self.task_list.addItem(item)

    def _show_tasks(self):
        if self.main_window is not None:
            self.main_window._show_tasks()

    def _build_favorites_group(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(8, 8, 8, 8)
        self.fav_list = QListWidget()
        self.fav_list.setObjectName("favoritesList")
        self.fav_list.itemActivated.connect(self._on_favorite_activated)
        layout.addWidget(self.fav_list, 1)
        buttons = QHBoxLayout()
        add_btn = make_button("加入目前", "star", self.theme())
        add_btn.clicked.connect(self._add_favorite)
        remove_btn = make_button("移除", "x", self.theme(), "ghost")
        remove_btn.clicked.connect(self._remove_favorite)
        buttons.addWidget(add_btn)
        buttons.addWidget(remove_btn)
        layout.addLayout(buttons)
        return tab

    def _build_activity_group(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(8, 8, 8, 8)
        self.activity_list = QListWidget()
        self.activity_list.setObjectName("activityList")
        self.activity_list.itemDoubleClicked.connect(
            lambda _item: self._open_history()
        )
        layout.addWidget(self.activity_list, 1)
        history_btn = make_button(
            "查看全部歷史", "history", self.theme()
        )
        history_btn.clicked.connect(self._open_history)
        layout.addWidget(history_btn)
        return tab

    def _build_cleanup_group(self, parent_layout):
        box = QGroupBox("清理建議與快速整理")
        layout = QVBoxLayout(box)
        self.cleanup_source = QLabel(tr("資料來源：尚未分析"))
        self.cleanup_source.setProperty("role", "hint")
        self.cleanup_source.setWordWrap(True)
        layout.addWidget(self.cleanup_source)

        self.junk_hint = QLabel(
            tr("暫存／備份檔（資料夾分析）：尚無分析")
        )
        self.junk_hint.setProperty("role", "hint")
        self.junk_hint.setWordWrap(True)
        self.old_hint = QLabel(
            tr("一年以上大型檔案（資料夾分析）：尚無分析")
        )
        self.old_hint.setProperty("role", "hint")
        self.old_hint.setWordWrap(True)
        self.dup_hint = QLabel(
            tr("重複檔案清理（歷史累計）：尚無紀錄")
        )
        self.dup_hint.setProperty("role", "hint")
        self.dup_hint.setWordWrap(True)
        layout.addWidget(self.junk_hint)
        layout.addWidget(self.old_hint)
        layout.addWidget(self.dup_hint)

        analyze_btn = make_button(
            "重新分析目前資料夾", "refresh", self.theme(), "ghost",
            "重新掃描上方資料夾，更新清理建議",
        )
        analyze_btn.clicked.connect(self._on_analyze)
        layout.addWidget(analyze_btn)

        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(separator)

        quick_title = QLabel(tr("快速整理"))
        quick_title.setProperty("role", "header")
        layout.addWidget(quick_title)
        self.quick_hint = QLabel(
            tr("只會把上方資料夾帶到模組，不會立即刪除或改名。")
        )
        self.quick_hint.setProperty("role", "hint")
        self.quick_hint.setWordWrap(True)
        layout.addWidget(self.quick_hint)
        self.quick_source = QLabel(tr("使用資料夾：尚未選擇"))
        self.quick_source.setProperty("role", "hint")
        self.quick_source.setWordWrap(True)
        layout.addWidget(self.quick_source)

        actions = [
            ("尋找重複檔案", MODULE_DUPLICATES, True, "duplicates",
             "帶入目前資料夾並開啟重複檔案掃描"),
            ("清理此資料夾", MODULE_REMOVE, False, "trash",
             "帶入目前資料夾並開啟批量刪除"),
            ("批次改名", MODULE_RENAME, False, "rename",
             "帶入目前資料夾並開啟批次改名"),
            ("用瀏覽器開啟", MODULE_BROWSER, False, "browser",
             "用檔案瀏覽器開啟目前資料夾"),
        ]
        for label, module_id, autostart, icon_name, tooltip in actions:
            button = make_button(
                label, icon_name, self.theme(), None, tooltip
            )
            button.clicked.connect(
                lambda _=False, mid=module_id, auto=autostart:
                self._send_folder(mid, autostart=auto)
            )
            layout.addWidget(button)
        self.folder.pathChanged.connect(self._on_folder_path_changed)
        parent_layout.addWidget(box)

    # ------------------------------------------------------------------
    # Data refresh
    # ------------------------------------------------------------------
    def _refresh_all(self):
        self._refresh_drives()
        self._refresh_history()
        self._refresh_favorites()
        if self.summary is None:
            cached = load_cache(self.settings)
            if cached is not None:
                self._apply_summary(cached)

    def _network_roots(self):
        raw = self.settings.value("network_roots", [])
        if isinstance(raw, str):
            raw = [raw]
        if not isinstance(raw, (list, tuple)):
            return []
        roots = []
        seen = set()
        for item in raw:
            path = normalize_path(item)
            key = path.casefold()
            if not path or key in seen:
                continue
            seen.add(key)
            roots.append(path)
        return roots

    def _save_network_roots(self, roots):
        values = []
        seen = set()
        for item in roots:
            path = normalize_path(item)
            key = path.casefold()
            if not path or key in seen:
                continue
            seen.add(key)
            values.append(path)
        self.settings.set_value("network_roots", values)
        return values

    def _refresh_drives(self):
        self._last_drive_refresh = time.monotonic()
        if self.drive_worker is not None and self.drive_worker.isRunning():
            return
        self._clear_disk_cards()
        self.disk_summary.setText("讀取磁碟資訊...")
        self.drive_worker = DriveInfoWorker(self._network_roots())
        self.drive_worker.completed.connect(self._render_drives)
        self.drive_worker.start()

    def _choose_network_folder(self, initial=""):
        from app.ui.network_dialog import NetworkLocationDialog

        dialog = NetworkLocationDialog(self, initial=initial)
        if dialog.exec():
            return dialog.selected_path
        return ""

    def _add_network_location(self):
        initial = self.folder.text()
        if not is_unc_path(initial):
            initial = ""
        path = self._choose_network_folder(initial)
        if not path:
            return
        roots = self._network_roots()
        if any(os.path.normcase(root) == os.path.normcase(path)
               for root in roots):
            self.status("此網路位置已在清單中")
            return
        roots.append(path)
        self._save_network_roots(roots)
        self.status(f"已加入網路位置：{path}")
        self._refresh_drives()

    def _remove_network_location(self, path):
        path = normalize_path(path)
        roots = [
            root for root in self._network_roots()
            if os.path.normcase(root) != os.path.normcase(path)
        ]
        self._save_network_roots(roots)
        self.status(f"已移除網路位置：{path}")
        self._refresh_drives()

    def _clear_disk_cards(self):
        while self.disk_layout.count():
            item = self.disk_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

    def _render_drives(self, infos):
        self._clear_disk_cards()
        if not infos:
            self.disk_summary.setText(tr("無法讀取磁碟資訊"))
            self.kpi_space.set_value("—", tr("請稍後重新整理"))
            return
        kind_labels = {
            "fixed": "本機磁碟",
            "network": "網路磁碟",
            "removable": "卸除式磁碟",
            "cdrom": "光碟機",
            "ram": "RAM 磁碟",
            "unknown": "磁碟",
        }
        total_all = 0
        free_all = 0
        network_count = 0
        for index, info in enumerate(infos):
            drive = info.get("root", "")
            total = int(info.get("total", 0) or 0)
            used = int(info.get("used", 0) or 0)
            free = int(info.get("free", 0) or 0)
            error = str(info.get("error", "") or "")

            card = QFrame()
            card.setObjectName("diskCard")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(9, 6, 9, 6)
            card_layout.setSpacing(4)

            top = QHBoxLayout()
            top.setSpacing(6)
            title = info.get("display_name") or drive
            name = QLabel(title)
            name.setStyleSheet("font-weight: bold;")
            name.setToolTip(drive)
            top.addWidget(name)

            if error:
                percent = 0
                detail = tr("無法讀取：") + error
            else:
                total_all += total
                free_all += free
                percent = int(used / total * 100) if total else 0
                detail = (
                    f"{tr('已用')} {format_size(used)} / "
                    f"{format_size(total)} · {tr('可用')} "
                    f"{format_size(free)}"
                )
            top.addStretch(1)
            percent_label = QLabel(f"{percent}%")
            percent_label.setProperty("role", "hint")
            top.addWidget(percent_label)

            if info.get("is_extra"):
                remove = QPushButton(tr("移除"))
                remove.setFixedWidth(46)
                remove.setToolTip(f"{tr('從儀表板移除')} {drive}")
                remove.clicked.connect(
                    lambda _=False, path=drive:
                    self._remove_network_location(path)
                )
                top.addWidget(remove)

            analyze = QPushButton(tr("分析"))
            analyze.setFixedWidth(52)
            analyze.setEnabled(not error)
            analyze.clicked.connect(
                lambda _=False, path=drive: self._analyze_path(path)
            )
            top.addWidget(analyze)
            card_layout.addLayout(top)

            kind = tr(kind_labels.get(info.get("kind", ""), "磁碟"))
            meta_parts = [kind]
            if info.get("filesystem"):
                meta_parts.append(str(info["filesystem"]))
            if info.get("is_network"):
                network_count += 1
                if info.get("unc"):
                    meta_parts.append(short_path(info["unc"], 44))
            meta = " · ".join(meta_parts)
            meta_label = QLabel(meta)
            meta_label.setProperty("role", "hint")
            meta_label.setWordWrap(True)
            meta_label.setToolTip(
                f"{drive}\n"
                + (f"{info.get('unc')}\n" if info.get("unc") else "")
                + meta
            )
            card_layout.addWidget(meta_label)

            bar = QProgressBar()
            bar.setRange(0, 100)
            bar.setValue(percent)
            bar.setFixedHeight(12)
            bar.setTextVisible(False)
            if percent >= 90:
                bar.setStyleSheet(
                    "QProgressBar::chunk { background-color: #e85a6a; "
                    "border-radius: 5px; }"
                )
            elif percent >= 75:
                bar.setStyleSheet(
                    "QProgressBar::chunk { background-color: #e6973f; "
                    "border-radius: 5px; }"
                )
            card_layout.addWidget(bar)

            detail_label = QLabel(
                detail if error else f"{tr('可用')} {format_size(free)}"
            )
            detail_label.setProperty("role", "hint")
            detail_label.setToolTip(detail)
            card_layout.addWidget(detail_label)
            card.setToolTip(
                f"{drive}\n"
                + (f"{info.get('unc')}\n" if info.get("unc") else "")
                + f"{meta}\n{detail}"
            )
            self.disk_layout.addWidget(card, index // 3, index % 3)

        used_all = max(0, total_all - free_all)
        used_percent = int(used_all / total_all * 100) if total_all else 0
        local_count = max(0, len(infos) - network_count)
        self.kpi_space.set_value(
            format_size(free_all),
            f"{tr('本機')} {local_count} · {tr('網路')} {network_count}"
            f" · {tr('共')} {format_size(total_all)}"
            f" · {tr('已用')} {used_percent}%",
        )
        self.disk_summary.setText(
            f"{len(infos)} {tr('個位置')}"
            f"（{tr('本機')} {local_count} · {tr('網路')} {network_count}）"
            f" · {tr('已用')} {format_size(used_all)}"
            f" · {tr('可用')} {format_size(free_all)}"
        )
        rows = max(1, (len(infos) + 2) // 3)
        self.disk_scroll.setMinimumHeight(
            min(300, max(104, rows * 104 + 12))
        )

    def _refresh_history(self):
        records = load_history(self.settings)
        summary = summarize_history(records)
        self.kpi_freed.set_value(
            format_size(summary["freed_bytes"]),
            f"{tr('歷史累計')} · {summary['operations']} {tr('筆操作')}",
        )
        self.kpi_success.set_value(
            f"{summary['success_rate'] * 100:.0f}%",
            f"{tr('歷史累計')} · {tr('成功')} {summary['processed']:,}"
            f" · {tr('失敗')} {summary['failed']:,}",
        )
        duplicate_freed = int(
            summary["by_module"].get(MODULE_DUPLICATES, {}).get(
                "freed_bytes", 0
            )
        )
        self._duplicate_freed = duplicate_freed
        self._update_cleanup_suggestions()

        self.activity_list.clear()
        if not records:
            item = QListWidgetItem(tr("尚無操作紀錄"))
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.activity_list.addItem(item)
            return
        for record in reversed(records[-8:]):
            module = str(record.get("module", ""))
            label = tr(MODULE_LABELS.get(module, module or "操作"))
            timestamp = str(record.get("timestamp", "")).replace("T", " ")[:16]
            detail = tr(str(record.get("detail", "")))
            item = QListWidgetItem(f"{label} · {timestamp}\n{detail}")
            item.setIcon(get_icon(
                MODULE_ICONS.get(module, "file"), self.theme(),
                icon_color(self.theme(), "text"), 16,
            ))
            item.setData(Qt.ItemDataRole.UserRole, record)
            folder = normalize_path(record.get("folder", ""))
            item.setToolTip(
                f"{folder}\n{tr('成功')} "
                f"{record.get('files_processed', 0):,} · "
                f"{tr('失敗')} {record.get('files_failed', 0):,} · "
                f"{tr('釋放')} "
                f"{format_size(record.get('size_freed_bytes', 0))}"
            )
            self.activity_list.addItem(item)

    def _refresh_favorites(self):
        self.fav_list.clear()
        favorites = list_favorites(self.settings)
        if not favorites:
            item = QListWidgetItem(tr("尚未加入最愛資料夾"))
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.fav_list.addItem(item)
            return
        for path in favorites:
            path = normalize_path(path)
            name = path_name(path) or path
            group = favorite_group(self.settings, path)
            item = QListWidgetItem(f"{name}  ·  {group}")
            item.setIcon(get_icon(
                "folder-open", self.theme(),
                icon_color(self.theme(), "text"), 16,
            ))
            item.setData(Qt.ItemDataRole.UserRole, path)
            item.setToolTip(path)
            self.fav_list.addItem(item)

    def _apply_summary(self, summary):
        self.summary = summary
        summary.root = normalize_path(summary.root)
        if summary.root and self.folder.text() != summary.root:
            self.folder.set_path(summary.root)
        self.summary_label.setText(
            f"{format_size(summary.total_size)} · "
            f"{summary.files:,} {tr('個檔案')} · "
            f"{summary.folders:,} {tr('個資料夾')}"
        )
        self.kpi_scan.set_value(
            format_size(summary.total_size),
            f"{tr('上次分析')} · {summary.files:,} {tr('個檔案')}"
            f" · {summary.folders:,} {tr('個資料夾')}",
        )
        errors = (
            f" · {tr('跳過')} {summary.errors} {tr('個無法讀取項目')}"
            if summary.errors else ""
        )
        self.scan_status.setText(
            f"{tr('上次分析：')}{summary.scanned_at} · "
            f"{tr('花費')} {summary.duration:.2f} {tr('秒')}{errors}"
        )
        self.footer.setText(f"{tr('分析路徑：')}{summary.root}")
        self.overview_empty.setVisible(False)
        self.overview_content.setVisible(True)

        self._update_category_chart()
        self._update_folder_chart()
        self._update_age_chart()
        self._populate_files()
        self._update_cleanup_suggestions()

    def _on_folder_path_changed(self, _path):
        self._update_cleanup_source()
        self._update_cleanup_suggestions()

    def _update_cleanup_source(self):
        if not hasattr(self, "cleanup_source"):
            return
        current = normalize_path(self.folder.text())
        self.quick_source.setText(
            f"{tr('使用資料夾：')}{short_path(current, 38)}"
            if current else tr("使用資料夾：尚未選擇")
        )
        self.quick_source.setToolTip(current)
        if self.summary is None:
            self.cleanup_source.setText(tr("資料來源：尚未分析任何資料夾"))
            self.cleanup_source.setToolTip(
                tr("請選擇上方資料夾後按「分析」，清理建議就會依該資料夾計算。")
            )
            return
        root = normalize_path(self.summary.root)
        same = bool(current) and (
            os.path.normcase(current) == os.path.normcase(root)
        )
        if same:
            text = (
                f"{tr('資料來源：資料夾分析')} · {short_path(root, 34)}"
                f" · {self.summary.scanned_at}"
            )
            tip = (
                f"{tr('分析路徑：')}{root}\n"
                f"{tr('分析時間：')}{self.summary.scanned_at}"
            )
        else:
            text = (
                f"{tr('目前資料夾尚未分析；以下為上次分析：')}"
                f"{short_path(root, 30)} · {self.summary.scanned_at}"
            )
            tip = (
                f"{tr('目前上方資料夾與上次分析不同。')}\n"
                f"{tr('上次分析路徑：')}{root}\n"
                f"{tr('分析時間：')}{self.summary.scanned_at}\n"
                f"{tr('請按「重新分析目前資料夾」更新。')}"
            )
        self.cleanup_source.setText(text)
        self.cleanup_source.setToolTip(tip)

    def _update_cleanup_suggestions(self):
        duplicate_freed = int(getattr(self, "_duplicate_freed", 0) or 0)
        if self.summary is None:
            self.junk_hint.setText(
                tr("暫存／備份檔（資料夾分析）：尚無分析")
            )
            self.old_hint.setText(
                tr("一年以上大型檔案（資料夾分析）：尚無分析")
            )
            self.junk_hint.setToolTip(
                tr("來源：尚未分析資料夾\n"
                   "條件：*.tmp、*.temp、*.bak、*.log 等暫存／備份檔")
            )
            self.old_hint.setToolTip(
                tr("來源：尚未分析資料夾\n"
                   "條件：單檔 ≥ 100 MB 且修改時間超過 365 天")
            )
        else:
            root = normalize_path(self.summary.root)
            common = (
                f"{tr('來源：上次資料夾分析')}\n"
                f"{tr('路徑：')}{root}\n"
                f"{tr('分析時間：')}{self.summary.scanned_at}"
            )
            junk_count = tr(
                "{count} 個", count=f"{self.summary.junk_files:,}"
            )
            self.junk_hint.setText(
                f"{tr('暫存／備份檔（資料夾分析）：')}{junk_count}"
                f" · {format_size(self.summary.junk_size)}"
            )
            self.junk_hint.setToolTip(
                common + "\n" + tr(
                    "條件：*.tmp、*.temp、*.bak、*.log、"
                    "*.cache、*.dmp、*.part 等，以及 ~$ 開頭的 Office 暫存檔"
                )
            )
            old_count = tr(
                "{count} 個", count=f"{self.summary.old_large_files:,}"
            )
            self.old_hint.setText(
                f"{tr('一年以上大型檔案（資料夾分析）：')}{old_count}"
                f" · {format_size(self.summary.old_large_size)}"
            )
            self.old_hint.setToolTip(
                common + "\n" + tr(
                    "條件：單檔 ≥ 100 MB 且修改時間超過 365 天"
                )
            )
        self.dup_hint.setText(
            f"{tr('重複檔案清理（歷史累計）：')}"
            f"{tr('累計釋放')} {format_size(duplicate_freed)}"
            if duplicate_freed
            else tr("重複檔案清理（歷史累計）：尚無紀錄")
        )
        self.dup_hint.setToolTip(
            tr("來源：操作歷史檔 operation_history.json\n"
               "範圍：所有資料夾的「重複檔案」模組累計，"
               "不是目前資料夾的即時狀態")
        )
        self._update_cleanup_source()

    def _update_category_chart(self):
        self.donut.set_theme(self.theme())
        sizes = []
        for key in CATEGORY_ORDER:
            size = int(self.summary.categories.get(key, 0) or 0)
            if size > 0:
                sizes.append((key, size))
        sizes.sort(key=lambda item: item[1], reverse=True)
        if len(sizes) > 6:
            top = sizes[:5]
            rest = sum(size for _key, size in sizes[5:])
            items = [
                (tr(CATEGORY_LABELS[key]), size, CATEGORY_COLORS.get(key))
                for key, size in top
            ]
            if rest:
                items.append((tr("其他"), rest, CATEGORY_COLORS["other"]))
        else:
            items = [
                (tr(CATEGORY_LABELS[key]), size, CATEGORY_COLORS.get(key))
                for key, size in sizes
            ]
        self.donut.set_data(items)

        while self.category_legend.count():
            item = self.category_legend.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

        if not items:
            hint = QLabel("尚無分析資料")
            hint.setProperty("role", "hint")
            self.category_legend.addWidget(hint)
            self.category_legend.addStretch(1)
            return

        total = sum(size for _label, size, _color in items)
        for label, size, color in items:
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(6)
            dot = QLabel("●")
            dot.setStyleSheet(f"color: {color};")
            row_layout.addWidget(dot)
            name = QLabel(label)
            row_layout.addWidget(name)
            row_layout.addStretch(1)
            value = QLabel(f"{format_size(size)} ({size / total * 100:.0f}%)")
            value.setProperty("role", "hint")
            row_layout.addWidget(value)
            self.category_legend.addWidget(row)
        self.category_legend.addStretch(1)

    def _update_folder_chart(self):
        self.folders_chart.set_theme(self.theme())
        self.folders_chart.set_data([
            (item.get("name", ""), int(item.get("size", 0) or 0))
            for item in (self.summary.top_folders if self.summary else [])
        ])

    def _update_age_chart(self):
        self.age_chart.set_theme(self.theme())
        buckets = self.summary.age_buckets if self.summary else {}
        self.age_chart.set_data([
            (tr(AGE_LABELS[key]), int(buckets.get(key, 0) or 0))
            for key in AGE_BUCKETS
        ])

    def _populate_files(self):
        files = self.summary.top_files if self.summary else []
        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)
        for entry in files:
            row = self.table.rowCount()
            self.table.insertRow(row)
            name = _SortItem(str(entry.get("name", "")),
                             str(entry.get("name", "")).lower())
            path = normalize_path(entry.get("path", ""))
            name.setData(Qt.ItemDataRole.UserRole, path)
            name.setToolTip(path)
            self.table.setItem(row, 0, name)
            size = int(entry.get("size", 0) or 0)
            self.table.setItem(row, 1, _SortItem(format_size(size), size))
            category = str(entry.get("category", "other"))
            self.table.setItem(
                row, 2,
                QTableWidgetItem(tr(CATEGORY_LABELS.get(category, "其他")))
            )
            modified = float(entry.get("modified", 0.0) or 0.0)
            self.table.setItem(
                row, 3, _SortItem(format_datetime(modified), modified)
            )
            path_item = QTableWidgetItem(short_path(path, 70))
            path_item.setToolTip(path)
            self.table.setItem(row, 4, path_item)
        self.table.setSortingEnabled(True)
        self.table.sortItems(1, Qt.SortOrder.DescendingOrder)
        self._filter_files(self.filter_edit.text())

    def _filter_files(self, text):
        needle = str(text).strip().lower()
        for row in range(self.table.rowCount()):
            name_item = self.table.item(row, 0)
            path_item = self.table.item(row, 4)
            haystack = " ".join(filter(None, [
                name_item.text() if name_item else "",
                path_item.toolTip() if path_item else "",
            ])).lower()
            self.table.setRowHidden(row, bool(needle) and needle not in haystack)

    # ------------------------------------------------------------------
    # Folder analysis
    # ------------------------------------------------------------------
    def _analyze_path(self, path):
        self.folder.set_path(normalize_path(path))
        self._on_analyze()

    def _on_analyze(self):
        folder = normalize_path(self.folder.text())
        if is_unc_server_root(folder):
            folder = self._choose_network_folder(folder)
            if not folder:
                return
            self.folder.set_path(folder)
        if (folder and is_unc_path(folder)
                and not os.path.isdir(extended_path(folder))):
            connected, error = ensure_network_share(
                unc_share_root(folder) or folder
            )
            if not connected:
                QMessageBox.warning(
                    self, "無法連線網路磁碟",
                    f"{folder}\n\n{error}\n\n"
                    "請按「網路」選擇共享資料夾，或輸入帳號密碼。",
                )
                return
        if not folder or not is_dir_path(folder):
            QMessageBox.warning(self, "資料夾錯誤", "請選擇有效的資料夾。")
            return
        if self.worker is not None and self.worker.isRunning():
            return
        self.settings.remember_path("dash_folder", folder)
        self.control = OperationControl()
        self.worker = DashboardScanWorker(folder, self.control)
        self.worker.progress.connect(self._on_progress)
        self.worker.completed.connect(self._on_completed)
        self.worker.failed.connect(self._on_failed)
        self._task = self.task_add(
            "scan", f"分析資料夾：{os.path.basename(folder) or folder}",
            control=self.control, message="掃描中...",
        )
        self._set_busy(True)
        self.scan_status.setText("掃描中...")
        self.status(f"正在分析 {folder} ...")
        self.worker.start()

    def _on_progress(self, files, folders, total_size):
        self.scan_status.setText(
            f"已掃描 {files:,} 個檔案 · {folders:,} 個資料夾"
            f" · {format_size(total_size)}"
        )
        self.task_update(
            self._task, done=files, message=f"{folders:,} 個資料夾"
        )

    def _on_completed(self, summary):
        self._set_busy(False)
        if summary is None:
            self.scan_status.setText("已取消掃描")
            self.task_finish(self._task, status="cancelled")
            self._task = None
            self.status("已取消資料夾分析")
            return
        self._apply_summary(summary)
        save_cache(self.settings, summary)
        self.task_update(self._task, done=summary.files, total=summary.files)
        self.task_finish(
            self._task,
            message=f"{summary.files:,} 個檔案 · {format_size(summary.total_size)}",
        )
        self._task = None
        self.status(
            f"分析完成：{summary.files:,} 個檔案，"
            f"{format_size(summary.total_size)}"
        )

    def _on_failed(self, message):
        self._set_busy(False)
        self.scan_status.setText("分析失敗")
        self.task_finish(self._task, status="failed", error=message)
        self._task = None
        QMessageBox.warning(self, "分析失敗", message)
        self.status("資料夾分析失敗")

    def _on_cancel(self):
        if self.worker is not None and self.worker.isRunning() and self.control:
            self.control.cancel()
            self.cancel_btn.setEnabled(False)
            self.scan_status.setText("正在取消...")

    def _set_busy(self, busy):
        self.analyze_btn.setEnabled(not busy)
        self.cancel_btn.setEnabled(busy)
        self.progress.setVisible(busy)

    # ------------------------------------------------------------------
    # File table actions
    # ------------------------------------------------------------------
    def _selected_path(self):
        row = self.table.currentRow()
        if row < 0:
            return ""
        item = self.table.item(row, 0)
        return normalize_path(item.data(Qt.ItemDataRole.UserRole)) if item else ""

    def _open_selected(self):
        path = self._selected_path()
        if not path:
            return
        ok, error = open_path(path)
        if not ok:
            QMessageBox.warning(self, "無法開啟", error)

    def _reveal_selected(self):
        path = self._selected_path()
        if not path:
            return
        ok, error = reveal_in_explorer(path)
        if not ok:
            QMessageBox.warning(self, "無法顯示", error)

    def _copy_selected_path(self):
        from PyQt6.QtWidgets import QApplication

        path = self._selected_path()
        if path:
            QApplication.clipboard().setText(path)
            self.status("已複製路徑")

    def _table_context_menu(self, pos):
        row = self.table.rowAt(pos.y())
        if row < 0:
            return
        self.table.setCurrentCell(row, 0)
        path = self._selected_path()
        if not path:
            return
        menu = QMenu(self)
        open_action = menu.addAction(tr("開啟"))
        open_action.triggered.connect(self._open_selected)
        reveal_action = menu.addAction(tr("在檔案總管中顯示"))
        reveal_action.triggered.connect(self._reveal_selected)
        copy_action = menu.addAction(tr("複製路徑"))
        copy_action.triggered.connect(self._copy_selected_path)
        menu.addSeparator()

        folder = normalize_path(os.path.dirname(path))
        submenu = menu.addMenu(tr("以資料夾開啟"))
        dup_action = submenu.addAction(tr("重複檔案掃描"))
        dup_action.triggered.connect(
            lambda: self._send_folder(MODULE_DUPLICATES, folder, autostart=True)
        )
        copy_action = submenu.addAction(tr("批量複製 / 搬移"))
        copy_action.triggered.connect(
            lambda: self._send_folder(MODULE_COPY, folder)
        )
        rename_action = submenu.addAction(tr("批次改名"))
        rename_action.triggered.connect(
            lambda: self._send_folder(MODULE_RENAME, folder)
        )
        remove_action = submenu.addAction(tr("批量刪除"))
        remove_action.triggered.connect(
            lambda: self._send_folder(MODULE_REMOVE, folder)
        )
        browser_action = submenu.addAction(tr("檔案瀏覽器"))
        browser_action.triggered.connect(
            lambda: self._send_folder(MODULE_BROWSER, folder)
        )
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def _export_csv(self):
        if self.summary is None:
            QMessageBox.information(self, "匯出", "尚無分析結果可匯出。")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, tr("匯出分析結果"), "folder_analysis.csv", file_filter("csv")
        )
        if not path:
            return
        path = normalize_path(path)
        try:
            with open(path, "w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow([
                    tr("分析路徑"), normalize_path(self.summary.root),
                ])
                writer.writerow([tr("分析時間"), self.summary.scanned_at])
                writer.writerow([
                    tr("總容量 (位元組)"), self.summary.total_size,
                ])
                writer.writerow([tr("檔案數"), self.summary.files])
                writer.writerow([tr("資料夾數"), self.summary.folders])
                writer.writerow([tr("無法讀取項目"), self.summary.errors])
                writer.writerow([])
                writer.writerow([
                    tr("檔案類型"), tr("容量 (位元組)"), tr("容量"),
                ])
                for key in CATEGORY_ORDER:
                    size = int(self.summary.categories.get(key, 0) or 0)
                    writer.writerow([
                        tr(CATEGORY_LABELS[key]), size, format_size(size),
                    ])
                writer.writerow([])
                writer.writerow([
                    tr("最大檔案"), tr("大小 (位元組)"), tr("大小"),
                    tr("類型"), tr("修改時間"), tr("路徑"),
                ])
                for entry in self.summary.top_files:
                    writer.writerow([
                        entry.get("name", ""),
                        entry.get("size", 0),
                        format_size(entry.get("size", 0)),
                        tr(CATEGORY_LABELS.get(
                            entry.get("category", "other"), "其他"
                        )),
                        format_datetime(entry.get("modified", 0)),
                        normalize_path(entry.get("path", "")),
                    ])
                writer.writerow([])
                writer.writerow([
                    tr("最大子資料夾"), tr("容量 (位元組)"), tr("容量"),
                ])
                for entry in self.summary.top_folders:
                    writer.writerow([
                        entry.get("name", ""),
                        entry.get("size", 0),
                        format_size(entry.get("size", 0)),
                    ])
            self.status(f"已匯出分析結果: {path}")
        except Exception as exc:
            QMessageBox.warning(self, "匯出失敗", str(exc))

    # ------------------------------------------------------------------
    # Favourites / history / navigation
    # ------------------------------------------------------------------
    def _add_favorite(self):
        folder = normalize_path(self.folder.text())
        if is_unc_server_root(folder):
            folder = self._choose_network_folder(folder)
        if not folder or not is_dir_path(folder):
            QMessageBox.information(self, "我的最愛", "請先選擇有效的資料夾。")
            return
        changed = add_favorite(self.settings, folder)
        self._refresh_favorites()
        self.status("已加入我的最愛" if changed else "此資料夾已在最愛中")

    def _remove_favorite(self):
        item = self.fav_list.currentItem()
        if item is None:
            return
        path = item.data(Qt.ItemDataRole.UserRole)
        if path and remove_favorite(self.settings, path):
            self._refresh_favorites()
            self.status("已從我的最愛移除")

    def _on_favorite_activated(self, item):
        path = normalize_path(item.data(Qt.ItemDataRole.UserRole))
        if not path:
            return
        if is_unc_server_root(path):
            path = self._choose_network_folder(path)
            if not path:
                return
        if not is_dir_path(path):
            QMessageBox.warning(self, "資料夾不存在", path)
            return
        self._analyze_path(path)

    def _open_history(self):
        from app.ui.history_dialog import show_history_dialog

        show_history_dialog(self, self.settings)
        self._refresh_history()

    def _goto(self, module_id):
        if self.main_window:
            self.main_window.goto_module(module_id)

    def _send_folder(self, module_id, folder=None, autostart=False):
        folder = normalize_path(folder or self.folder.text())
        if is_unc_server_root(folder):
            folder = self._choose_network_folder(folder)
        if (folder and is_unc_path(folder)
                and not os.path.isdir(extended_path(folder))):
            connected, error = ensure_network_share(
                unc_share_root(folder) or folder
            )
            if not connected:
                QMessageBox.warning(
                    self, "無法連線網路磁碟",
                    f"{folder}\n\n{error}",
                )
                return
        if not folder or not is_dir_path(folder):
            QMessageBox.information(self, "快速整理", "請先選擇有效的資料夾。")
            return
        if self.main_window:
            self.main_window.goto_module(
                module_id, {"folder": folder, "autostart": autostart}
            )

    def apply_payload(self, payload):
        if not isinstance(payload, dict):
            return
        folder = normalize_path(payload.get("folder"))
        if folder and (is_dir_path(folder) or is_unc_server_root(folder)):
            self.folder.set_path(folder)
            if payload.get("scan") or payload.get("autostart"):
                QTimer.singleShot(0, self._on_analyze)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def on_show(self):
        if time.monotonic() - self._last_drive_refresh > 30:
            self._refresh_drives()
        self._refresh_history()
        self._refresh_favorites()

    def on_theme_changed(self):
        self.page_header.set_theme(self.theme())
        self.overview_empty.set_theme(self.theme())
        self.donut.set_theme(self.theme())
        self._refresh_drives()
        self._refresh_tasks()
        if self.summary is not None:
            self._update_category_chart()
            self._update_folder_chart()
            self._update_age_chart()

    def request_stop(self):
        if self.worker is not None and self.worker.isRunning():
            if self.control:
                self.control.cancel()
            self.worker.wait(5000)
        if self.drive_worker is not None and self.drive_worker.isRunning():
            self.drive_worker.wait(3000)

