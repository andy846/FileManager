"""Network share picker and UNC connection dialog."""

from PyQt6.QtCore import QThread, QTimer, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMessageBox, QPushButton, QVBoxLayout,
)

from app.core.drives import (
    connect_network_share, list_server_shares, normalize_unc_server,
)
from app.core.utils import is_unc_path, normalize_path, server_from_path


class ShareEnumWorker(QThread):
    completed = pyqtSignal(list)
    failed = pyqtSignal(str)

    def __init__(self, server, parent=None):
        super().__init__(parent)
        self.server = server

    def run(self):
        try:
            self.completed.emit(list_server_shares(self.server))
        except Exception as exc:
            self.failed.emit(str(exc))


class ShareConnectWorker(QThread):
    completed = pyqtSignal(bool, str)

    def __init__(self, path, username="", password="", parent=None):
        super().__init__(parent)
        self.path = path
        self.username = username
        self.password = password

    def run(self):
        try:
            ok, error = connect_network_share(
                self.path, self.username, self.password
            )
        except Exception as exc:
            ok, error = False, str(exc)
        self.completed.emit(ok, error)


class NetworkLocationDialog(QDialog):
    """Choose a shared folder on a server and optionally authenticate."""

    def __init__(self, parent=None, initial=""):
        super().__init__(parent)
        self.selected_path = ""
        self._initial_share = ""
        self._pending_path = ""
        self._share_worker = None
        self._connect_worker = None

        self.setWindowTitle("網路共享資料夾")
        self.setMinimumWidth(560)
        self.resize(620, 440)

        layout = QVBoxLayout(self)
        hint = QLabel(
            "輸入伺服器名稱或 IP，列出共享後選擇資料夾。"
            "需要帳號密碼時可在下方填寫。"
        )
        hint.setProperty("role", "hint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        server_row = QHBoxLayout()
        server_row.addWidget(QLabel("伺服器："))
        self.server_edit = QLineEdit()
        self.server_edit.setPlaceholderText("\\\\10.8.17.66 / 10.8.17.66")
        server_row.addWidget(self.server_edit, 1)
        self.refresh_btn = QPushButton("重新整理")
        self.refresh_btn.clicked.connect(self.refresh_shares)
        server_row.addWidget(self.refresh_btn)
        layout.addLayout(server_row)

        share_row = QHBoxLayout()
        share_row.addWidget(QLabel("共享路徑："))
        self.share_edit = QLineEdit()
        self.share_edit.setPlaceholderText("\\\\server\\share")
        share_row.addWidget(self.share_edit, 1)
        layout.addLayout(share_row)

        self.status = QLabel("請輸入伺服器名稱")
        self.status.setProperty("role", "hint")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        self.list = QListWidget()
        self.list.setAlternatingRowColors(True)
        self.list.itemDoubleClicked.connect(
            lambda _item: self._connect_selected()
        )
        self.list.currentItemChanged.connect(self._on_share_selected)
        layout.addWidget(self.list, 1)

        credentials = QGroupBox("需要帳號密碼時填寫（不會儲存密碼）")
        form = QFormLayout(credentials)
        self.username_edit = QLineEdit()
        self.username_edit.setPlaceholderText("DOMAIN\\user")
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("帳號：", self.username_edit)
        form.addRow("密碼：", self.password_edit)
        layout.addWidget(credentials)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        self.connect_btn = QPushButton("連線並使用")
        self.connect_btn.setProperty("variant", "primary")
        self.connect_btn.clicked.connect(self._connect_selected)
        buttons.addWidget(self.connect_btn)
        layout.addLayout(buttons)

        self.server_edit.returnPressed.connect(self.refresh_shares)
        initial = normalize_path(initial)
        server = ""
        if is_unc_path(initial):
            server = server_from_path(initial) or normalize_unc_server(initial)
            if initial.casefold() != server.casefold():
                self._initial_share = initial
        if self._initial_share:
            self.share_edit.setText(self._initial_share)
        if server:
            self.server_edit.setText(server)
            QTimer.singleShot(0, self.refresh_shares)

    def refresh_shares(self):
        if self._share_worker is not None and self._share_worker.isRunning():
            return
        server = normalize_unc_server(self.server_edit.text())
        if not server:
            self.status.setText("請輸入伺服器名稱或 IP")
            return
        self.server_edit.setText(server)
        self.list.clear()
        self.list.setEnabled(False)
        self.connect_btn.setEnabled(False)
        self.refresh_btn.setEnabled(False)
        self.status.setText(f"正在讀取 {server} 的共享...")
        self._share_worker = ShareEnumWorker(server, self)
        self._share_worker.completed.connect(self._on_shares)
        self._share_worker.failed.connect(self._on_share_error)
        self._share_worker.start()

    def _on_shares(self, shares):
        self.refresh_btn.setEnabled(True)
        self.list.setEnabled(True)
        self.connect_btn.setEnabled(True)
        self.list.clear()
        if not shares:
            self.status.setText("沒有找到可用的共享資料夾")
            return
        known = set()
        for share in shares:
            text = share["name"]
            if share.get("comment"):
                text += f"  —  {share['comment']}"
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, share["path"])
            item.setToolTip(share["path"])
            self.list.addItem(item)
            known.add(normalize_path(share["path"]).casefold())
        if (self._initial_share
                and self._initial_share.casefold() not in known):
            item = QListWidgetItem(self._initial_share)
            item.setData(Qt.ItemDataRole.UserRole, self._initial_share)
            item.setToolTip(self._initial_share)
            self.list.addItem(item)
        self.status.setText(f"找到 {len(shares)} 個共享資料夾")
        target = 0
        if self._initial_share:
            for row in range(self.list.count()):
                item = self.list.item(row)
                if normalize_path(
                    item.data(Qt.ItemDataRole.UserRole)
                ).casefold() == self._initial_share.casefold():
                    target = row
                    break
        self.list.setCurrentRow(target)

    def _on_share_error(self, message):
        self.refresh_btn.setEnabled(True)
        self.list.setEnabled(True)
        self.connect_btn.setEnabled(True)
        self.list.clear()
        if self._initial_share:
            item = QListWidgetItem(self._initial_share)
            item.setData(Qt.ItemDataRole.UserRole, self._initial_share)
            item.setToolTip(self._initial_share)
            self.list.addItem(item)
            self.list.setCurrentRow(0)
            self.status.setText(
                f"{message}；可直接按「連線並使用」嘗試此路徑"
            )
        else:
            self.status.setText(message)

    def _on_share_selected(self, current, _previous=None):
        if current is None:
            return
        path = normalize_path(current.data(Qt.ItemDataRole.UserRole))
        if path:
            self.share_edit.setText(path)

    def _connect_selected(self):
        path = normalize_path(self.share_edit.text())
        item = self.list.currentItem()
        if not path and item is not None:
            path = normalize_path(item.data(Qt.ItemDataRole.UserRole))
        if not path:
            path = self._initial_share
        if not path:
            QMessageBox.information(
                self, "選擇共享", "請先選擇一個共享資料夾。"
            )
            return
        if self._connect_worker is not None and self._connect_worker.isRunning():
            return
        self.status.setText(f"正在連線 {path} ...")
        self._pending_path = path
        self.connect_btn.setEnabled(False)
        self.refresh_btn.setEnabled(False)
        self._connect_worker = ShareConnectWorker(
            path, self.username_edit.text().strip(),
            self.password_edit.text(), self,
        )
        self._connect_worker.completed.connect(self._on_connected)
        self._connect_worker.start()

    def _on_connected(self, ok, error):
        self.connect_btn.setEnabled(True)
        self.refresh_btn.setEnabled(True)
        if not ok:
            self._pending_path = ""
            self.status.setText(error)
            QMessageBox.warning(
                self, "無法連線",
                f"{error}\n\n"
                "請確認伺服器名稱、共享名稱與帳號權限。",
            )
            return
        self.selected_path = normalize_path(self._pending_path)
        self._pending_path = ""
        self.accept()

    def closeEvent(self, event):  # noqa: N802 (Qt API)
        for worker in (self._share_worker, self._connect_worker):
            if worker is not None and worker.isRunning():
                worker.wait(3000)
                if worker.isRunning():
                    worker.terminate()
                    worker.wait(1000)
        super().closeEvent(event)
