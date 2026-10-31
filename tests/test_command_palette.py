"""Smoke tests for the command palette."""

from app.ui.command_palette import Command, CommandPalette


def test_command_palette_filters_and_selects(app):
    calls = []
    commands = [
        Command("儀表板", "前往模組", lambda: calls.append("dashboard")),
        Command("檔案搜尋", "前往模組", lambda: calls.append("search")),
        Command("📁 專案", "C:/work", lambda: calls.append("folder")),
    ]
    dialog = CommandPalette(commands)
    try:
        assert dialog.list.count() == 3
        dialog.search.setText("搜尋")
        assert dialog.list.count() == 1
        dialog._activate()
        assert dialog.selected is not None
        assert dialog.selected.label == "檔案搜尋"
    finally:
        dialog.close()
        dialog.deleteLater()
