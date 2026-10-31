"""Shared, theme-aware visual building blocks for module pages."""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView, QHBoxLayout, QLabel, QPushButton, QToolButton,
    QVBoxLayout, QWidget,
)

from app.core.i18n import tr
from app.ui.icons import get_icon, icon_color, set_icon


class PageHeader(QWidget):
    """Consistent title block used by every module page."""

    def __init__(self, title, subtitle="", icon=None, actions=None,
                 theme="dark", parent=None):
        super().__init__(parent)
        self._theme = theme
        self._icon_name = icon
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 2)
        layout.setSpacing(10)

        self.icon_label = QLabel()
        self.icon_label.setFixedSize(26, 26)
        layout.addWidget(self.icon_label, 0, Qt.AlignmentFlag.AlignTop)
        self.icon_label.setVisible(bool(icon))

        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(1)
        self.title_label = QLabel(title)
        self.title_label.setProperty("role", "pageTitle")
        text_layout.addWidget(self.title_label)
        self.subtitle_label = QLabel(subtitle)
        self.subtitle_label.setProperty("role", "hint")
        self.subtitle_label.setWordWrap(True)
        text_layout.addWidget(self.subtitle_label)
        layout.addLayout(text_layout, 1)
        self.subtitle_label.setVisible(bool(subtitle))

        self.actions_layout = QHBoxLayout()
        self.actions_layout.setContentsMargins(0, 0, 0, 0)
        self.actions_layout.setSpacing(6)
        layout.addLayout(self.actions_layout)
        for action in actions or []:
            self.add_action(action)
        self.set_theme(theme)

    def add_action(self, widget):
        self.actions_layout.addWidget(widget)
        return widget

    def set_theme(self, theme):
        self._theme = theme
        if self._icon_name:
            pixmap = get_icon(
                self._icon_name, theme, icon_color(theme, "primary_accent"), 24
            ).pixmap(24, 24)
            self.icon_label.setPixmap(pixmap)


class EmptyState(QWidget):
    """Centered guidance shown when a page has no content yet."""

    def __init__(self, title, description="", icon="file", action=None,
                 theme="dark", parent=None):
        super().__init__(parent)
        self._theme = theme
        self._icon_name = icon
        self._action = action
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(8)
        layout.addStretch(1)
        self.icon_label = QLabel()
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.icon_label)
        self.title_label = QLabel(title)
        self.title_label.setProperty("role", "sectionTitle")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.title_label)
        self.description_label = QLabel(description)
        self.description_label.setProperty("role", "hint")
        self.description_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.description_label.setWordWrap(True)
        layout.addWidget(self.description_label)
        if action is not None:
            action.setParent(self)
            button_row = QHBoxLayout()
            button_row.addStretch(1)
            button_row.addWidget(action)
            button_row.addStretch(1)
            layout.addLayout(button_row)
        layout.addStretch(1)
        self.set_theme(theme)

    def set_theme(self, theme):
        self._theme = theme
        pixmap = get_icon(
            self._icon_name, theme, icon_color(theme, "text_hint"), 40
        ).pixmap(40, 40)
        self.icon_label.setPixmap(pixmap)

    def set_content(self, title, description=""):
        self.title_label.setText(title)
        self.description_label.setText(description)
        self.description_label.setVisible(bool(description))


class StatusBadge(QLabel):
    """Compact semantic status pill."""

    LABELS = {
        "running": "進行中",
        "paused": "已暫停",
        "done": "完成",
        "failed": "失敗",
        "cancelled": "已取消",
        "skipped": "已跳過",
        "pending": "待處理",
    }

    def __init__(self, status="running", parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setProperty("role", "statusBadge")
        self.set_status(status)

    def set_status(self, status):
        self.setProperty("status", status)
        self.setText(tr(self.LABELS.get(status, status)))
        self.style().unpolish(self)
        self.style().polish(self)


class IconToolButton(QToolButton):
    def __init__(self, icon_name, tooltip, theme="dark", checkable=False,
                 parent=None):
        super().__init__(parent)
        self.setToolTip(tooltip)
        self.setAccessibleName(tooltip)
        self.setCheckable(checkable)
        self.setFixedSize(32, 32)
        set_icon(self, icon_name, theme, "text", 18)


def make_button(text, icon_name=None, theme="dark", variant=None, tooltip=None):
    button = QPushButton(text)
    if icon_name:
        set_icon(button, icon_name, theme, "text", 16)
    if variant:
        button.setProperty("variant", variant)
    if tooltip:
        button.setToolTip(tooltip)
        button.setAccessibleName(tooltip)
    return button


def apply_table_defaults(table):
    """Consistent row height, alignment and selection for data tables."""
    table.verticalHeader().setDefaultSectionSize(28)
    table.verticalHeader().setVisible(False)
    table.setAlternatingRowColors(True)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    return table
