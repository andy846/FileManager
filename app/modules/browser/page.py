"""Dual-pane file browser inspired by classic Windows file managers."""

import json
import os

from PyQt6.QtCore import QDir, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QCursor, QKeySequence, QShortcut

try:  # PyQt6 6.11 moved QFileSystemModel into QtGui.
    from PyQt6.QtGui import QFileSystemModel
except ImportError:  # pragma: no cover - older PyQt6 releases
    from PyQt6.QtWidgets import QFileSystemModel

from PyQt6.QtWidgets import (
    QCheckBox, QFileDialog, QHBoxLayout, QInputDialog,
    QMenu, QMessageBox, QPushButton, QSplitter, QTabWidget, QToolButton,
    QVBoxLayout, QWidget,
)

from app.core.i18n import tr
from app.core.constants import (
    MODULE_BROWSER, MODULE_COPY, MODULE_DUPLICATES, MODULE_HASH,
    MODULE_REMOVE, MODULE_RENAME,
)
from app.core.favorites import (
    add_favorite, favorite_group, grouped_favorites, set_favorite_group,
)
from app.core.history import record_operation
from app.core.utils import (
    extended_path, format_datetime, format_size, is_unc_path,
    is_unc_server_root, normalize_path, open_path, path_name,
    reveal_in_explorer, short_path,
)
from app.ui.path_utils import is_dir_path
from app.core.workers import OperationControl
from app.core.file_ops import TrashWorker
from app.modules.browser.operations import OperationDialog
from app.modules.browser.pane import BrowserPane
from app.modules.browser.preview import PreviewPanel
from app.ui.base import ModulePage
from app.ui.components import PageHeader
from app.ui.icons import get_icon, icon_color, set_icon


class BrowserTab(QWidget):
    """One tab containing one or two browser panes."""

    title_changed = pyqtSignal()

    def __init__(self, model, parent=None):
        super().__init__(parent)
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.left = BrowserPane(model)
        self.right = BrowserPane(model)
        self.splitter.addWidget(self.left)
        self.splitter.addWidget(self.right)
        self.splitter.setSizes([500, 500])

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.splitter)

        self.active_pane = self.left
        self.dual = True
        for pane in (self.left, self.right):
            pane.activated.connect(lambda p=pane: self._set_active(p))

    def _set_active(self, pane):
        if self.active_pane is not pane:
            self.active_pane = pane
            self.title_changed.emit()

    def set_dual(self, enabled):
        self.dual = bool(enabled)
        self.right.setVisible(self.dual)
        if not self.dual and self.active_pane is self.right:
            self.active_pane = self.left
            self.title_changed.emit()

    def label(self):
        path = self.active_pane.current_path
        if not path:
            return "本機"
        return path_name(path) or path


class BrowserPage(ModulePage):
    title = "檔案瀏覽器"
    module_id = MODULE_BROWSER

    def __init__(self, settings, main_window=None):
        super().__init__(settings, main_window)
        self.show_hidden = self.settings.option("browser_show_hidden", False)
        self._restoring = True
        self._operation_dialog = None
        self._trash_worker = None
        self._op_task = None
        self._task = None
        self._closed_tabs = []
        self._columns = self.settings.value(
            "browser/columns", {"type": True, "date": True}
        )
        if not isinstance(self._columns, dict):
            self._columns = {"type": True, "date": True}
        self.clipboard = {"mode": "", "paths": []}
        self._pending_preview = None

        self.model = QFileSystemModel(self)
        self.model.setReadOnly(True)
        # Custom folder icons (cloud/OneDrive/Dropbox overlays etc.) require
        # shell round-trips for every folder and are very slow on networks.
        self.model.setOption(
            QFileSystemModel.Option.DontUseCustomDirectoryIcons, True
        )
        self.model.setOption(
            QFileSystemModel.Option.DontResolveSymlinks, True
        )
        self.model.setRootPath("")
        self.model.setFilter(self._filter_flags())
        from app.modules.browser.thumbnails import ThumbnailIconProvider

        self._icon_provider = ThumbnailIconProvider()
        self.model.setIconProvider(self._icon_provider)

        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(120)
        self._preview_timer.timeout.connect(self._apply_preview)

        self._build_ui()
        self._icon_provider.set_thumbnails_enabled(
            self.icons_check.isChecked()
        )
        self._restore_state()
        self._restoring = False
        self._refresh_favorites_menu()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _filter_flags(self):
        flags = (QDir.Filter.AllEntries | QDir.Filter.NoDotAndDotDot
                 | QDir.Filter.AllDirs)
        if self.show_hidden:
            flags |= QDir.Filter.Hidden
        return flags

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        self.page_header = PageHeader(
            "檔案瀏覽器",
            "雙窗格瀏覽、快速預覽與安全檔案操作",
            icon="browser",
            theme=self.theme(),
        )
        root.addWidget(self.page_header)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(6)
        new_tab = QPushButton("新分頁")
        set_icon(new_tab, "plus", self.theme(), "text", 15)
        new_tab.clicked.connect(lambda: self._new_tab())
        toolbar.addWidget(new_tab)
        close_tab = QPushButton("關閉分頁")
        set_icon(close_tab, "x", self.theme(), "text", 14)
        close_tab.clicked.connect(self._close_current_tab)
        toolbar.addWidget(close_tab)
        self.drives_btn = QToolButton()
        self.drives_btn.setText("磁碟")
        self.drives_btn.setToolTip("本機磁碟、網路磁碟與 UNC 共享")
        self.drives_btn.setPopupMode(
            QToolButton.ToolButtonPopupMode.InstantPopup
        )
        set_icon(self.drives_btn, "drive", self.theme(), "text", 15)
        self.drive_menu = QMenu(self)
        self.drive_menu.aboutToShow.connect(self._refresh_drive_menu)
        self.drives_btn.setMenu(self.drive_menu)
        toolbar.addWidget(self.drives_btn)

        self.dual_check = QCheckBox("雙窗格")
        self.dual_check.setChecked(True)
        self.dual_check.toggled.connect(self._toggle_dual)
        toolbar.addWidget(self.dual_check)

        self.hidden_check = QCheckBox("顯示隱藏檔")
        self.hidden_check.setChecked(self.show_hidden)
        self.hidden_check.toggled.connect(self._toggle_hidden)
        toolbar.addWidget(self.hidden_check)

        self.icons_check = QCheckBox("縮圖")
        set_icon(self.icons_check, "grid", self.theme(), "text", 14)
        self.icons_check.setChecked(
            self.settings.option("browser_icons", False)
        )
        self.icons_check.toggled.connect(self._toggle_icons)
        toolbar.addWidget(self.icons_check)

        self.preview_check = QCheckBox("預覽")
        set_icon(self.preview_check, "eye", self.theme(), "text", 14)
        self.preview_check.toggled.connect(self._toggle_preview)
        toolbar.addWidget(self.preview_check)

        self.fav_btn = QToolButton()
        self.fav_btn.setText("我的最愛")
        set_icon(self.fav_btn, "star", self.theme(), "text", 15)
        self.fav_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.fav_menu = QMenu(self)
        self.fav_menu.aboutToShow.connect(self._refresh_favorites_menu)
        self.fav_btn.setMenu(self.fav_menu)
        toolbar.addWidget(self.fav_btn)

        self.columns_btn = QToolButton()
        self.columns_btn.setText("欄位")
        set_icon(self.columns_btn, "columns", self.theme(), "text", 15)
        self.columns_btn.setPopupMode(
            QToolButton.ToolButtonPopupMode.InstantPopup
        )
        column_menu = QMenu(self)
        self.type_action = column_menu.addAction(tr("顯示類型"))
        self.type_action.setCheckable(True)
        self.type_action.setChecked(bool(self._columns.get("type", True)))
        self.type_action.toggled.connect(
            lambda checked: self._set_column_visible("type", checked)
        )
        self.date_action = column_menu.addAction(tr("顯示修改時間"))
        self.date_action.setCheckable(True)
        self.date_action.setChecked(bool(self._columns.get("date", True)))
        self.date_action.toggled.connect(
            lambda checked: self._set_column_visible("date", checked)
        )
        self.columns_btn.setMenu(column_menu)
        toolbar.addWidget(self.columns_btn)
        toolbar.addStretch(1)
        root.addLayout(toolbar)

        body = QSplitter(Qt.Orientation.Horizontal)
        self.tabs = QTabWidget()
        self.tabs.setObjectName("browserTabs")
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)
        self.tabs.setDocumentMode(True)
        self.tabs.tabCloseRequested.connect(self._close_tab)
        self.tabs.currentChanged.connect(self._on_tab_changed)
        body.addWidget(self.tabs)

        self.preview = PreviewPanel()
        self.preview.max_image_bytes = int(
            self.settings.option("preview_max_mb", 20) * 1024 * 1024
        )
        self.preview.setVisible(False)
        body.addWidget(self.preview)
        body.setStretchFactor(0, 1)
        body.setSizes([800, 320])
        root.addWidget(body, 1)

        self.tabs.tabBar().setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )
        self.tabs.tabBar().customContextMenuRequested.connect(
            self._tab_context_menu
        )
        QShortcut(QKeySequence("Ctrl+Shift+T"), self,
                  activated=self._restore_closed_tab)

    # ------------------------------------------------------------------
    # Tabs and state
    # ------------------------------------------------------------------
    def _home_path(self):
        home = normalize_path(os.path.expanduser("~"))
        if home and os.path.isdir(home):
            return home
        recent = self.settings.recent("browser_folder")
        if recent and is_dir_path(recent[0]):
            return recent[0]
        return ""

    def _new_tab(self, left_path=None, right_path=None, activate=True):
        tab = BrowserTab(self.model)
        tab.set_dual(self.settings.option("browser_dual", True))
        index = self.tabs.addTab(tab, tr("本機"))
        self._connect_tab(tab)
        home = self._home_path()
        left = left_path if left_path is not None else home
        right = right_path if right_path is not None else left
        tab.left.navigate(left)
        tab.right.navigate(right)
        tab.left.set_compact(self.preview.isVisible())
        tab.right.set_compact(self.preview.isVisible())
        tab.left.set_thumbnail_mode(self.icons_check.isChecked())
        tab.right.set_thumbnail_mode(self.icons_check.isChecked())
        for pane in (tab.left, tab.right):
            pane.set_column_visible(2, self._columns.get("type", True))
            pane.set_column_visible(3, self._columns.get("date", True))
        tab.title_changed.connect(lambda t=tab: self._update_tab_title(t))
        self._update_tab_title(tab)
        tab.active_pane = tab.left
        if activate:
            self.tabs.setCurrentIndex(index)
        return tab

    def _connect_tab(self, tab):
        for pane in (tab.left, tab.right):
            pane.activated.connect(
                lambda p=pane, t=tab: self._activate_pane(t, p)
            )
            pane.path_changed.connect(
                lambda path, p=pane, t=tab: self._on_path_changed(t, p, path)
            )
            pane.selection_changed.connect(
                lambda paths, p=pane, t=tab: self._on_selection(t, p, paths)
            )
            pane.context_requested.connect(
                lambda paths, pos, p=pane, t=tab:
                self._show_context_menu(t, p, paths, pos)
            )
            pane.files_dropped.connect(
                lambda paths, target, modifiers, p=pane, t=tab:
                self._on_files_dropped(t, p, paths, target, modifiers)
            )
            pane.copy_requested.connect(
                lambda p=pane, t=tab: self._copy_selection(t, p)
            )
            pane.cut_requested.connect(
                lambda p=pane, t=tab: self._cut_selection(t, p)
            )
            pane.paste_requested.connect(
                lambda p=pane, t=tab: self._paste(t, p)
            )
            pane.delete_requested.connect(
                lambda p=pane, t=tab: self._trash_selection(t, p)
            )
            pane.rename_requested.connect(
                lambda p=pane, t=tab: self._rename_selection(t, p)
            )
            pane.new_folder_requested.connect(
                lambda p=pane, t=tab: self._new_folder(t, p)
            )
            pane.refresh_requested.connect(self._refresh_current_panes)
            pane.preview_requested.connect(
                lambda: self.preview_check.setChecked(
                    not self.preview_check.isChecked()
                )
            )
            pane.status_message.connect(self.status)

    def _activate_pane(self, tab, pane):
        tab.active_pane = pane
        if self.tabs.currentWidget() is tab:
            self.dual_check.blockSignals(True)
            self.dual_check.setChecked(tab.dual)
            self.dual_check.blockSignals(False)
            self._queue_preview(tab, pane, pane.selected_paths())

    def _on_path_changed(self, tab, pane, path):
        self._update_tab_title(tab)
        if path:
            self.settings.remember_path("browser_folder", path)
        if self.tabs.currentWidget() is tab and tab.active_pane is pane:
            self._queue_preview(tab, pane, [])

    def _update_tab_title(self, tab):
        index = self.tabs.indexOf(tab)
        if index >= 0:
            self.tabs.setTabText(index, tab.label())

    def _on_tab_changed(self, index):
        tab = self.tabs.widget(index)
        if tab is None:
            return
        self.dual_check.blockSignals(True)
        self.dual_check.setChecked(tab.dual)
        self.dual_check.blockSignals(False)
        self._update_preview_now()

    def _close_current_tab(self):
        self._close_tab(self.tabs.currentIndex())

    def _tab_state(self, tab):
        return {
            "left": tab.left.current_path,
            "right": tab.right.current_path,
            "active": "right" if tab.active_pane is tab.right else "left",
            "dual": tab.dual,
        }

    def _close_tab(self, index):
        if index < 0:
            return
        tab = self.tabs.widget(index)
        if tab is not None and not self._restoring:
            self._closed_tabs.append(self._tab_state(tab))
            self._closed_tabs = self._closed_tabs[-10:]
        self.tabs.removeTab(index)
        if tab is not None:
            tab.deleteLater()
        if self.tabs.count() == 0:
            self._new_tab()
        self._save_state()

    def _restore_closed_tab(self):
        if not self._closed_tabs:
            return
        state = self._closed_tabs.pop()
        tab = self._new_tab(
            state.get("left"), state.get("right"), activate=True
        )
        tab.set_dual(bool(state.get("dual", True)))
        if state.get("active") == "right" and tab.dual:
            tab.active_pane = tab.right
        self._update_tab_title(tab)
        self._save_state()

    def _duplicate_tab(self, index):
        tab = self.tabs.widget(index)
        if tab is None:
            return
        state = self._tab_state(tab)
        new_tab = self._new_tab(
            state.get("left"), state.get("right"), activate=True
        )
        new_tab.set_dual(state.get("dual", True))
        if state.get("active") == "right" and new_tab.dual:
            new_tab.active_pane = new_tab.right
        self._update_tab_title(new_tab)

    def _close_other_tabs(self, keep_index):
        for index in reversed(range(self.tabs.count())):
            if index != keep_index:
                self._close_tab(index)
                if index < keep_index:
                    keep_index -= 1
        self.tabs.setCurrentIndex(keep_index)

    def _tab_context_menu(self, position):
        index = self.tabs.tabBar().tabAt(position)
        if index < 0:
            return
        menu = QMenu(self)
        duplicate = menu.addAction(tr("複製分頁"))
        duplicate.triggered.connect(lambda: self._duplicate_tab(index))
        close = menu.addAction(tr("關閉分頁"))
        close.triggered.connect(lambda: self._close_tab(index))
        close_others = menu.addAction(tr("關閉其他分頁"))
        close_others.triggered.connect(lambda: self._close_other_tabs(index))
        menu.exec(self.tabs.tabBar().mapToGlobal(position))

    def _set_column_visible(self, column, visible):
        self._columns[column] = bool(visible)
        self.settings.set_value("browser/columns", self._columns)
        for index in range(self.tabs.count()):
            tab = self.tabs.widget(index)
            target = 2 if column == "type" else 3
            tab.left.set_column_visible(target, visible)
            tab.right.set_column_visible(target, visible)

    def _toggle_dual(self, enabled):
        tab = self.tabs.currentWidget()
        if tab is not None:
            tab.set_dual(enabled)
        self.settings.set_option("browser_dual", bool(enabled))
        self._save_state()

    def _toggle_hidden(self, enabled):
        self.show_hidden = bool(enabled)
        self.settings.set_option("browser_show_hidden", self.show_hidden)
        self.model.setFilter(self._filter_flags())
        for index in range(self.tabs.count()):
            self._reload_tab_paths(self.tabs.widget(index))

    def _reload_tab_paths(self, tab):
        active = tab.active_pane
        left = self._valid_path(tab.left.current_path)
        right = self._valid_path(tab.right.current_path)
        tab.left.navigate(left, add_history=False)
        if tab.dual:
            tab.right.navigate(right, add_history=False)
        tab.active_pane = active
        self._update_tab_title(tab)

    def _valid_path(self, path):
        path = normalize_path(path)
        if not path or is_dir_path(path):
            return path
        candidate = path
        while candidate:
            parent = os.path.dirname(candidate.rstrip("\\/"))
            if not parent or parent == candidate:
                break
            candidate = normalize_path(parent)
            if is_dir_path(candidate):
                return candidate
        return self._home_path()

    def _toggle_preview(self, enabled):
        self.preview.setVisible(enabled)
        for index in range(self.tabs.count()):
            tab = self.tabs.widget(index)
            tab.left.set_compact(enabled)
            tab.right.set_compact(enabled)
        if enabled:
            self._update_preview_now()

    def _toggle_icons(self, enabled):
        enabled = bool(enabled)
        self.settings.set_option("browser_icons", enabled)
        self._icon_provider.set_thumbnails_enabled(enabled)
        if enabled:
            # Ask the model to re-query icons now that thumbnails are enabled.
            self.model.setIconProvider(self._icon_provider)
        for index in range(self.tabs.count()):
            tab = self.tabs.widget(index)
            tab.left.set_thumbnail_mode(enabled)
            tab.right.set_thumbnail_mode(enabled)
        self._save_state()

    def _restore_state(self):
        raw = self.settings.value("browser/state", "")
        state = None
        if isinstance(raw, str) and raw:
            try:
                state = json.loads(raw)
            except Exception:
                state = None
        if not isinstance(state, dict) or not state.get("tabs"):
            tab = self._new_tab()
            tab.set_dual(self.settings.option("browser_dual", True))
            if self.settings.option("browser_preview_default", False):
                self.preview_check.setChecked(True)
            return

        if state.get("preview"):
            self.preview_check.setChecked(True)
        home = self._home_path()
        for item in state.get("tabs", []):
            if not isinstance(item, dict):
                continue
            left = normalize_path(item.get("left"))
            right = normalize_path(item.get("right"))
            if left and not is_dir_path(left):
                left = home
            if right and not is_dir_path(right):
                right = left if left is not None else home
            tab = self._new_tab(left, right, activate=False)
            tab.set_dual(bool(item.get("dual", True)))
            if item.get("active") == "right" and tab.dual:
                tab.active_pane = tab.right
            self._update_tab_title(tab)
        if self.tabs.count() == 0:
            self._new_tab()
            return
        try:
            self.tabs.setCurrentIndex(int(state.get("current", 0)))
        except Exception:
            self.tabs.setCurrentIndex(0)

    def _save_state(self):
        if self._restoring:
            return
        tabs = []
        for index in range(self.tabs.count()):
            tabs.append(self._tab_state(self.tabs.widget(index)))
        state = {
            "tabs": tabs,
            "current": max(0, self.tabs.currentIndex()),
            "preview": self.preview.isVisible(),
        }
        self.settings.set_value(
            "browser/state", json.dumps(state, ensure_ascii=False)
        )

    # ------------------------------------------------------------------
    # Favourites
    # ------------------------------------------------------------------
    def _refresh_favorites_menu(self):
        self.fav_menu.clear()
        groups = grouped_favorites(self.settings)
        if groups:
            for group_name, paths in groups:
                submenu = self.fav_menu.addMenu(group_name)
                submenu.setIcon(get_icon(
                    "folder-open", self.theme(),
                    icon_color(self.theme(), "text"), 15,
                ))
                for path in paths:
                    name = path_name(path) or path
                    action = submenu.addAction(name)
                    action.setToolTip(path)
                    action.triggered.connect(
                        lambda _=False, target=path:
                        self._navigate_active(target)
                    )
        else:
            empty = self.fav_menu.addAction(tr("尚無最愛資料夾"))
            empty.setEnabled(False)
        self.fav_menu.addSeparator()
        add_action = self.fav_menu.addAction(tr("加入目前資料夾"))
        add_action.triggered.connect(self._add_current_favorite)
        group_action = self.fav_menu.addAction(tr("設定目前資料夾群組"))
        group_action.triggered.connect(self._set_current_favorite_group)

    def _add_current_favorite(self):
        pane = self._active_pane()
        if pane is None:
            return
        path = normalize_path(pane.current_path)
        if not path or not is_dir_path(path):
            self.status("目前位置是本機磁碟清單，請先進入資料夾")
            return
        changed = add_favorite(self.settings, path)
        self.status("已加入我的最愛" if changed else "此資料夾已在最愛中")
        self._refresh_favorites_menu()

    def _set_current_favorite_group(self):
        pane = self._active_pane()
        if pane is None:
            return
        path = normalize_path(pane.current_path)
        if not path or not is_dir_path(path):
            self.status("目前位置是本機磁碟清單，請先進入資料夾")
            return
        add_favorite(self.settings, path)
        current = favorite_group(self.settings, path)
        name, ok = QInputDialog.getText(
            self, "我的最愛群組", "群組名稱：", text=current
        )
        if not ok or not name.strip():
            return
        set_favorite_group(self.settings, path, name)
        self._refresh_favorites_menu()
        self.status(f"已將資料夾加入「{name.strip()}」群組")

    def _navigate_active(self, path):
        pane = self._active_pane()
        if pane is not None:
            pane.navigate(path)

    def _refresh_drive_menu(self):
        menu = self.drive_menu
        menu.clear()
        all_action = menu.addAction(tr("所有磁碟"))
        all_action.triggered.connect(lambda: self._navigate_active(""))

        from app.core.drives import list_drive_entries

        raw = self.settings.value("network_roots", [])
        if isinstance(raw, str):
            raw = [raw]
        if not isinstance(raw, (list, tuple)):
            raw = []
        extras = [normalize_path(item) for item in raw if item]
        try:
            entries = list_drive_entries(extras)
        except Exception:
            entries = []
        local = [entry for entry in entries if not entry.get("is_network")]
        network = [entry for entry in entries if entry.get("is_network")]

        def fill(submenu, items, show_unc=False):
            for entry in items:
                label = entry.get("display_name") or entry.get("root", "")
                if show_unc and entry.get("unc"):
                    label = f"{label} · {entry['unc']}"
                action = submenu.addAction(label)
                action.setToolTip(
                    f"{entry.get('root', '')}\n{entry.get('unc', '')}\n"
                    f"{entry.get('filesystem', '')}"
                )
                action.triggered.connect(
                    lambda _=False, path=entry.get("root", ""):
                    self._navigate_active(path)
                )

        if local:
            fill(menu.addMenu(tr("本機磁碟")), local)
        if network:
            fill(menu.addMenu(tr("網路磁碟")), network, show_unc=True)
        menu.addSeparator()
        browse_action = menu.addAction(tr("瀏覽網路共享..."))
        browse_action.triggered.connect(self._browse_network_shares)
        unc_action = menu.addAction(tr("輸入 UNC 路徑..."))
        unc_action.triggered.connect(self._enter_unc_path)

    def _choose_network_folder(self, initial=""):
        from app.ui.network_dialog import NetworkLocationDialog

        dialog = NetworkLocationDialog(self, initial=initial)
        if dialog.exec():
            return dialog.selected_path
        return ""

    def _browse_network_shares(self):
        pane = self._active_pane()
        initial = ""
        if pane is not None and is_unc_path(pane.current_path):
            initial = pane.current_path
        path = self._choose_network_folder(initial)
        if path:
            self._navigate_active(path)

    def _enter_unc_path(self):
        pane = self._active_pane()
        initial = ""
        if pane is not None and is_unc_path(pane.current_path):
            initial = pane.current_path
        path, ok = QInputDialog.getText(
            self, "UNC 網路路徑", "路徑（\\\\伺服器\\共享）：", text=initial
        )
        if not ok or not path.strip():
            return
        path = normalize_path(path)
        if is_unc_server_root(path):
            self._navigate_active(path)
            return
        if is_unc_path(path):
            from app.core.drives import ensure_network_share, unc_share_root

            connected, _error = ensure_network_share(
                unc_share_root(path) or path
            )
            if not connected:
                chosen = self._choose_network_folder(path)
                if chosen:
                    self._navigate_active(chosen)
                return
        self._navigate_active(path)

    # ------------------------------------------------------------------
    # Preview / active pane helpers
    # ------------------------------------------------------------------
    def _active_tab(self):
        tab = self.tabs.currentWidget()
        return tab if isinstance(tab, BrowserTab) else None

    def _active_pane(self):
        tab = self._active_tab()
        return tab.active_pane if tab else None

    def _on_selection(self, tab, pane, paths):
        if tab.active_pane is not pane:
            tab.active_pane = pane
            self._update_tab_title(tab)
        if paths:
            self.status(f"已選取 {len(paths)} 個項目")
        if self.tabs.currentWidget() is tab:
            self._queue_preview(tab, pane, paths)

    def _queue_preview(self, tab, pane, paths):
        self._pending_preview = (tab, pane, paths)
        self._preview_timer.start()

    def _apply_preview(self):
        if not self.preview.isVisible() or self._pending_preview is None:
            return
        tab, pane, paths = self._pending_preview
        self._pending_preview = None
        if self.tabs.currentWidget() is tab and tab.active_pane is pane:
            self.preview.show_paths(paths)

    def _update_preview_now(self):
        if not self.preview.isVisible():
            return
        tab = self._active_tab()
        if tab is None:
            self.preview.clear()
            return
        self.preview.show_paths(tab.active_pane.selected_paths())

    # ------------------------------------------------------------------
    # File operations
    # ------------------------------------------------------------------
    def _selected_or_info(self, pane):
        paths = pane.selected_paths()
        if not paths:
            self.status("請先選取檔案或資料夾")
        return paths

    def _copy_selection(self, tab, pane):
        paths = self._selected_or_info(pane)
        if paths:
            self.clipboard = {"mode": "copy", "paths": paths}
            self.status(f"已複製 {len(paths)} 個項目到剪貼簿")

    def _cut_selection(self, tab, pane):
        paths = self._selected_or_info(pane)
        if paths:
            self.clipboard = {"mode": "move", "paths": paths}
            self.status(f"已剪下 {len(paths)} 個項目")

    def _paste(self, tab, pane):
        paths = self.clipboard.get("paths") or []
        if not paths:
            self.status("剪貼簿是空的")
            return
        dest = pane.current_path or self._home_path()
        if not dest or not os.path.isdir(extended_path(dest)):
            self.status("目前位置不是有效資料夾")
            return
        self._execute_operation(self.clipboard["mode"], paths, dest)

    def _copy_to_other(self, tab, pane):
        paths = self._selected_or_info(pane)
        if not paths:
            return
        dest = self._other_pane_path(tab, pane)
        if dest:
            self._execute_operation("copy", paths, dest)

    def _move_to_other(self, tab, pane):
        paths = self._selected_or_info(pane)
        if not paths:
            return
        dest = self._other_pane_path(tab, pane)
        if dest:
            self._execute_operation("move", paths, dest)

    def _other_pane_path(self, tab, pane):
        other = tab.right if pane is tab.left else tab.left
        path = normalize_path(other.current_path)
        if tab.dual and path and os.path.isdir(extended_path(path)):
            return path
        path = QFileDialog.getExistingDirectory(self, "選擇目標資料夾")
        return normalize_path(path) or None

    def _execute_operation(self, operation, sources, dest, verify=None):
        if verify is None:
            verify = self.settings.option("verify_copy", True)
        sources = [normalize_path(path) for path in (sources or [])]
        dest = normalize_path(dest)
        if not sources or not dest:
            return
        if not os.path.isdir(extended_path(dest)):
            QMessageBox.warning(self, "目標錯誤", "目標資料夾不存在。")
            return
        if any(self._is_drive_root(path) for path in sources):
            QMessageBox.warning(
                self, "無法操作", "不能直接複製或搬移磁碟根目錄。"
            )
            return
        conflict = "skip"
        if self._has_destination_conflict(sources, dest):
            conflict = self._ask_conflict()
            if conflict is None:
                return
        verify_mode = self.settings.option(
            "copy_verify_mode", "quick" if verify else "off"
        )
        retries = int(self.settings.option("copy_retries", 1) or 0)
        threads = int(self.settings.option("copy_threads", 4) or 4)
        dialog = OperationDialog(
            self, operation, sources, dest, conflict=conflict,
            verify=verify, verify_mode=verify_mode, retries=retries,
            threads=threads,
        )
        dialog.completed.connect(self._on_operation_completed)
        dialog.worker.progress.connect(self._on_operation_progress)
        dialog.worker.failed.connect(self._on_operation_failed)
        dialog.finished.connect(lambda: setattr(self, "_operation_dialog", None))
        dialog.finished.connect(dialog.deleteLater)
        self._operation_dialog = dialog
        self._op_task = self.task_add(
            "copy" if operation == "copy" else "move",
            f"{'複製' if operation == 'copy' else '搬移'} "
            f"{len(sources)} 個項目",
            control=dialog.control, total=len(sources),
            message=dest,
        )
        dialog.show()
        dialog.start()
        self.status(
            f"{'複製' if operation == 'copy' else '搬移'} "
            f"{len(sources)} 個項目..."
        )

    @staticmethod
    def _is_drive_root(path):
        path = str(path).rstrip("\\/")
        return len(path) == 2 and path[1] == ":"

    @staticmethod
    def _has_destination_conflict(sources, dest):
        for source in sources:
            name = os.path.basename(str(source).rstrip("\\/"))
            if name and os.path.exists(os.path.join(dest, name)):
                return True
        return False

    def _ask_conflict(self):
        box = QMessageBox(self)
        box.setWindowTitle("名稱衝突")
        box.setText("目標資料夾已有同名檔案，要如何處理？")
        skip = box.addButton("跳過", QMessageBox.ButtonRole.RejectRole)
        overwrite = box.addButton("覆寫", QMessageBox.ButtonRole.DestructiveRole)
        rename = box.addButton("自動重新命名", QMessageBox.ButtonRole.AcceptRole)
        default = self.settings.option("default_conflict", "rename")
        default_button = {
            "skip": skip, "overwrite": overwrite, "rename": rename,
        }.get(default, rename)
        box.setDefaultButton(default_button)
        box.exec()
        clicked = box.clickedButton()
        if clicked is None:
            return None
        role = box.buttonRole(clicked)
        if role == QMessageBox.ButtonRole.RejectRole:
            return "skip"
        if role == QMessageBox.ButtonRole.DestructiveRole:
            return "overwrite"
        if role == QMessageBox.ButtonRole.AcceptRole:
            return "rename"
        return None

    def _on_operation_progress(self, done, total, moved, total_bytes, current):
        self.task_update(self._op_task, done=done, total=total,
                         message=short_path(current, 60))

    def _on_operation_failed(self, message):
        self.task_finish(self._op_task, status="failed", error=message)
        self._op_task = None

    def _on_operation_completed(self, summary):
        if summary is None:
            return
        verb = "複製" if summary.get("operation") == "copy" else "搬移"
        message = (
            f"{verb}完成：成功 {summary['done']} · 跳過 {summary['skipped']}"
            f" · 失敗 {summary['failed']}"
        )
        if summary.get("cancelled"):
            self.task_finish(self._op_task, status="cancelled", message=message)
        else:
            self.task_finish(self._op_task, message=message)
        self._op_task = None
        self.status(message)
        try:
            record_operation(
                self.settings, MODULE_BROWSER, self._active_pane().current_path
                if self._active_pane() else "",
                f"{verb} {summary['done']} 個項目",
                summary["done"], summary["failed"],
            )
        except Exception:
            pass
        if summary.get("operation") == "move" and self.clipboard.get("mode") == "move":
            self.clipboard = {"mode": "", "paths": []}
        self._refresh_current_panes()

    def _trash_selection(self, tab, pane):
        paths = self._selected_or_info(pane)
        if not paths:
            return
        paths = [path for path in paths if not self._is_drive_root(path)]
        if not paths:
            QMessageBox.information(
                self, "無法刪除", "不能將磁碟根目錄移至資源回收筒。"
            )
            return
        answer = QMessageBox.question(
            self,
            "移至資源回收筒",
            f"要將 {len(paths)} 個項目移至資源回收筒嗎？\n"
            "之後可以從 Windows 資源回收筒還原。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._trash_worker = TrashWorker(paths, OperationControl())
        self._trash_worker.completed.connect(self._on_trash_completed)
        self._task = self.task_add(
            "trash", f"刪除 {len(paths)} 個項目",
            control=self._trash_worker.control, total=len(paths),
        )
        self._trash_worker.progress.connect(
            lambda done, total: self.task_update(
                self._task, done=done, total=total
            )
        )
        self._trash_worker.start()
        self.status(f"正在將 {len(paths)} 個項目移至資源回收筒...")

    def _on_trash_completed(self, deleted, failed):
        folder = self._active_pane().current_path if self._active_pane() else ""
        self.task_finish(
            self._task,
            status="done" if not failed else "failed",
            message=f"刪除 {len(deleted)} · 失敗 {len(failed)}",
        )
        self._task = None
        try:
            record_operation(
                self.settings, MODULE_BROWSER, folder,
                f"刪除 {len(deleted)} 個項目至資源回收筒",
                len(deleted), len(failed),
            )
        except Exception:
            pass
        if failed:
            details = "\n".join(
                f"{short_path(path, 50)}：{error}" for path, error in failed[:10]
            )
            QMessageBox.warning(
                self, "部分項目刪除失敗",
                f"已刪除 {len(deleted)} 個，失敗 {len(failed)} 個。\n\n{details}",
            )
        else:
            self.status(f"已移至資源回收筒：{len(deleted)} 個項目")
        self._refresh_current_panes()

    def _rename_selection(self, tab, pane):
        paths = self._selected_or_info(pane)
        if len(paths) != 1:
            if paths:
                self.status("重新命名一次只能選取一個項目")
            return
        path = paths[0]
        current_name = os.path.basename(path.rstrip("\\/"))
        new_name, ok = QInputDialog.getText(
            self, "重新命名", "新名稱：", text=current_name
        )
        if not ok or not new_name.strip():
            return
        new_name = new_name.strip()
        if any(char in new_name for char in '\\/:*?"<>|'):
            QMessageBox.warning(self, "名稱無效", "名稱含有 Windows 不允許的字元。")
            return
        new_path = os.path.join(os.path.dirname(path), new_name)
        if os.path.exists(new_path):
            QMessageBox.warning(self, "名稱衝突", "同名檔案或資料夾已存在。")
            return
        try:
            os.rename(path, new_path)
            self.status(f"已重新命名為 {new_name}")
            self._refresh_current_panes()
        except OSError as exc:
            QMessageBox.warning(self, "重新命名失敗", str(exc))

    def _new_folder(self, tab, pane):
        folder = pane.current_path or self._home_path()
        if not folder or not os.path.isdir(extended_path(folder)):
            self.status("目前位置不是有效資料夾")
            return
        name, ok = QInputDialog.getText(self, "新增資料夾", "資料夾名稱：")
        if not ok or not name.strip():
            return
        name = name.strip()
        if any(char in name for char in '\\/:*?"<>|'):
            QMessageBox.warning(self, "名稱無效", "名稱含有 Windows 不允許的字元。")
            return
        target = os.path.join(folder, name)
        try:
            os.mkdir(target)
            self.status(f"已新增資料夾 {name}")
            self._refresh_current_panes()
        except OSError as exc:
            QMessageBox.warning(self, "新增資料夾失敗", str(exc))

    def _on_files_dropped(self, tab, pane, paths, target, modifiers):
        target = target or pane.current_path
        if not target or not os.path.isdir(extended_path(target)):
            self.status("請拖放到有效的資料夾")
            return
        menu = QMenu(self)
        copy_action = menu.addAction(tr("複製到此處"))
        move_action = menu.addAction(tr("搬移到此處"))
        menu.addSeparator()
        menu.addAction(tr("取消"))
        chosen = menu.exec(QCursor.pos())
        if chosen is copy_action:
            self._execute_operation("copy", paths, target)
        elif chosen is move_action:
            self._execute_operation("move", paths, target)

    # ------------------------------------------------------------------
    # Context menu
    # ------------------------------------------------------------------
    def _show_context_menu(self, tab, pane, paths, global_pos):
        menu = QMenu(self)
        if paths:
            open_action = menu.addAction(tr("開啟"))
            open_action.triggered.connect(lambda: self._open_paths(paths))
            reveal_action = menu.addAction(tr("在檔案總管中顯示"))
            reveal_action.triggered.connect(lambda: self._reveal_paths(paths))
            hash_action = menu.addAction(tr("計算雜湊"))
            hash_action.triggered.connect(
                lambda _=False, selected=paths: self._send_files_to_hash(selected)
            )
            if len(paths) == 1 and is_dir_path(paths[0]):
                new_tab_action = menu.addAction(tr("以新分頁開啟"))
                new_tab_action.triggered.connect(
                    lambda _=False, target=paths[0]:
                    self._new_tab(target, target, activate=True)
                )
            if len(paths) == 1:
                copy_path_action = menu.addAction(tr("複製路徑"))
                copy_path_action.triggered.connect(
                    lambda: self._copy_path_text(paths[0])
                )
            menu.addSeparator()
            copy_action = menu.addAction(tr("複製"))
            copy_action.triggered.connect(lambda: self._copy_selection(tab, pane))
            cut_action = menu.addAction(tr("剪下"))
            cut_action.triggered.connect(lambda: self._cut_selection(tab, pane))
        paste_action = menu.addAction(tr("貼上"))
        paste_action.setEnabled(bool(self.clipboard.get("paths")))
        paste_action.triggered.connect(lambda: self._paste(tab, pane))
        menu.addSeparator()
        if paths:
            copy_other = menu.addAction(tr("複製到另一窗格"))
            copy_other.triggered.connect(lambda: self._copy_to_other(tab, pane))
            move_other = menu.addAction(tr("搬移到另一窗格"))
            move_other.triggered.connect(lambda: self._move_to_other(tab, pane))
            menu.addSeparator()
            if len(paths) == 1:
                rename_action = menu.addAction(tr("重新命名 (F2)"))
                rename_action.triggered.connect(
                    lambda: self._rename_selection(tab, pane)
                )
                properties_action = menu.addAction(tr("內容"))
                properties_action.triggered.connect(
                    lambda: self._show_properties(paths[0])
                )
            delete_action = menu.addAction(tr("移至資源回收筒 (Del)"))
            delete_action.triggered.connect(
                lambda: self._trash_selection(tab, pane)
            )
        new_folder_action = menu.addAction(tr("新增資料夾 (Ctrl+Shift+N)"))
        new_folder_action.triggered.connect(lambda: self._new_folder(tab, pane))
        menu.addSeparator()
        send_menu = menu.addMenu(tr("以此資料夾開啟"))
        folder = pane.current_path
        for label, module_id, autostart in (
            ("重複檔案掃描", MODULE_DUPLICATES, True),
            ("批量複製 / 搬移", MODULE_COPY, False),
            ("批次改名", MODULE_RENAME, False),
            ("批量刪除", MODULE_REMOVE, False),
        ):
            action = send_menu.addAction(tr(label))
            action.triggered.connect(
                lambda _=False, mid=module_id, auto=autostart, path=folder:
                self._send_folder(mid, path, auto)
            )
        menu.exec(global_pos)

    def _open_paths(self, paths):
        if not paths:
            return
        ok, error = open_path(paths[0])
        if not ok:
            QMessageBox.warning(self, "無法開啟", error)

    def _reveal_paths(self, paths):
        if not paths:
            return
        ok, error = reveal_in_explorer(paths[0])
        if not ok:
            QMessageBox.warning(self, "無法顯示", error)

    def _copy_path_text(self, path):
        from PyQt6.QtWidgets import QApplication

        QApplication.clipboard().setText(normalize_path(path))
        self.status("已複製路徑")

    def _show_properties(self, path):
        path = normalize_path(path)
        try:
            stat = os.stat(path)
        except OSError as exc:
            QMessageBox.warning(self, "無法讀取內容", str(exc))
            return
        is_dir = os.path.isdir(extended_path(path))
        kind = tr("資料夾") if is_dir else tr("檔案")
        size = "—" if is_dir else format_size(stat.st_size)
        created = format_datetime(getattr(stat, "st_ctime", 0))
        modified = format_datetime(stat.st_mtime)
        QMessageBox.information(
            self,
            tr("內容"),
            f"{path}\n\n{tr('類型：')}{kind}\n{tr('大小：')}{size}\n"
            f"{tr('建立時間：')}{created}\n{tr('修改時間：')}{modified}",
        )

    def _send_folder(self, module_id, folder, autostart=False):
        folder = normalize_path(folder)
        if is_unc_server_root(folder):
            folder = self._choose_network_folder(folder)
        if (folder and is_unc_path(folder)
                and not os.path.isdir(extended_path(folder))):
            from app.core.drives import ensure_network_share, unc_share_root

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
            return
        if self.main_window:
            self.main_window.goto_module(
                module_id, {"folder": folder, "autostart": autostart}
            )

    def _send_files_to_hash(self, paths):
        if not paths or self.main_window is None:
            return
        self.main_window.goto_module(MODULE_HASH, {"files": paths})

    def _refresh_current_panes(self):
        tab = self._active_tab()
        if tab is None:
            return
        self._reload_tab_paths(tab)
        self._update_preview_now()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def apply_payload(self, payload):
        if not isinstance(payload, dict):
            return
        folder = normalize_path(payload.get("folder"))
        if not folder or not is_dir_path(folder):
            return
        if self.tabs.count() == 0:
            self._new_tab(folder)
            return
        self._navigate_active(folder)

    def on_show(self):
        self._refresh_favorites_menu()
        if self.preview.isVisible():
            self._update_preview_now()

    def on_theme_changed(self):
        self.page_header.set_theme(self.theme())

    def on_settings_changed(self):
        self.preview.max_image_bytes = int(
            self.settings.option("preview_max_mb", 20) * 1024 * 1024
        )
        hidden = self.settings.option("browser_show_hidden", False)
        if hidden != self.hidden_check.isChecked():
            self.hidden_check.setChecked(hidden)
        icons = self.settings.option("browser_icons", False)
        if icons != self.icons_check.isChecked():
            self.icons_check.setChecked(icons)

    def request_stop(self):
        self._save_state()
        if self._operation_dialog is not None:
            self._operation_dialog.request_stop()
        if self._trash_worker is not None and self._trash_worker.isRunning():
            self._trash_worker.cancel()
            self._trash_worker.wait(3000)
