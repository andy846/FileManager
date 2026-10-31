"""Ctrl+K command palette for modules, folders and actions."""

from dataclasses import dataclass

from PyQt6.QtCore import QEvent, Qt
from PyQt6.QtWidgets import (
    QDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem, QVBoxLayout,
)

from app.core.i18n import tr


@dataclass
class Command:
    label: str
    subtitle: str
    callback: object


def _fuzzy_score(text, query):
    text = text.lower()
    query = query.lower().strip()
    if not query:
        return 1
    if query in text:
        return 100 - text.index(query)
    position = 0
    score = 0
    for char in query:
        found = text.find(char, position)
        if found < 0:
            return -1
        score += 1
        position = found + 1
    return score


class CommandPalette(QDialog):
    """Small keyboard-first action launcher."""

    def __init__(self, commands, parent=None):
        super().__init__(parent)
        self.commands = list(commands)
        self.selected = None
        self.setWindowTitle(tr("命令面板"))
        self.resize(620, 420)
        self.setModal(True)

        layout = QVBoxLayout(self)
        self.search = QLineEdit()
        self.search.setPlaceholderText(
            tr("輸入模組、資料夾或動作... (Ctrl+K)")
        )
        layout.addWidget(self.search)
        self.list = QListWidget()
        self.list.setAlternatingRowColors(True)
        self.list.setSpacing(2)
        layout.addWidget(self.list, 1)
        hint = QLabel(tr("↑↓ 選擇 · Enter 執行 · Esc 關閉"))
        hint.setProperty("role", "hint")
        hint.setAlignment(Qt.AlignmentFlag.AlignRight)
        layout.addWidget(hint)

        self.search.textChanged.connect(self._refresh)
        self.search.returnPressed.connect(self._activate)
        self.list.itemActivated.connect(lambda _item: self._activate())
        self.search.installEventFilter(self)
        self._refresh("")
        self.search.setFocus()

    def eventFilter(self, obj, event):
        if obj is self.search and event.type() == QEvent.Type.KeyPress:
            key = event.key()
            if key == Qt.Key.Key_Down:
                self._move_selection(1)
                return True
            if key == Qt.Key.Key_Up:
                self._move_selection(-1)
                return True
            if key == Qt.Key.Key_Escape:
                self.reject()
                return True
        return super().eventFilter(obj, event)

    def _move_selection(self, delta):
        row = self.list.currentRow()
        count = self.list.count()
        if count:
            self.list.setCurrentRow((row + delta) % count)

    def _refresh(self, text):
        query = text.strip()
        scored = []
        for command in self.commands:
            score = _fuzzy_score(
                f"{command.label} {command.subtitle}", query
            )
            if score >= 0:
                scored.append((score, command))
        scored.sort(key=lambda item: (-item[0], item[1].label.lower()))
        self.list.clear()
        for _score, command in scored[:50]:
            item = QListWidgetItem(
                f"{command.label}\n{command.subtitle}"
                if command.subtitle else command.label
            )
            item.setData(Qt.ItemDataRole.UserRole, command)
            self.list.addItem(item)
        if self.list.count():
            self.list.setCurrentRow(0)

    def _activate(self):
        item = self.list.currentItem()
        if item is None:
            return
        self.selected = item.data(Qt.ItemDataRole.UserRole)
        self.accept()


def run_command_palette(parent, commands):
    dialog = CommandPalette(commands, parent)
    dialog.exec()
    if dialog.selected is not None:
        dialog.selected.callback()
    return dialog.selected
