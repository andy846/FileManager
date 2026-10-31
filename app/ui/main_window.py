"""Application shell: grouped sidebar, stacked modules, tasks and palette."""

from PyQt6.QtCore import QSignalBlocker, QSize, Qt, QThread
from PyQt6.QtGui import QKeySequence, QShortcut, QColor, QFont
from PyQt6.QtWidgets import (
    QAbstractItemView, QApplication, QMainWindow, QWidget, QHBoxLayout,
    QVBoxLayout, QListWidget, QListWidgetItem, QTreeWidget,
    QTreeWidgetItem, QStackedWidget, QLabel, QStatusBar, QToolButton,
    QMessageBox,
)

from app.core.constants import (
    APP_NAME, APP_VERSION, MODULE_COMPARE, MODULE_COPY, MODULE_DASHBOARD,
    MODULE_HASH, MODULE_ICONS, MODULE_MOVE, MODULE_NAV_LABELS,
    MODULE_SETTINGS, NAV_GROUPS,
)
from app.core.favorites import list_favorites
from app.core.i18n import tr
from app.core.settings import AppSettings
from app.core.tasks import TaskManager
from app.core.utils import path_name
from app.core.theme import apply_theme
from app.ui.base import ModulePage
from app.ui.icons import (
    get_icon, icon_color, refresh_icons, set_icon,
)


class MainWindow(QMainWindow):
    def __init__(self, settings: AppSettings):
        super().__init__()
        self.settings = settings
        if isinstance(settings, AppSettings):
            settings.migrate()
        self.theme = self.settings.option("theme", "dark")
        self.pages = []
        self.pages_by_id = {}
        self.nav_items = {}
        self._selected_nav_item = None
        self._collapsed = bool(
            self.settings.option("sidebar_collapsed", False)
        )
        self.tasks = TaskManager(self)
        self._task_dialog = None

        self.setWindowTitle(f"{APP_NAME} v{APP_VERSION}")
        self.resize(1180, 760)
        self._build_ui()
        self._register_modules()
        self._populate_compact_nav()
        self._apply_sidebar_state(self._collapsed, persist=False)
        apply_theme(QApplication.instance(), self.theme)
        self._restore_geometry()
        self._select_start_page()
        self._update_task_button()
        self.tasks.changed.connect(self._update_task_button)
        self.show_status("就緒")

    # ------------------------------------------------------------------
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(216)
        self.sidebar = sidebar
        s_layout = QVBoxLayout(sidebar)
        s_layout.setContentsMargins(10, 12, 10, 10)
        s_layout.setSpacing(6)
        self._sidebar_layout = s_layout

        self.logo = QLabel("FileManager")
        self.logo.setProperty("role", "header")
        self.logo.setWordWrap(False)
        s_layout.addWidget(self.logo)

        self.version_label = QLabel(f"檔案工作台 · v{APP_VERSION}")
        self.version_label.setProperty("role", "hint")
        s_layout.addWidget(self.version_label)

        self.collapse_btn = QToolButton()
        self.collapse_btn.setObjectName("sidebarCollapseBtn")
        self.collapse_btn.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextBesideIcon
        )
        self.collapse_btn.setIconSize(QSize(18, 18))
        self.collapse_btn.setFixedHeight(34)
        self.collapse_btn.clicked.connect(self._toggle_sidebar)
        s_layout.addWidget(self.collapse_btn)

        self.nav = QTreeWidget()
        self.nav.setObjectName("navTree")
        self.nav.setHeaderHidden(True)
        self.nav.setIndentation(10)
        self.nav.setAnimated(False)
        self.nav.setUniformRowHeights(True)
        self.nav.setRootIsDecorated(True)
        self.nav.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.nav.currentItemChanged.connect(self._on_nav)
        s_layout.addWidget(self.nav, 1)

        self.compact_nav = QListWidget()
        self.compact_nav.setObjectName("compactNav")
        self.compact_nav.setSpacing(2)
        self.compact_nav.setVisible(False)
        self.compact_nav.itemClicked.connect(self._on_compact_nav)
        s_layout.addWidget(self.compact_nav, 1)

        footer = QHBoxLayout()
        footer.setSpacing(4)
        self.theme_btn = QToolButton()
        self.theme_btn.setFixedSize(32, 32)
        self.theme_btn.clicked.connect(self._toggle_theme)
        footer.addWidget(self.theme_btn)
        self.history_btn = QToolButton()
        self.history_btn.setFixedSize(32, 32)
        self.history_btn.clicked.connect(self._show_history)
        footer.addWidget(self.history_btn)
        footer.addStretch(1)
        self.palette_btn = QToolButton()
        self.palette_btn.setFixedSize(32, 32)
        self.palette_btn.clicked.connect(self._show_command_palette)
        footer.addWidget(self.palette_btn)
        self.footer_layout = footer
        s_layout.addLayout(footer)

        root.addWidget(sidebar)

        content = QWidget()
        c_layout = QVBoxLayout(content)
        c_layout.setContentsMargins(12, 12, 12, 12)
        self.stack = QStackedWidget()
        c_layout.addWidget(self.stack)
        root.addWidget(content, 1)

        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self._status_label = QLabel("就緒")
        self.status_bar.addWidget(self._status_label, 1)
        self.task_btn = QToolButton()
        self.task_btn.setText("任務")
        self.task_btn.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextBesideIcon
        )
        self.task_btn.setToolTip("開啟任務中心 (Ctrl+Shift+J)")
        self.task_btn.clicked.connect(self._show_tasks)
        self.status_bar.addPermanentWidget(self.task_btn)
        self._update_shell_icons()

        QShortcut(QKeySequence("Ctrl+K"), self,
                  activated=self._show_command_palette)
        QShortcut(QKeySequence("Ctrl+Shift+J"), self,
                  activated=self._show_tasks)
        QShortcut(QKeySequence("Ctrl+B"), self,
                  activated=self._toggle_sidebar)

    def _module_classes(self):
        from app.modules.dashboard.page import DashboardPage
        from app.modules.browser.page import BrowserPage
        from app.modules.search.page import SearchPage
        from app.modules.copier.page import CopierPage
        from app.modules.remover.page import RemoverPage
        from app.modules.duplicates.page import DuplicatesPage
        from app.modules.renamer.page import RenamerPage
        from app.modules.compare.page import ComparePage
        from app.modules.hash.page import HashPage
        from app.modules.archive.page import ArchivePage
        from app.modules.settings.page import SettingsPage

        return [
            DashboardPage, BrowserPage, SearchPage, CopierPage,
            RemoverPage, DuplicatesPage, RenamerPage, ComparePage, HashPage,
            ArchivePage, SettingsPage,
        ]

    def _register_modules(self):
        for PageCls in self._module_classes():
            page = PageCls(self.settings, self)
            self.pages.append(page)
            self.pages_by_id[page.module_id] = page
            self.stack.addWidget(page)

        self.nav_items = {}
        for heading, module_ids in NAV_GROUPS:
            group = QTreeWidgetItem([heading])
            group.setFlags(Qt.ItemFlag.ItemIsEnabled)
            group.setFirstColumnSpanned(True)
            font = QFont(group.font(0))
            font.setBold(True)
            font.setPointSize(8)
            group.setFont(0, font)
            group.setForeground(0, QColor(icon_color(self.theme, "nav_group")))
            group.setIcon(0, get_icon(
                "chevron-down", self.theme,
                icon_color(self.theme, "nav_group"), 14,
            ))
            self.nav.addTopLevelItem(group)
            group.setExpanded(True)
            for module_id in module_ids:
                page = self.pages_by_id.get(module_id)
                if page is None:
                    continue
                item = QTreeWidgetItem([page.title])
                item.setData(0, Qt.ItemDataRole.UserRole, module_id)
                item.setIcon(0, get_icon(
                    MODULE_ICONS.get(module_id, "file"), self.theme,
                    icon_color(self.theme, "text"), 16,
                ))
                group.addChild(item)
                self.nav_items[module_id] = item

        for index, page in enumerate(self.pages[:9]):
            shortcut = QShortcut(QKeySequence(f"Ctrl+{index + 1}"), self)
            shortcut.activated.connect(
                lambda mid=page.module_id: self.goto_module(mid)
            )
        self.nav.itemClicked.connect(self._on_nav_item_clicked)
        self.nav.itemExpanded.connect(self._update_group_icon)
        self.nav.itemCollapsed.connect(self._update_group_icon)

    def _on_nav_item_clicked(self, item, _column):
        if item.parent() is None:
            item.setExpanded(not item.isExpanded())

    def _update_group_icon(self, item):
        if item.parent() is not None:
            return
        item.setIcon(0, get_icon(
            "chevron-down" if item.isExpanded() else "chevron-right",
            self.theme, icon_color(self.theme, "nav_group"), 14,
        ))

    def _all_nav_items(self):
        items = []
        for group_index in range(self.nav.topLevelItemCount()):
            group = self.nav.topLevelItem(group_index)
            for child_index in range(group.childCount()):
                items.append(group.child(child_index))
        return items

    def _populate_compact_nav(self):
        self.compact_nav.clear()
        self.compact_nav.setIconSize(QSize(20, 20))
        for group_index, (_heading, module_ids) in enumerate(NAV_GROUPS):
            for module_id in module_ids:
                page = self.pages_by_id.get(module_id)
                if page is None:
                    continue
                item = QListWidgetItem()
                item.setIcon(get_icon(
                    MODULE_ICONS.get(module_id, "file"), self.theme,
                    icon_color(self.theme, "text"), 20,
                ))
                item.setData(Qt.ItemDataRole.UserRole, module_id)
                item.setToolTip(page.title)
                item.setSizeHint(QSize(0, 38))
                self.compact_nav.addItem(item)
            if group_index < len(NAV_GROUPS) - 1:
                spacer = QListWidgetItem("")
                spacer.setFlags(Qt.ItemFlag.NoItemFlags)
                spacer.setSizeHint(QSize(0, 10))
                self.compact_nav.addItem(spacer)

    def _on_compact_nav(self, item):
        module_id = item.data(Qt.ItemDataRole.UserRole)
        if module_id:
            self.goto_module(module_id)

    def _select_compact(self, module_id):
        if not hasattr(self, "compact_nav"):
            return
        for index in range(self.compact_nav.count()):
            item = self.compact_nav.item(index)
            if item.data(Qt.ItemDataRole.UserRole) == module_id:
                blocker = QSignalBlocker(self.compact_nav)
                self.compact_nav.setCurrentItem(item)
                del blocker
                return

    def _toggle_sidebar(self):
        self._apply_sidebar_state(not self._collapsed)

    def _apply_sidebar_state(self, collapsed, persist=True):
        self._collapsed = bool(collapsed)
        width = 64 if self._collapsed else 216
        self.sidebar.setFixedWidth(width)
        margins = (6, 12, 6, 10) if self._collapsed else (10, 12, 10, 10)
        self._sidebar_layout.setContentsMargins(*margins)
        self.logo.setText("FM" if self._collapsed else "FileManager")
        self.logo.setVisible(True)
        if self._collapsed:
            self.logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._sidebar_layout.setAlignment(
                self.logo, Qt.AlignmentFlag.AlignHCenter
            )
            self._sidebar_layout.setAlignment(
                self.collapse_btn, Qt.AlignmentFlag.AlignHCenter
            )
        else:
            self.logo.setAlignment(
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
            )
            self._sidebar_layout.setAlignment(
                self.logo, Qt.AlignmentFlag.AlignLeft
            )
            self._sidebar_layout.setAlignment(
                self.collapse_btn, Qt.AlignmentFlag.AlignLeft
            )
        self.version_label.setVisible(not self._collapsed)
        self.nav.setVisible(not self._collapsed)
        self.compact_nav.setVisible(self._collapsed)
        for button in (self.theme_btn, self.history_btn, self.palette_btn):
            button.setVisible(not self._collapsed)
        self.collapse_btn.setVisible(True)
        set_icon(
            self.collapse_btn,
            "chevron-right" if self._collapsed else "chevron-left",
            self.theme, "primary_accent", 18,
        )
        if self._collapsed:
            self.collapse_btn.setText("")
            self.collapse_btn.setToolButtonStyle(
                Qt.ToolButtonStyle.ToolButtonIconOnly
            )
            self.collapse_btn.setFixedSize(40, 40)
        else:
            self.collapse_btn.setText(tr("收起側邊欄"))
            self.collapse_btn.setToolButtonStyle(
                Qt.ToolButtonStyle.ToolButtonTextBesideIcon
            )
            self.collapse_btn.setFixedSize(196, 34)
        tip = "展開側邊欄 (Ctrl+B)" if self._collapsed else "收起側邊欄 (Ctrl+B)"
        self.collapse_btn.setToolTip(tr(tip))
        self.collapse_btn.setAccessibleName(tr(tip))
        if persist:
            self.settings.set_option("sidebar_collapsed", self._collapsed)
        current = self.nav.currentItem()
        if current is not None:
            module_id = current.data(0, Qt.ItemDataRole.UserRole)
            if module_id:
                self._select_compact(module_id)

    def _find_nav_item(self, module_id):
        return self.nav_items.get(module_id)

    def _select_start_page(self):
        start = self.settings.option("start_page", MODULE_DASHBOARD)
        if start == MODULE_MOVE:
            # Legacy start page: batch move lives in the merged copy/move page.
            start = MODULE_COPY
        item = self._find_nav_item(start) or self._find_nav_item(MODULE_DASHBOARD)
        if item is not None:
            self.nav.setCurrentItem(item)

    def _on_nav(self, current, previous=None):
        if current is None:
            return
        if current.parent() is None:
            target = self._selected_nav_item
            if target is None and current.childCount():
                target = current.child(0)
            if target is not None:
                blocker = QSignalBlocker(self.nav)
                self.nav.setCurrentItem(target)
                del blocker
            return
        if previous is not None and previous.parent() is not None:
            previous.setIcon(0, get_icon(
                MODULE_ICONS.get(
                    previous.data(0, Qt.ItemDataRole.UserRole), "file"
                ),
                self.theme, icon_color(self.theme, "text"), 16,
            ))
        if current.parent() is not None:
            current.setIcon(0, get_icon(
                MODULE_ICONS.get(
                    current.data(0, Qt.ItemDataRole.UserRole), "file"
                ),
                self.theme, icon_color(self.theme, "primary_accent"), 16,
            ))
            self._selected_nav_item = current
        module_id = current.data(0, Qt.ItemDataRole.UserRole)
        page = self.pages_by_id.get(module_id)
        if page is None:
            return
        self._select_compact(module_id)
        self.stack.setCurrentWidget(page)
        page.on_show()

    def goto_module(self, module_id, payload=None):
        if module_id == MODULE_MOVE:
            # Backwards-compatible fallback for callers that still target the
            # old standalone move module. Batch move now lives in the merged
            # copy/move page and is selected through its operation switch.
            module_id = MODULE_COPY
            payload = {**(payload or {}), "operation": "move"}
        item = self._find_nav_item(module_id)
        if item is None:
            return
        self.nav.setCurrentItem(item)
        self._select_compact(module_id)
        page = self.pages_by_id.get(module_id)
        if payload is not None and isinstance(page, ModulePage):
            page.apply_payload(payload)

    def _toggle_theme(self):
        self.set_theme("light" if self.theme == "dark" else "dark")

    def set_theme(self, theme):
        self.theme = "light" if theme == "light" else "dark"
        self.settings.set_option("theme", self.theme)
        apply_theme(QApplication.instance(), self.theme)
        self._update_shell_icons()
        refresh_icons(self, self.theme)
        for page in self.pages:
            page.on_theme_changed()
            refresh_icons(page, self.theme)

    def _update_shell_icons(self):
        theme_icon = "sun" if self.theme == "dark" else "moon"
        theme_label = "切換至淺色模式" if self.theme == "dark" else "切換至深色模式"
        set_icon(self.theme_btn, theme_icon, self.theme, "text", 17)
        self.theme_btn.setToolTip(theme_label)
        self.theme_btn.setAccessibleName(theme_label)
        set_icon(self.history_btn, "history", self.theme, "text", 17)
        self.history_btn.setToolTip("操作歷史")
        self.history_btn.setAccessibleName("操作歷史")
        set_icon(self.palette_btn, "search", self.theme, "text", 17)
        self.palette_btn.setToolTip("命令面板 (Ctrl+K)")
        self.palette_btn.setAccessibleName("命令面板")
        set_icon(self.task_btn, "task", self.theme, "text", 15)
        if hasattr(self, "nav_items"):
            current = self.nav.currentItem()
            for module_id, item in self.nav_items.items():
                item.setIcon(0, get_icon(
                    MODULE_ICONS.get(module_id, "file"), self.theme,
                    icon_color(
                        self.theme,
                        "primary_accent" if item is current else "text",
                    ),
                    16,
                ))
            for index in range(self.nav.topLevelItemCount()):
                group = self.nav.topLevelItem(index)
                group.setForeground(0, QColor(
                    icon_color(self.theme, "nav_group")
                ))
                self._update_group_icon(group)
        if hasattr(self, "compact_nav"):
            for index in range(self.compact_nav.count()):
                item = self.compact_nav.item(index)
                module_id = item.data(Qt.ItemDataRole.UserRole)
                if module_id:
                    item.setIcon(get_icon(
                        MODULE_ICONS.get(module_id, "file"), self.theme,
                        icon_color(self.theme, "text"), 20,
                    ))
        if hasattr(self, "collapse_btn"):
            set_icon(
                self.collapse_btn,
                "chevron-right" if self._collapsed else "chevron-left",
                self.theme, "primary_accent", 18,
            )

    def apply_settings(self):
        theme = self.settings.option("theme", "dark")
        if theme != self.theme:
            self.set_theme(theme)
        for page in self.pages:
            page.on_settings_changed()
        self._update_task_button()

    def show_status(self, message, timeout=0):
        self._status_label.setText(message)
        if timeout:
            self.status_bar.showMessage(message, timeout)

    def _update_task_button(self):
        active = self.tasks.active_count()
        self.task_btn.setText(f"任務 {active}" if active else "任務")
        self.task_btn.setToolTip(
            f"進行中 {active} · 歷史任務 {len(self.tasks.tasks())}"
        )

    def _show_tasks(self):
        from app.ui.task_center import TaskCenterDialog

        if self._task_dialog is not None and self._task_dialog.isVisible():
            self._task_dialog.raise_()
            self._task_dialog.activateWindow()
            return
        self._task_dialog = TaskCenterDialog(
            self.tasks, self, theme=self.theme
        )
        self._task_dialog.setAttribute(
            Qt.WidgetAttribute.WA_DeleteOnClose, True
        )
        self._task_dialog.finished.connect(self._clear_task_dialog)
        self._task_dialog.show()

    def _clear_task_dialog(self, _result=None):
        self._task_dialog = None

    def _show_command_palette(self):
        from app.ui.command_palette import Command, run_command_palette

        commands = []
        for _heading, module_ids in NAV_GROUPS:
            for module_id in module_ids:
                page = self.pages_by_id.get(module_id)
                if page is None:
                    continue
                commands.append(Command(
                    tr(page.title),
                    f"{tr('前往模組')} · "
                    f"{tr(MODULE_NAV_LABELS.get(module_id, module_id))}",
                    lambda mid=module_id: self.goto_module(mid),
                ))
        for path in list_favorites(self.settings):
            name = path_name(path) or path
            commands.append(Command(
                name,
                path,
                lambda target=path: self.goto_module(
                    "browser", {"folder": target}
                ),
            ))
        commands.extend([
            Command(tr("任務中心"), tr("查看進行中與已完成的工作"),
                    self._show_tasks),
            Command(tr("操作歷史"), tr("檢視、篩選與匯出歷史"),
                    self._show_history),
            Command(tr("資料夾比對"), tr("比較兩個資料夾的差異"),
                    lambda: self.goto_module(MODULE_COMPARE)),
            Command(tr("計算雜湊"), tr("開啟雜湊工具"),
                    lambda: self.goto_module(MODULE_HASH)),
            Command(tr("設定"), tr("外觀、操作與歷史設定"),
                    lambda: self.goto_module(MODULE_SETTINGS)),
            Command(tr("切換主題"), tr("切換亮色／深色"),
                    self._toggle_theme),
        ])
        run_command_palette(self, commands)

    def _show_history(self):
        from app.ui.history_dialog import show_history_dialog

        show_history_dialog(self, self.settings)

    def _restore_geometry(self):
        geo = self.settings.load_geometry()
        if geo:
            try:
                self.restoreGeometry(geo)
            except Exception:
                pass

    def closeEvent(self, event):
        for page in self.pages:
            if hasattr(page, "request_stop"):
                try:
                    page.request_stop()
                except Exception:
                    pass
        # request_stop() uses bounded waits; never destroy a running QThread.
        active = []
        for page in self.pages:
            for value in vars(page).values():
                if isinstance(value, QThread) and value.isRunning():
                    active.append(value)
        active.extend(
            thread for thread in self.findChildren(QThread)
            if thread.isRunning() and thread not in active
        )
        if active:
            event.ignore()
            QMessageBox.information(
                self, "仍有檔案操作進行中",
                "已要求背景工作停止；部分磁碟或網路操作尚未完成。"
                "為保障檔案完整性，暫時不會關閉程式，請稍後再關閉。",
            )
            return
        self.settings.save_geometry(self.saveGeometry())
        self.settings.q.sync()
        super().closeEvent(event)
