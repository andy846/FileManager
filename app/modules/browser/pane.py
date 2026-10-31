"""Single browser pane: navigation, filtering and file listing."""

import os
import stat

from PyQt6.QtCore import (
    QItemSelectionModel, QMimeData, QModelIndex, QSize, QSortFilterProxyModel,
    Qt, QTimer, QUrl, pyqtSignal,
)
from PyQt6.QtGui import QAction, QDrag, QKeySequence
from PyQt6.QtWidgets import (
    QAbstractItemView, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QListView, QPushButton, QStackedWidget, QTreeView, QVBoxLayout, QWidget,
)

from app.core.i18n import tr
from app.core.utils import format_size, normalize_path, open_path
from app.ui.path_utils import is_dir_path


class FileTreeView(QTreeView):
    """QTreeView that reports URL drops instead of letting the model handle them."""

    urls_dropped = pyqtSignal(list, str, object)  # paths, target dir, modifiers

    def __init__(self, parent=None):
        super().__init__(parent)
        self.source_model = None
        self.proxy_model = None
        self.path_for_index = None
        self.current_dir = ""
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.CopyAction)

    def _source_index(self, index):
        if not index.isValid() or self.proxy_model is None:
            return QModelIndex()
        return self.proxy_model.mapToSource(index)

    def _target_dir(self, position):
        index = self.indexAt(position)
        source = self._source_index(index)
        if source.isValid() and self.source_model is not None:
            if self.source_model.isDir(source):
                return normalize_path(self.source_model.filePath(source))
        return self.current_dir

    def dragEnterEvent(self, event):  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event):  # noqa: N802
        if not event.mimeData().hasUrls():
            return
        paths = [
            url.toLocalFile() for url in event.mimeData().urls()
            if url.isLocalFile()
        ]
        if not paths:
            return
        target = self._target_dir(event.position().toPoint())
        self.urls_dropped.emit(paths, target, event.modifiers())
        event.acceptProposedAction()

    def startDrag(self, supported_actions):  # noqa: N802
        indexes = self.selectionModel().selectedRows(0)
        if not indexes:
            return
        paths = []
        for index in indexes:
            source = self._source_index(index)
            if source.isValid() and self.source_model is not None:
                paths.append(normalize_path(
                    self.source_model.filePath(source)
                ))
        if not paths:
            return
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(path) for path in paths])
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.CopyAction)


class BrowserProxy(QSortFilterProxyModel):
    """Proxy model with Traditional Chinese column headers."""

    HEADERS = ["名稱", "大小", "類型", "修改時間"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._root_source = QModelIndex()

    def set_root_source(self, index):
        self._root_source = index
        self.invalidateFilter()

    def filterAcceptsRow(self, source_row, source_parent):
        if not self.filterRegularExpression().pattern():
            return True
        # Keep the current folder itself visible; otherwise typing a filter
        # would also filter out the view's root index and show an empty pane.
        if self._root_source.isValid() and self.sourceModel() is not None:
            current = self.sourceModel().index(
                source_row, 0, source_parent
            )
            if current == self._root_source:
                return True
            parent = self._root_source.parent()
            while parent.isValid():
                if (parent.row() == source_row
                        and parent.parent() == source_parent):
                    return True
                parent = parent.parent()
        return super().filterAcceptsRow(source_row, source_parent)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if (orientation == Qt.Orientation.Horizontal
                and role == Qt.ItemDataRole.DisplayRole
                and 0 <= section < len(self.HEADERS)):
            return tr(self.HEADERS[section])
        return super().headerData(section, orientation, role)


class BrowserPane(QWidget):
    """One side of a dual-pane browser."""

    activated = pyqtSignal()
    path_changed = pyqtSignal(str)
    selection_changed = pyqtSignal(list)
    context_requested = pyqtSignal(list, object)
    files_dropped = pyqtSignal(list, str, object)
    copy_requested = pyqtSignal()
    cut_requested = pyqtSignal()
    paste_requested = pyqtSignal()
    delete_requested = pyqtSignal()
    rename_requested = pyqtSignal()
    new_folder_requested = pyqtSignal()
    refresh_requested = pyqtSignal()
    preview_requested = pyqtSignal()
    status_message = pyqtSignal(str)

    def __init__(self, model, parent=None):
        super().__init__(parent)
        self.model = model
        self.proxy = BrowserProxy(self)
        self.proxy.setSourceModel(model)
        self.proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.proxy.setFilterKeyColumn(0)
        self.proxy.setRecursiveFilteringEnabled(False)
        self.proxy.setDynamicSortFilter(True)

        self._history = []
        self._history_index = -1
        self.current_path = ""
        self.compact = False
        self.show_type = True
        self.show_date = True
        self._footer_timer = QTimer(self)
        self._footer_timer.setSingleShot(True)
        self._footer_timer.setInterval(120)
        self._footer_timer.timeout.connect(self._update_footer)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        nav = QHBoxLayout()
        nav.setSpacing(4)
        self.back_btn = QPushButton()
        self.back_btn.setFixedWidth(32)
        self.back_btn.setToolTip("上一頁")
        self.back_btn.setAccessibleName("上一頁")
        self.forward_btn = QPushButton()
        self.forward_btn.setFixedWidth(32)
        self.forward_btn.setToolTip("下一頁")
        self.forward_btn.setAccessibleName("下一頁")
        self.up_btn = QPushButton()
        self.up_btn.setFixedWidth(32)
        self.up_btn.setToolTip("上一層")
        self.up_btn.setAccessibleName("上一層")
        self.back_btn.setIcon(self.style().standardIcon(
            self.style().StandardPixmap.SP_ArrowBack
        ))
        self.forward_btn.setIcon(self.style().standardIcon(
            self.style().StandardPixmap.SP_ArrowForward
        ))
        self.up_btn.setIcon(self.style().standardIcon(
            self.style().StandardPixmap.SP_ArrowUp
        ))
        nav.addWidget(self.back_btn)
        nav.addWidget(self.forward_btn)
        nav.addWidget(self.up_btn)

        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText(
            "路徑（可輸入 \\\\伺服器\\共享 或 \\\\伺服器）"
        )
        nav.addWidget(self.path_edit, 1)

        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("篩選")
        self.filter_edit.setFixedWidth(120)
        nav.addWidget(self.filter_edit)

        self.refresh_btn = QPushButton()
        self.refresh_btn.setFixedWidth(32)
        self.refresh_btn.setToolTip("重新整理 (F5)")
        self.refresh_btn.setAccessibleName("重新整理")
        self.refresh_btn.setIcon(self.style().standardIcon(
            self.style().StandardPixmap.SP_BrowserReload
        ))
        nav.addWidget(self.refresh_btn)
        layout.addLayout(nav)

        self.view = FileTreeView()
        self.view.setModel(self.proxy)
        self.view.source_model = self.model
        self.view.proxy_model = self.proxy
        self.view.path_for_index = self._path_for_index
        self.view.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self.view.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.view.setAlternatingRowColors(True)
        self.view.setRootIsDecorated(False)
        self.view.setUniformRowHeights(True)
        self.view.setAllColumnsShowFocus(True)
        self.view.setExpandsOnDoubleClick(False)
        self.view.setSortingEnabled(True)
        self.view.sortByColumn(0, Qt.SortOrder.AscendingOrder)
        self.view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        header = self.view.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column, width in ((1, 90), (2, 110), (3, 150)):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Interactive)
            self.view.setColumnWidth(column, width)

        self.icon_view = QListView()
        self.icon_view.setModel(self.proxy)
        self.icon_view.setViewMode(QListView.ViewMode.IconMode)
        self.icon_view.setIconSize(QSize(96, 96))
        self.icon_view.setGridSize(QSize(118, 128))
        self.icon_view.setResizeMode(QListView.ResizeMode.Adjust)
        self.icon_view.setWordWrap(True)
        self.icon_view.setUniformItemSizes(True)
        self.icon_view.setLayoutMode(QListView.LayoutMode.Batched)
        self.icon_view.setBatchSize(100)
        self.icon_view.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self.icon_view.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self.icon_view.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )
        self.view_stack = QStackedWidget()
        self.view_stack.addWidget(self.view)
        self.view_stack.addWidget(self.icon_view)
        layout.addWidget(self.view_stack, 1)
        self.footer = QLabel("")
        self.footer.setProperty("role", "hint")
        layout.addWidget(self.footer)

        self.back_btn.clicked.connect(self.go_back)
        self.forward_btn.clicked.connect(self.go_forward)
        self.up_btn.clicked.connect(self.go_up)
        self.refresh_btn.clicked.connect(self.refresh)
        self.path_edit.returnPressed.connect(self._on_path_entered)
        self.filter_edit.textChanged.connect(self.proxy.setFilterFixedString)
        self.filter_edit.textChanged.connect(
            lambda _text: self._schedule_refresh()
        )
        for view in (self.view, self.icon_view):
            view.doubleClicked.connect(self._on_double_click)
            view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            view.customContextMenuRequested.connect(
                lambda position, v=view: self._on_context_menu(position, v)
            )
            view.selectionModel().selectionChanged.connect(
                lambda *_args, v=view: self._emit_selection(v)
            )
            view.clicked.connect(lambda _index: self.activated.emit())
        self.view.urls_dropped.connect(self.files_dropped.emit)

        self._install_shortcuts()
        self._update_buttons()
        self.proxy.rowsInserted.connect(
            lambda *_args: self._schedule_refresh()
        )
        self.proxy.rowsRemoved.connect(
            lambda *_args: self._schedule_refresh()
        )
        self.proxy.modelReset.connect(self._schedule_refresh)
        self._update_footer()

    # ------------------------------------------------------------------
    def _install_shortcuts(self):
        shortcuts = [
            ("Ctrl+C", self.copy_requested),
            ("Ctrl+X", self.cut_requested),
            ("Ctrl+V", self.paste_requested),
            ("Del", self.delete_requested),
            ("F2", self.rename_requested),
            ("F5", self.refresh_requested),
            ("F3", self.preview_requested),
            ("Ctrl+Shift+N", self.new_folder_requested),
        ]
        for sequence, signal in shortcuts:
            action = QAction(self)
            action.setShortcut(QKeySequence(sequence))
            action.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            action.triggered.connect(lambda _checked=False, sig=signal: sig.emit())
            self.view.addAction(action)
            self.icon_view.addAction(action)

        navigation = [
            ("Alt+Left", self.go_back),
            ("Alt+Right", self.go_forward),
            ("Alt+Up", self.go_up),
        ]
        for sequence, callback in navigation:
            action = QAction(self)
            action.setShortcut(QKeySequence(sequence))
            action.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            action.triggered.connect(callback)
            self.view.addAction(action)
            self.icon_view.addAction(action)

    def _path_for_index(self, index):
        source = self.proxy.mapToSource(index)
        return (normalize_path(self.model.filePath(source))
                if source.isValid() else "")

    def _on_path_entered(self):
        self.navigate(self.path_edit.text())

    def _on_double_click(self, index):
        source = self.proxy.mapToSource(index)
        if not source.isValid():
            return
        path = normalize_path(self.model.filePath(source))
        if self.model.isDir(source):
            self.navigate(path)
        else:
            ok, error = open_path(path)
            if not ok:
                self.status_message.emit(f"無法開啟：{error}")

    def _on_context_menu(self, position, view=None):
        view = view or self.current_view()
        index = view.indexAt(position)
        if index.isValid() and not view.selectionModel().isSelected(index):
            view.setCurrentIndex(index)
            view.selectionModel().select(
                index,
                QItemSelectionModel.SelectionFlag.ClearAndSelect
                | QItemSelectionModel.SelectionFlag.Rows,
            )
        paths = self.selected_paths()
        self.context_requested.emit(
            paths, view.viewport().mapToGlobal(position)
        )

    def _emit_selection(self, view=None):
        self._update_footer()
        self.selection_changed.emit(self.selected_paths())

    def _schedule_refresh(self):
        if not self._footer_timer.isActive():
            self._footer_timer.start()

    def _update_footer(self):
        view = self.current_view()
        model = view.model()
        count = model.rowCount(view.rootIndex())
        paths = self.selected_paths()
        total = 0
        for path in paths:
            try:
                info = os.stat(path)
                if stat.S_ISREG(info.st_mode):
                    total += info.st_size
            except OSError:
                pass
        text = tr(f"{count:,} 個項目")
        if paths:
            selected = tr(f"已選 {len(paths):,} 個")
            text += f" · {selected} · {format_size(total)}"
        self.footer.setText(text)

    def current_view(self):
        return (self.icon_view if self.view_stack.currentIndex() == 1
                else self.view)

    def set_thumbnail_mode(self, enabled):
        self.view_stack.setCurrentIndex(1 if enabled else 0)
        self._emit_selection()

    def _update_buttons(self):
        self.back_btn.setEnabled(self._history_index > 0)
        self.forward_btn.setEnabled(
            0 <= self._history_index < len(self._history) - 1
        )
        self.up_btn.setEnabled(bool(self.current_path))

    def selected_paths(self):
        paths = []
        for index in self.current_view().selectionModel().selectedRows(0):
            source = self.proxy.mapToSource(index)
            if source.isValid():
                paths.append(normalize_path(
                    self.model.filePath(source)
                ))
        return paths

    def set_compact(self, compact):
        """Hide metadata columns when the preview panel takes space."""
        self.compact = bool(compact)
        self.apply_columns()

    def set_column_visible(self, column, visible):
        if column == 2:
            self.show_type = bool(visible)
        elif column == 3:
            self.show_date = bool(visible)
        self.apply_columns()

    def apply_columns(self):
        self.view.setColumnHidden(2, self.compact or not self.show_type)
        self.view.setColumnHidden(3, not self.show_date)
        self.view.setColumnWidth(1, 78 if self.compact else 90)
        self.view.setColumnWidth(3, 112 if self.compact else 150)

    # ------------------------------------------------------------------
    def navigate(self, path, add_history=True):
        path = normalize_path(path)
        if path:
            if not is_dir_path(path):
                self.status_message.emit(f"資料夾不存在：{path}")
                return False
        else:
            path = ""

        source_index = self.model.index(path) if path else QModelIndex()
        if path and not source_index.isValid():
            self.status_message.emit(f"無法讀取資料夾：{path}")
            return False
        self.proxy.set_root_source(source_index)
        proxy_index = self.proxy.mapFromSource(source_index)
        if path and not proxy_index.isValid():
            # A filter may hide the folder itself; clear it and retry once.
            self.filter_edit.clear()
            proxy_index = self.proxy.mapFromSource(source_index)
        if path and not proxy_index.isValid():
            self.status_message.emit(f"無法顯示資料夾：{path}")
            return False

        self.view.setRootIndex(proxy_index)
        self.icon_view.setRootIndex(proxy_index)
        self.current_path = path
        self.view.current_dir = path
        self.path_edit.blockSignals(True)
        self.path_edit.setText(path)
        self.path_edit.blockSignals(False)
        self.view.clearSelection()
        self.icon_view.clearSelection()
        self._emit_selection()
        if add_history:
            if self._history_index < len(self._history) - 1:
                self._history = self._history[: self._history_index + 1]
            if not self._history or self._history[-1] != path:
                self._history.append(path)
            self._history_index = len(self._history) - 1
        self._update_buttons()
        self.path_changed.emit(path)
        self._schedule_refresh()
        return True

    def go_back(self):
        if self._history_index > 0:
            self._history_index -= 1
            self.navigate(self._history[self._history_index], add_history=False)

    def go_forward(self):
        if self._history_index < len(self._history) - 1:
            self._history_index += 1
            self.navigate(self._history[self._history_index], add_history=False)

    def go_up(self):
        if not self.current_path:
            return
        current = normalize_path(self.current_path)
        raw = current.rstrip("\\")
        if len(raw) == 2 and raw[1] == ":":
            self.navigate("")
            return
        if raw.startswith("\\\\"):
            parts = [part for part in raw[2:].split("\\") if part]
            if len(parts) <= 1:
                self.navigate("")
                return
            if len(parts) == 2:
                self.navigate(f"\\\\{parts[0]}")
                return
        parent = os.path.dirname(raw)
        if not parent or parent == raw:
            self.navigate("")
        else:
            self.navigate(parent)

    def refresh(self):
        self.filter_edit.clear()
        self.proxy.invalidate()
        self.navigate(self.current_path, add_history=False)
        self.refresh_requested.emit()
