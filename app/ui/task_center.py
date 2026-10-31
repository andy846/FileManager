"""Unified task centre dialog."""

from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QHBoxLayout, QHeaderView,
    QLabel, QProgressBar, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from app.core.i18n import tr, tr_exact
from app.ui.components import StatusBadge, make_button


class TaskCenterDialog(QDialog):
    """Session task list with cancel / pause controls and filtering."""

    def __init__(self, manager, parent=None, theme="dark"):
        super().__init__(parent)
        self.manager = manager
        self.theme = theme
        self.setWindowTitle("任務中心")
        self.resize(900, 460)
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(120)
        self._refresh_timer.timeout.connect(self._refresh)

        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        self.summary = QLabel("")
        self.summary.setProperty("role", "hint")
        top.addWidget(self.summary, 1)
        top.addWidget(QLabel("篩選:"))
        self.filter = QComboBox()
        self.filter.addItem(tr("全部"), "all")
        self.filter.addItem(tr("進行中"), "active")
        self.filter.addItem(tr("完成"), "done")
        self.filter.addItem(tr("失敗"), "failed")
        self.filter.currentIndexChanged.connect(self._refresh)
        top.addWidget(self.filter)
        layout.addLayout(top)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["狀態", "任務", "進度", "訊息", "時間"]
        )
        self.table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setDefaultSectionSize(34)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(0, 92)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(2, 180)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.table, 1)

        buttons = QHBoxLayout()
        self.pause_btn = make_button("暫停／繼續", "pause", self.theme)
        self.pause_btn.clicked.connect(self._toggle_pause)
        self.cancel_btn = make_button(
            "取消任務", "stop", self.theme, "danger"
        )
        self.cancel_btn.clicked.connect(self._cancel)
        self.clear_btn = make_button(
            "清除已完成", "trash", self.theme, "ghost"
        )
        self.clear_btn.clicked.connect(self._clear_finished)
        close_btn = make_button("關閉", "x", self.theme, "ghost")
        close_btn.clicked.connect(self.accept)
        buttons.addWidget(self.pause_btn)
        buttons.addWidget(self.cancel_btn)
        buttons.addStretch(1)
        buttons.addWidget(self.clear_btn)
        buttons.addWidget(close_btn)
        layout.addLayout(buttons)

        self.manager.changed.connect(self._schedule_refresh)
        self.table.itemSelectionChanged.connect(self._update_buttons)
        self._refresh()

    def _schedule_refresh(self):
        if not self._refresh_timer.isActive():
            self._refresh_timer.start()

    def _visible_tasks(self):
        mode = self.filter.currentData()
        tasks = self.manager.tasks()
        if mode == "active":
            return [task for task in tasks if task.is_active]
        if mode == "done":
            return [task for task in tasks if task.status == "done"]
        if mode == "failed":
            return [task for task in tasks if task.status == "failed"]
        return tasks

    def _refresh(self):
        selected = self._selected_task_id()
        tasks = self._visible_tasks()
        self.table.setRowCount(0)
        for task in reversed(tasks):
            row = self.table.rowCount()
            self.table.insertRow(row)
            badge = StatusBadge(task.status)
            badge.setFixedHeight(22)
            badge.setAttribute(
                Qt.WidgetAttribute.WA_TransparentForMouseEvents, True
            )
            self.table.setCellWidget(row, 0, badge)

            title_item = QTableWidgetItem(tr(task.title))
            title_item.setData(Qt.ItemDataRole.UserRole, task.id)
            self.table.setItem(row, 1, title_item)

            bar = QProgressBar()
            bar.setRange(0, 100)
            bar.setValue(task.percent)
            bar.setFixedHeight(12)
            bar.setTextVisible(False)
            bar.setAttribute(
                Qt.WidgetAttribute.WA_TransparentForMouseEvents, True
            )
            self.table.setCellWidget(row, 2, bar)

            message = (
                tr_exact(task.error) if task.error else tr(task.message)
            )
            message_item = QTableWidgetItem(message)
            message_item.setToolTip(message)
            self.table.setItem(row, 3, message_item)
            started = task.started_at.strftime("%H:%M:%S")
            self.table.setItem(row, 4, QTableWidgetItem(started))
            if selected == task.id:
                self.table.selectRow(row)
        active = self.manager.active_count()
        completed = sum(1 for task in self.manager.tasks()
                        if not task.is_active)
        self.summary.setText(
            f"進行中 {active} · 已完成／結束 {completed}"
            f" · 顯示 {len(tasks)} 筆"
        )
        self._update_buttons()

    def _selected_task_id(self):
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 1)
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _selected_task(self):
        task_id = self._selected_task_id()
        for task in self.manager.tasks():
            if task.id == task_id:
                return task
        return None

    def _update_buttons(self):
        task = self._selected_task()
        active = bool(task and task.is_active)
        self.cancel_btn.setEnabled(active)
        self.pause_btn.setEnabled(active and task.can_pause)

    def _cancel(self):
        self.manager.cancel(self._selected_task())
        self._refresh()

    def _toggle_pause(self):
        self.manager.toggle_pause(self._selected_task())
        self._refresh()

    def _clear_finished(self):
        self.manager.clear_finished()
        self._refresh()


def show_task_center(manager, parent=None):
    if manager is None:
        return None
    dialog = TaskCenterDialog(manager, parent)
    dialog.show()
    return dialog
