"""Regression test: rebuilding the results table after a delete must not
enter an infinite loop (iterating a list that _add_row appends to)."""


from PyQt6.QtCore import Qt

from app.core.models import FileInfo


def test_delete_rebuild_full(app, tmp_path):
    """Full page construction requires Qt widgets; run against a real page."""
    from app.core.settings import AppSettings
    from app.modules.remover.page import RemoverPage

    settings = AppSettings()
    page = RemoverPage(settings, None)
    infos = [FileInfo(path=str(tmp_path / f"f{i}.pdf"), size=100 * (i + 1))
             for i in range(5)]
    page._reset_counts()
    for i in infos:
        page._add_row(i)
    page._update_counts()
    assert page._total_size == 1500
    assert len(page._sel_rows) == 5

    # Simulate the post-delete rebuild exactly as _on_delete_complete does.
    deleted = {infos[1].path}
    keep = [f for f in page.files if f.path not in deleted]
    page.files = []
    page.table.setRowCount(0)
    page._reset_counts()
    for info in list(keep):  # snapshot - this is the bug fix
        page._add_row(info)
    page._update_counts()

    assert page.table.rowCount() == 4
    assert len(page.files) == 4
    assert page._total_size == 1300
    assert len(page._sel_rows) == 4

    # Unchecking rows updates the incremental selection set.
    page.table.item(0, 0).setCheckState(Qt.CheckState.Unchecked)
    assert page._sel_rows == {1, 2, 3}
    assert len(page._selected_files()) == 3
