"""Reusable UI widgets shared by all module pages."""

import os

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLineEdit, QPushButton, QToolButton,
    QMenu, QFileDialog, QFrame, QLabel,
)
from PyQt6.QtGui import QDragEnterEvent, QDropEvent

from app.core.i18n import tr
from app.core.utils import (
    extended_path, is_unc_path, is_unc_server_root, normalize_path,
    short_path,
)
from app.ui.path_utils import start_directory


class SectionLabel(QLabel):
    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self.setProperty("role", "header")


class HintLabel(QLabel):
    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self.setProperty("role", "hint")


class PathField(QWidget):
    """Line edit with browse + recent-folder dropdown and folder drag/drop."""

    pathChanged = pyqtSignal(str)

    def __init__(self, parent=None, mode="dir", field_name=None, settings=None,
                 placeholder="請選擇資料夾"):
        super().__init__(parent)
        self.mode = mode
        self.field_name = field_name
        self.settings = settings

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.line = QLineEdit()
        self.line.setPlaceholderText(placeholder)
        self.line.textChanged.connect(
            lambda t: self.pathChanged.emit(normalize_path(t))
        )
        self.line.returnPressed.connect(self._on_return_pressed)
        self.line.editingFinished.connect(self._on_editing_finished)
        layout.addWidget(self.line, 1)

        self.browse_btn = QPushButton("瀏覽")
        self.browse_btn.clicked.connect(self._browse)
        layout.addWidget(self.browse_btn)

        if self.mode == "dir":
            self.network_btn = QPushButton("網路")
            self.network_btn.setToolTip(
                "瀏覽網路共享資料夾，或連線到 \\\\伺服器\\共享"
            )
            self.network_btn.clicked.connect(self._browse_network)
            layout.addWidget(self.network_btn)
        else:
            self.network_btn = None

        if field_name and settings:
            self.recent_btn = QToolButton()
            self.recent_btn.setText("最近 ▾")
            self._build_recent_menu()
            layout.addWidget(self.recent_btn)
        else:
            self.recent_btn = None

        self.setAcceptDrops(True)

    def _build_recent_menu(self):
        menu = QMenu(self)
        self._refresh_menu(menu)
        self.recent_btn.setMenu(menu)

    def _refresh_menu(self, menu=None):
        menu = menu or self.recent_btn.menu()
        menu.clear()
        for p in self.settings.recent(self.field_name):
            act = menu.addAction(short_path(p, 60))
            act.setToolTip(p)
            act.triggered.connect(lambda _=False, path=p: self.set_path(path))
        menu.addSeparator()
        clear = menu.addAction("清除紀錄")
        clear.triggered.connect(lambda: self.settings.clear_recent(self.field_name))

    def _browse(self):
        if self.mode == "file":
            path, _ = QFileDialog.getOpenFileName(self, tr("選擇檔案"))
        else:
            path = QFileDialog.getExistingDirectory(
                self, tr("選擇資料夾"), start_directory(self.text())
            )
            if not path and is_unc_server_root(self.text()):
                self._browse_network()
                return
        if path:
            self.set_path(path)

    def _browse_network(self):
        from app.ui.network_dialog import NetworkLocationDialog

        if getattr(self, "_network_open", False):
            return
        self._network_open = True
        try:
            dialog = NetworkLocationDialog(
                self.window(), initial=self.text()
            )
            if dialog.exec():
                path = dialog.selected_path
                if path:
                    self.set_path(path)
        finally:
            self._network_open = False

    def _on_editing_finished(self):
        text = normalize_path(self.line.text())
        if text and text != self.line.text():
            self.set_path(text)
        if (self.mode == "dir" and text and is_unc_path(text)
                and not is_unc_server_root(text)
                and not os.path.isdir(extended_path(text))):
            from app.core.drives import ensure_network_share, unc_share_root

            ensure_network_share(unc_share_root(text) or text)

    def _on_return_pressed(self):
        if self.mode != "dir":
            return
        text = normalize_path(self.line.text())
        if not is_unc_path(text):
            return
        if is_unc_server_root(text):
            self._browse_network()
            return
        if os.path.isdir(extended_path(text)):
            return

        from app.core.drives import ensure_network_share, unc_share_root

        ok, _error = ensure_network_share(unc_share_root(text) or text)
        if not ok:
            self._browse_network()

    def set_path(self, path):
        path = normalize_path(path)
        # Setting the text would emit pathChanged via textChanged; block it
        # so the signal fires exactly once below.
        self.line.blockSignals(True)
        self.line.setText(path)
        self.line.setCursorPosition(0)
        self.line.blockSignals(False)
        if self.field_name and self.settings:
            self.settings.remember_path(self.field_name, path)
            if self.recent_btn:
                self._refresh_menu()
        self.pathChanged.emit(path)

    def text(self):
        return normalize_path(self.line.text())

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
        urls = event.mimeData().urls()
        if urls:
            path = urls[0].toLocalFile()
            self.set_path(path)
            event.acceptProposedAction()


class DropArea(QFrame):
    """Dashed-border drop target accepting a single folder."""

    folder_dropped = pyqtSignal(str)

    def __init__(self, parent=None, text="拖放資料夾到此處"):
        super().__init__(parent)
        self.setObjectName("dropArea")
        self.setMinimumHeight(70)
        self.setAcceptDrops(True)
        layout = QVBoxLayout(self)
        label = QLabel(text)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(label)
        self.setStyleSheet("QFrame#dropArea { border: 2px dashed #888; border-radius: 8px; }")

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
        urls = event.mimeData().urls()
        if urls:
            path = urls[0].toLocalFile()
            self.folder_dropped.emit(path)
            event.acceptProposedAction()


class ExtensionChips(QWidget):
    """Toggleable extension pills plus a custom-extension input."""

    changed = pyqtSignal(list)

    COMMON = ["pdf", "jpg", "jpeg", "png", "gif", "docx", "doc", "xlsx",
              "xls", "txt", "mp4", "mp3", "zip", "rar", "7z", "csv",
              "pptx", "ppt", "ps", "afp", "pgp"]

    def __init__(self, parent=None, defaults=None):
        super().__init__(parent)
        self.buttons = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # Grid layout so all chips stay visible and wrap into rows.
        from PyQt6.QtWidgets import QGridLayout

        grid = QGridLayout()
        grid.setSpacing(6)
        cols = 6
        for idx, ext in enumerate(self.COMMON):
            btn = QPushButton(f".{ext}")
            btn.setCheckable(True)
            btn.setChecked(ext in (defaults or []))
            btn.toggled.connect(self._emit)
            btn.setMinimumWidth(50)
            btn.setMaximumHeight(28)
            self.buttons[ext] = btn
            grid.addWidget(btn, idx // cols, idx % cols)
        grid.setColumnStretch(cols, 1)
        layout.addLayout(grid)

        row = QHBoxLayout()
        self.custom_edit = QLineEdit()
        self.custom_edit.setPlaceholderText("自訂副檔名 (逗號分隔, 例如 tmp, bak)")
        self.custom_edit.textChanged.connect(self._emit)
        row.addWidget(self.custom_edit, 1)
        select_all = QPushButton("全選")
        select_all.clicked.connect(lambda: self._set_all(True))
        clear_all = QPushButton("取消全選")
        clear_all.clicked.connect(lambda: self._set_all(False))
        row.addWidget(select_all)
        row.addWidget(clear_all)
        layout.addLayout(row)

    def _set_all(self, state):
        for btn in self.buttons.values():
            btn.setChecked(state)

    def _emit(self, *_):
        self.changed.emit(self.selected())

    def selected(self):
        exts = [e for e, b in self.buttons.items() if b.isChecked()]
        custom = [x.strip().lstrip(".").lower()
                  for x in self.custom_edit.text().split(",") if x.strip()]
        for c in custom:
            if c and c not in exts:
                exts.append(c)
        return exts

    def set_selected(self, exts):
        for e, b in self.buttons.items():
            b.setChecked(e in exts)
        custom = [e for e in exts if e not in self.buttons]
        self.custom_edit.setText(", ".join(custom))
