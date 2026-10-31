"""Unified light/dark theme (QSS) for the whole application."""

from PyQt6.QtWidgets import QApplication

LIGHT = {
    "bg": "#f6f8fb",
    "panel": "#ffffff",
    "panel_alt": "#eef2f7",
    "text": "#0f172a",
    "text_hint": "#5f6b7a",
    "border": "#d8e0ea",
    "primary": "#2563eb",
    "primary_text": "#ffffff",
    "primary_accent": "#1d4ed8",
    "primary_hover": "#1d4ed8",
    "primary_soft": "#e5edff",
    "danger": "#b91c1c",
    "danger_fill": "#b91c1c",
    "danger_hover": "#7f1d1d",
    "danger_text": "#ffffff",
    "danger_soft": "#fee2e2",
    "success": "#15803d",
    "success_fill": "#15803d",
    "success_hover": "#166534",
    "success_soft": "#dcfce7",
    "warning": "#b45309",
    "warning_fill": "#b45309",
    "warning_soft": "#fef3c7",
    "focus": "#2563eb",
    "row_alt": "#f6f8fc",
    "row_hover": "#eef4ff",
    "header": "#1d4ed8",
    "status_bg": "#eef2f7",
    "nav_hover": "#e5ebf4",
    "nav_sel_bg": "#e3edff",
    "nav_sel_text": "#1d4ed8",
    "nav_group": "#5f6b7a",
}

DARK = {
    "bg": "#151a21",
    "panel": "#1c232c",
    "panel_alt": "#242d38",
    "text": "#e6edf3",
    "text_hint": "#9aa8b6",
    "border": "#33404f",
    "primary": "#2563eb",
    "primary_text": "#ffffff",
    "primary_accent": "#60a5fa",
    "primary_hover": "#1d4ed8",
    "primary_soft": "#1d3557",
    "danger": "#f87171",
    "danger_fill": "#b91c1c",
    "danger_hover": "#7f1d1d",
    "danger_text": "#ffffff",
    "danger_soft": "#3f1d22",
    "success": "#4ade80",
    "success_fill": "#15803d",
    "success_hover": "#166534",
    "success_soft": "#123023",
    "warning": "#fbbf24",
    "warning_fill": "#b45309",
    "warning_soft": "#3a2a10",
    "focus": "#60a5fa",
    "row_alt": "#202933",
    "row_hover": "#263341",
    "header": "#60a5fa",
    "status_bg": "#202832",
    "nav_hover": "#293340",
    "nav_sel_bg": "rgba(37, 99, 235, 0.26)",
    "nav_sel_text": "#93c5fd",
    "nav_group": "#9aa8b6",
}


def _palette(theme):
    return DARK if theme == "dark" else LIGHT


def build_stylesheet(theme="dark"):
    c = _palette(theme)
    return f"""
    QWidget {{
        background-color: {c['bg']};
        color: {c['text']};
        font-family: "Segoe UI", "Microsoft JhengHei", "PingFang TC", sans-serif;
        font-size: 10pt;
    }}
    QMainWindow, QDialog {{
        background-color: {c['bg']};
    }}
    QLabel[role="header"] {{
        font-size: 15pt;
        font-weight: bold;
        color: {c['header']};
    }}
    QLabel[role="pageTitle"] {{
        font-size: 16pt;
        font-weight: bold;
        color: {c['text']};
    }}
    QLabel {{
        background: transparent;
    }}
    QLabel[role="hint"] {{
        font-size: 9pt;
        color: {c['text_hint']};
    }}
    QLabel#statValue {{
        font-size: 20pt;
        font-weight: bold;
        color: {c['primary_accent']};
    }}
    QLabel#sectionTitle {{
        font-size: 11pt;
        font-weight: bold;
        color: {c['text']};
    }}
    QFrame#statCard, QFrame#diskCard {{
        background-color: {c['panel']};
        border: 1px solid {c['border']};
        border-radius: 10px;
    }}
    QFrame#statCard QLabel, QFrame#diskCard QLabel {{
        background: transparent;
    }}
    QScrollArea {{
        border: none;
        background: transparent;
    }}
    QWidget#scrollContent {{
        background-color: {c['bg']};
    }}
    QListWidget#activityList {{
        background-color: {c['panel']};
        border: 1px solid {c['border']};
        border-radius: 8px;
    }}
    QListWidget#activityList::item {{
        padding: 6px;
        border-bottom: 1px solid {c['border']};
    }}
    QWidget#previewPanel {{
        background-color: {c['panel']};
        border-left: 1px solid {c['border']};
    }}
    QGroupBox {{
        background-color: {c['panel']};
        border: 1px solid {c['border']};
        border-radius: 8px;
        margin-top: 12px;
        padding: 10px;
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        left: 12px;
        padding: 0 4px;
        color: {c['header']};
        font-weight: bold;
    }}
    QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox, QComboBox, QDateEdit {{
        background-color: {c['panel']};
        border: 1px solid {c['border']};
        border-radius: 6px;
        padding: 5px 8px;
        color: {c['text']};
    }}
    QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QSpinBox:focus,
    QDoubleSpinBox:focus, QComboBox:focus, QDateEdit:focus {{
        border: 2px solid {c['focus']};
        padding: 4px 7px;
    }}
    QCheckBox:focus, QRadioButton:focus {{
        color: {c['primary_accent']};
    }}
    QPushButton {{
        background-color: {c['panel_alt']};
        border: 1px solid {c['border']};
        border-radius: 7px;
        padding: 6px 12px;
        min-height: 18px;
        color: {c['text']};
    }}
    QPushButton:hover {{
        border: 1px solid {c['primary_accent']};
        background-color: {c['row_hover']};
    }}
    QPushButton:pressed {{
        background-color: {c['primary_soft']};
    }}
    QPushButton:focus {{
        border: 2px solid {c['focus']};
        padding: 5px 11px;
    }}
    QToolButton:focus {{
        border: 2px solid {c['focus']};
        padding: 2px 6px;
    }}
    QPushButton:checked {{
        background-color: {c['primary']};
        color: {c['primary_text']};
        border: 1px solid {c['primary']};
        font-weight: bold;
    }}
    QPushButton:checked:hover {{
        background-color: {c['primary_hover']};
        border: 1px solid {c['primary_hover']};
    }}
    QPushButton:disabled {{
        color: {c['text_hint']};
        background-color: {c['panel']};
    }}
    QPushButton[variant="primary"] {{
        background-color: {c['primary']};
        color: {c['primary_text']};
        border: 1px solid {c['primary']};
        font-weight: bold;
        min-width: 96px;
    }}
    QPushButton[variant="primary"]:hover {{
        background-color: {c['primary_hover']};
    }}
    QPushButton[variant="ghost"] {{
        background-color: transparent;
        border: 1px solid transparent;
    }}
    QPushButton[variant="ghost"]:hover {{
        background-color: {c['row_hover']};
        border: 1px solid {c['border']};
    }}
    QPushButton[variant="danger"] {{
        background-color: {c['danger_fill']};
        color: {c['danger_text']};
        border: none;
        font-weight: bold;
    }}
    QPushButton[variant="danger"]:hover {{
        background-color: {c['danger_hover']};
    }}
    QPushButton[variant="success"] {{
        background-color: {c['success_fill']};
        color: {c['primary_text']};
        border: none;
        font-weight: bold;
    }}
    QPushButton[variant="success"]:hover {{
        background-color: {c['success_hover']};
    }}
    QToolButton {{
        background-color: {c['panel_alt']};
        border: 1px solid {c['border']};
        border-radius: 7px;
        padding: 4px 8px;
    }}
    QToolButton:hover {{
        border-color: {c['primary_accent']};
        background-color: {c['row_hover']};
    }}
    QToolButton#sidebarCollapseBtn {{
        background-color: {c['primary_soft']};
        border: 1px solid {c['primary_accent']};
        color: {c['primary_accent']};
        font-weight: 600;
        padding: 5px 8px;
    }}
    QToolButton#sidebarCollapseBtn:hover {{
        background-color: {c['row_hover']};
        border-color: {c['primary']};
        color: {c['primary_accent']};
    }}
    QToolButton:checked {{
        background-color: {c['primary_soft']};
        border-color: {c['primary_accent']};
    }}
    QToolButton::menu-indicator {{
        image: none;
    }}
    QListWidget, QTableWidget, QTreeWidget {{
        background-color: {c['panel']};
        border: 1px solid {c['border']};
        border-radius: 8px;
        alternate-background-color: {c['row_alt']};
        gridline-color: {c['border']};
        selection-background-color: {c['primary']};
        selection-color: {c['primary_text']};
    }}
    QListWidget:focus, QTableWidget:focus, QTreeWidget:focus {{
        border: 1px solid {c['focus']};
    }}
    QHeaderView::section {{
        background-color: {c['panel_alt']};
        color: {c['text']};
        border: none;
        border-bottom: 1px solid {c['border']};
        padding: 6px;
        font-weight: bold;
    }}
    QTableWidget::item, QListWidget::item, QTreeWidget::item {{
        padding: 5px;
        color: {c['text']};
    }}
    QTableWidget::item:selected, QListWidget::item:selected, QTreeWidget::item:selected {{
        background-color: {c['primary']};
        color: {c['primary_text']};
    }}
    QTableWidget::item:hover, QListWidget::item:hover, QTreeWidget::item:hover {{
        background-color: {c['row_hover']};
    }}
    QTableWidget QTableCornerButton::section {{
        background-color: {c['panel_alt']};
        border: none;
    }}
    QProgressBar {{
        border: 1px solid {c['border']};
        border-radius: 6px;
        background-color: {c['panel_alt']};
        text-align: center;
        height: 18px;
    }}
    QProgressBar::chunk {{
        background-color: {c['primary']};
        border-radius: 5px;
    }}
    QTabWidget::pane {{
        border: 1px solid {c['border']};
        border-radius: 6px;
        top: -1px;
    }}
    QTabBar::tab {{
        background-color: {c['panel_alt']};
        padding: 6px 14px;
        border: 1px solid {c['border']};
        border-bottom: none;
        border-top-left-radius: 6px;
        border-top-right-radius: 6px;
    }}
    QTabBar::tab:hover {{
        background-color: {c['row_hover']};
    }}
    QTabBar::tab:focus {{
        border: 2px solid {c['focus']};
    }}
    QTabBar::tab:selected {{
        background-color: {c['primary']};
        color: {c['primary_text']};
    }}
    QSplitter::handle {{
        background-color: {c['border']};
    }}
    QSplitter::handle:hover {{
        background-color: {c['primary_accent']};
    }}
    QToolTip {{
        background-color: {c['panel']};
        color: {c['text']};
        border: 1px solid {c['border']};
        padding: 5px 7px;
    }}
    QLabel[role="statusBadge"] {{
        border-radius: 8px;
        padding: 2px 8px;
        font-size: 8.5pt;
        font-weight: bold;
    }}
    QLabel[role="statusBadge"][status="running"] {{
        background-color: {c['primary_soft']};
        color: {c['primary_accent']};
    }}
    QLabel[role="statusBadge"][status="paused"] {{
        background-color: {c['warning_soft']};
        color: {c['warning']};
    }}
    QLabel[role="statusBadge"][status="done"] {{
        background-color: {c['success_soft']};
        color: {c['success']};
    }}
    QLabel[role="statusBadge"][status="failed"] {{
        background-color: {c['danger_soft']};
        color: {c['danger']};
    }}
    QLabel[role="statusBadge"][status="cancelled"] {{
        background-color: {c['panel_alt']};
        color: {c['text_hint']};
    }}
    QTableWidget::item:selected:hover, QListWidget::item:selected:hover,
    QTreeWidget::item:selected:hover {{
        background-color: {c['primary_hover']};
        color: {c['primary_text']};
    }}
    QScrollBar:vertical {{
        background: {c['panel_alt']};
        width: 12px;
        border-radius: 6px;
    }}
    QScrollBar::handle:vertical {{
        background: {c['border']};
        border-radius: 6px;
        min-height: 24px;
    }}
    QScrollBar:horizontal {{
        background: {c['panel_alt']};
        height: 12px;
        border-radius: 6px;
    }}
    QScrollBar::handle:horizontal {{
        background: {c['border']};
        border-radius: 6px;
        min-width: 24px;
    }}
    QMenu {{
        background-color: {c['panel']};
        border: 1px solid {c['border']};
        border-radius: 6px;
        padding: 4px;
    }}
    QMenu::item:selected {{
        background-color: {c['primary']};
        color: {c['primary_text']};
    }}
    QStatusBar {{
        background-color: {c['status_bg']};
        border-top: 1px solid {c['border']};
    }}
    QCheckBox::indicator, QRadioButton::indicator {{
        width: 16px;
        height: 16px;
    }}
    QComboBox QAbstractItemView {{
        background-color: {c['panel']};
        selection-background-color: {c['primary']};
    }}
    QWidget#sidebar {{
        background-color: {c['panel_alt']};
        border-right: 1px solid {c['border']};
    }}
    QTreeWidget#navTree {{
        background: transparent;
        border: none;
        outline: none;
        font-size: 10pt;
        show-decoration-selected: 0;
    }}
    QTreeWidget#navTree::item {{
        padding: 5px 8px;
        margin: 1px 4px;
        border-radius: 7px;
        color: {c['text']};
        background: transparent;
    }}
    QTreeWidget#navTree::item:hover {{
        background-color: {c['nav_hover']};
    }}
    QTreeWidget#navTree::item:selected {{
        background-color: {c['nav_sel_bg']};
        color: {c['nav_sel_text']};
        font-weight: bold;
    }}
    QTreeWidget#navTree::item:has-children {{
        color: {c['nav_group']};
        font-size: 8.5pt;
        font-weight: bold;
    }}
    QTreeWidget#navTree::branch {{
        background: transparent;
    }}
    QListWidget#compactNav {{
        background: transparent;
        border: none;
        outline: none;
    }}
    QListWidget#compactNav::item {{
        padding: 7px 6px;
        margin: 1px 4px;
        border-radius: 8px;
    }}
    QListWidget#compactNav::item:hover {{
        background-color: {c['nav_hover']};
    }}
    QListWidget#compactNav::item:selected {{
        background-color: {c['nav_sel_bg']};
    }}
    """


def apply_theme(app: QApplication, theme="dark"):
    app.setStyleSheet(build_stylesheet(theme))
    return theme
