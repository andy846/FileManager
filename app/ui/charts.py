"""Small theme-aware dashboard widgets (no external chart dependency)."""

from PyQt6.QtCore import QRectF, QSize, Qt
from PyQt6.QtGui import QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QProgressBar, QSizePolicy, QVBoxLayout, QWidget,
)

from app.core.i18n import tr
from app.core.utils import format_size

CHART_COLORS = {
    "dark": [
        "#60a5fa", "#4ade80", "#fbbf24", "#f87171",
        "#a78bfa", "#22d3ee", "#f59e0b", "#94a3b8",
    ],
    "light": [
        "#2563eb", "#15803d", "#b45309", "#b91c1c",
        "#7c3aed", "#0e7490", "#c2410c", "#64748b",
    ],
}

CATEGORY_COLORS = {
    "documents": "#3b82f6",
    "images": "#8b5cf6",
    "video": "#ef4444",
    "audio": "#10b981",
    "archives": "#f59e0b",
    "installers": "#64748b",
    "code": "#06b6d4",
    "other": "#94a3b8",
}


def chart_colors(theme):
    return CHART_COLORS.get(theme, CHART_COLORS["dark"])


class StatCard(QFrame):
    """Compact KPI card used along the top of the dashboard."""

    def __init__(self, title, value="—", subtitle="", accent=None, parent=None):
        super().__init__(parent)
        self.setObjectName("statCard")
        self.setMinimumHeight(92)
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(2)

        self.title_label = QLabel(title)
        self.title_label.setProperty("role", "hint")
        self.title_label.setMinimumWidth(0)
        layout.addWidget(self.title_label)

        self.value_label = QLabel(value)
        self.value_label.setObjectName("statValue")
        self.value_label.setMinimumWidth(0)
        layout.addWidget(self.value_label)

        self.subtitle_label = QLabel(subtitle)
        self.subtitle_label.setProperty("role", "hint")
        self.subtitle_label.setWordWrap(True)
        self.subtitle_label.setMinimumWidth(0)
        layout.addWidget(self.subtitle_label)

        if accent:
            self.set_accent(accent)

    def set_accent(self, color):
        self.value_label.setStyleSheet(f"color: {color};")

    def set_value(self, value, subtitle=None):
        self.value_label.setText(str(value))
        if subtitle is not None:
            self.subtitle_label.setText(str(subtitle))


class DonutChart(QWidget):
    """Simple donut chart drawn with QPainter."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items = []
        self._theme = "dark"
        self.setMinimumSize(180, 180)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)

    def sizeHint(self):
        return QSize(200, 200)

    def set_theme(self, theme):
        self._theme = theme
        self.update()

    def set_data(self, items):
        """*items* is a list of ``(label, value, color)`` tuples."""
        self._items = list(items or [])
        self.update()

    def paintEvent(self, event):  # noqa: N802 (Qt API)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        side = min(self.width(), self.height()) - 24
        rect = QRectF(
            (self.width() - side) / 2,
            (self.height() - side) / 2,
            side,
            side,
        )
        pen_width = max(14, int(side * 0.12))
        ring = rect.adjusted(pen_width / 2, pen_width / 2,
                             -pen_width / 2, -pen_width / 2)
        palette = chart_colors(self._theme)

        background = QColor("#3a4250" if self._theme == "dark" else "#e3e9f1")
        painter.setPen(QPen(background, pen_width))
        painter.drawEllipse(ring)

        total = sum(max(0, value) for _label, value, _color in self._items)
        if total > 0:
            start = 90 * 16
            for index, (_label, value, color_value) in enumerate(self._items):
                if value <= 0:
                    continue
                span = -int(round(value / total * 360 * 16))
                color = QColor(color_value or palette[index % len(palette)])
                painter.setPen(QPen(color, pen_width))
                painter.drawArc(ring, start, span)
                start += span

        painter.setPen(QColor("#e6e9ee" if self._theme == "dark" else "#1f2733"))
        value_font = QFont(self.font())
        value_font.setPointSize(max(12, int(side * 0.075)))
        value_font.setBold(True)
        painter.setFont(value_font)
        text_rect = QRectF(rect.x(), rect.y() + side * 0.30, side, side * 0.25)
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, format_size(total))

        label_font = QFont(self.font())
        label_font.setPointSize(max(8, int(side * 0.045)))
        painter.setFont(label_font)
        painter.setPen(QColor("#9aa4b2" if self._theme == "dark" else "#6b7785"))
        label_rect = QRectF(rect.x(), rect.y() + side * 0.53, side, side * 0.18)
        painter.drawText(label_rect, Qt.AlignmentFlag.AlignCenter, tr("總容量"))


class BarList(QWidget):
    """Vertical list of labelled proportion bars."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(6)
        self._empty = QLabel("尚無資料")
        self._empty.setProperty("role", "hint")
        self._layout.addWidget(self._empty)
        self._rows = []
        self._theme = "dark"

    def set_theme(self, theme):
        self._theme = theme

    def set_data(self, items):
        for row in self._rows:
            row.setParent(None)
            row.deleteLater()
        self._rows = []
        while self._layout.count():
            item = self._layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        items = [item for item in (items or []) if item[1] > 0]
        if not items:
            self._empty = QLabel("尚無資料")
            self._empty.setProperty("role", "hint")
            self._layout.addWidget(self._empty)
            return

        maximum = max(value for _label, value in items)
        color = chart_colors(self._theme)[0]
        for label, value in items:
            row = QWidget()
            layout = QHBoxLayout(row)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(8)

            name = QLabel(str(label))
            name.setObjectName("chartDataLabel")
            name.setMinimumWidth(90)
            name.setMaximumWidth(150)
            name.setToolTip(str(label))
            layout.addWidget(name)

            bar = QProgressBar()
            bar.setRange(0, 1000)
            bar.setValue(int(value / maximum * 1000) if maximum else 0)
            bar.setTextVisible(False)
            bar.setFixedHeight(10)
            bar.setStyleSheet(
                "QProgressBar { border: none; border-radius: 5px; "
                "background-color: #3a4250; }"
                if self._theme == "dark" else
                "QProgressBar { border: none; border-radius: 5px; "
                "background-color: #e3e9f1; }"
            )
            bar.setStyleSheet(
                bar.styleSheet()
                + f" QProgressBar::chunk {{ background-color: {color}; border-radius: 5px; }}"
            )
            layout.addWidget(bar, 1)

            amount = QLabel(format_size(value))
            amount.setProperty("role", "hint")
            amount.setMinimumWidth(72)
            amount.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            layout.addWidget(amount)

            self._layout.addWidget(row)
            self._rows.append(row)
