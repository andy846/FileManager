"""Path normalisation and UNC-awareness tests."""

from app.core.utils import (
    extended_path, is_unc_path, is_unc_server_root, normalize_path, path_name,
    server_from_path, short_path,
)


def test_normalize_mixed_windows_path():
    mixed = "C:/Users/example/Desktop/Desktop2\\CCBA\\file.xls"
    assert normalize_path(mixed) == (
        "C:\\Users\\example\\Desktop\\Desktop2\\CCBA\\file.xls"
    )


def test_normalize_unc_and_drive_root():
    assert normalize_path("//server/share/folder") == (
        "\\\\server\\share\\folder"
    )
    assert normalize_path("\\\\server\\share\\") == "\\\\server\\share"
    assert normalize_path("C:/") == "C:\\"
    assert normalize_path("") == ""


def test_unc_helpers():
    assert is_unc_path("//server/share/folder")
    assert is_unc_server_root("\\\\server")
    assert not is_unc_server_root("\\\\server\\share")
    assert server_from_path("\\\\server\\share\\folder") == "\\\\server"
    assert server_from_path("C:\\temp") == ""


def test_extended_path_prefixes_windows_paths():
    assert extended_path("C:\\temp\\file.txt") == "\\\\?\\C:\\temp\\file.txt"
    assert extended_path("\\\\server\\share\\file.txt") == (
        "\\\\?\\UNC\\server\\share\\file.txt"
    )


def test_path_name_handles_unc_and_drive_roots():
    assert path_name("C:\\") == "C:\\"
    assert path_name("\\\\server\\share") == "share"
    assert path_name("\\\\server\\share\\folder") == "folder"


def test_short_path_uses_native_separators():
    text = short_path("C:/Users/example/Desktop/Desktop2\\CCBA\\file.xls")
    assert "/" not in text
    assert text == "C:\\Users\\example\\Desktop\\Desktop2\\CCBA\\file.xls"


def test_path_field_normalizes_input(app, tmp_path):
    from app.ui.widgets import PathField

    field = PathField()
    try:
        mixed = str(tmp_path).replace("\\", "/") + "\\sub"
        field.set_path(mixed)
        assert field.text() == normalize_path(mixed)
        assert "/" not in field.text()
    finally:
        field.deleteLater()


def test_browser_filter_keeps_current_folder_visible(app, tmp_path):
    from PyQt6.QtTest import QTest

    try:
        from PyQt6.QtGui import QFileSystemModel
    except ImportError:  # pragma: no cover - older PyQt6
        from PyQt6.QtWidgets import QFileSystemModel

    from app.modules.browser.pane import BrowserPane

    folder = tmp_path / "filter"
    folder.mkdir()
    (folder / "alpha.txt").write_text("a", encoding="utf-8")
    (folder / "beta.txt").write_text("b", encoding="utf-8")
    (folder / "gamma.log").write_text("c", encoding="utf-8")
    model = QFileSystemModel()
    model.setRootPath("")
    pane = BrowserPane(model)
    try:
        assert pane.navigate(str(folder))
        QTest.qWait(600)
        assert pane.proxy.rowCount(pane.view.rootIndex()) == 3
        pane.filter_edit.setText("beta")
        QTest.qWait(300)
        assert pane.proxy.rowCount(pane.view.rootIndex()) == 1
        pane.filter_edit.clear()
        QTest.qWait(300)
        assert pane.proxy.rowCount(pane.view.rootIndex()) == 3
    finally:
        pane.deleteLater()
        model.deleteLater()


def test_thumbnail_provider_is_lazy_by_default(app):
    from app.modules.browser.thumbnails import ThumbnailIconProvider

    provider = ThumbnailIconProvider()
    assert provider._thumbnails_enabled is False


def test_network_dialog_ignores_local_initial_path(app, tmp_path):
    from app.ui.network_dialog import NetworkLocationDialog

    dialog = NetworkLocationDialog(None, initial=str(tmp_path))
    try:
        assert dialog.server_edit.text() == ""
    finally:
        dialog.deleteLater()


def test_browser_pane_navigates_mixed_path(app, tmp_path):
    try:
        from PyQt6.QtGui import QFileSystemModel
    except ImportError:  # pragma: no cover - older PyQt6
        from PyQt6.QtWidgets import QFileSystemModel

    from app.modules.browser.pane import BrowserPane

    folder = tmp_path / "browse"
    folder.mkdir()
    model = QFileSystemModel()
    model.setRootPath("")
    pane = BrowserPane(model)
    try:
        mixed = str(folder).replace("\\", "/")
        assert pane.navigate(mixed)
        assert pane.current_path == normalize_path(str(folder))
        assert "/" not in pane.path_edit.text()
    finally:
        pane.deleteLater()
        model.deleteLater()
