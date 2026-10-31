"""Integration smoke test: the shell builds every module and can switch."""

from app.core.constants import (
    MODULE_BROWSER, MODULE_COMPARE, MODULE_COPY, MODULE_DASHBOARD,
    MODULE_MOVE, MODULE_SEARCH, MODULE_SETTINGS,
)


class _FakeQ:
    def __init__(self, path):
        self._path = str(path)

    def fileName(self):
        return self._path

    def sync(self):
        pass


class _FakeSettings:
    """Keep the smoke test away from the user's real QSettings file."""

    def __init__(self, path):
        self.q = _FakeQ(path)
        self.data = {}
        self.recent_data = {}
        self.geometry = None

    def option(self, name, default):
        return self.data.get(name, default)

    def set_option(self, name, value):
        self.data[name] = value

    def set_options(self, values):
        self.data.update(values)

    def value(self, name, default=None):
        return self.data.get(name, default)

    def set_value(self, name, value):
        self.data[name] = value

    def recent(self, name):
        return list(self.recent_data.get(name, []))

    def remember_path(self, name, path):
        paths = self.recent_data.setdefault(name, [])
        if path in paths:
            paths.remove(path)
        paths.insert(0, path)

    def save_geometry(self, data):
        self.geometry = data

    def load_geometry(self):
        return self.geometry


def test_main_window_builds_all_pages(app, tmp_path):
    from app.ui.main_window import MainWindow

    window = MainWindow(_FakeSettings(tmp_path / "settings.ini"))
    try:
        assert window.nav.topLevelItemCount() == 3
        assert len(window._all_nav_items()) == 11
        assert window.stack.count() == 11
        for item in window._all_nav_items():
            window.nav.setCurrentItem(item)
        # Dashboard is the default landing page.
        window.goto_module(MODULE_DASHBOARD)
        assert window.stack.currentWidget().module_id == MODULE_DASHBOARD
        assert window.pages[0].module_id == MODULE_DASHBOARD
        # goto_module resolves module ids to the right page.
        for module_id in (
            MODULE_COPY, MODULE_BROWSER, MODULE_SEARCH,
            MODULE_COMPARE, MODULE_SETTINGS,
        ):
            window.goto_module(module_id)
            assert window.stack.currentWidget() is window.pages_by_id[module_id]
        # The legacy move id maps to the merged page and preselects move.
        window.goto_module(MODULE_MOVE)
        merged = window.pages_by_id[MODULE_COPY]
        assert window.stack.currentWidget() is merged
        assert merged.operation == "move"
        # Clicking a group heading must not steal the current page selection.
        window.goto_module(MODULE_BROWSER)
        window.nav.setCurrentItem(window.nav.topLevelItem(0))
        assert window.nav.currentItem() is window._find_nav_item(MODULE_BROWSER)
        assert window.stack.currentWidget() is window.pages_by_id[MODULE_BROWSER]
        # Sidebar collapses to an icon rail and restores.
        assert window.compact_nav.count() == 13
        assert window.collapse_btn.width() == 196
        window._toggle_sidebar()
        assert window.sidebar.width() == 64
        assert window.compact_nav.isHidden() is False
        assert window.nav.isHidden() is True
        assert window.collapse_btn.width() == 40
        assert "Ctrl+B" in window.collapse_btn.toolTip()
        window._toggle_sidebar()
        assert window.sidebar.width() == 216
        assert window.nav.isHidden() is False
        assert window.compact_nav.isHidden() is True
        assert window.collapse_btn.width() == 196
    finally:
        window.close()
