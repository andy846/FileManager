from app.modules.remover.scanner import scan_files


def _dt(y, m, d):
    from PyQt6.QtCore import QDate

    return QDate(y, m, d)


def test_scan_ext(sample_tree):
    results = scan_files(str(sample_tree), ["pdf"], {}, recursive=True)
    # pdf, sub/deep.pdf, backup.PDF
    assert len(results) == 3


def test_scan_size_filter(sample_tree):
    results = scan_files(str(sample_tree), ["pdf"], {"size_op": ">=", "size_value": 2.5, "size_unit": "MB"}, recursive=True)
    # only sub/deep.pdf (3MB) qualifies
    assert len(results) == 1


def test_scan_date_filter(sample_tree):
    results = scan_files(
        str(sample_tree), ["txt"], {"date_from": _dt(2000, 1, 1), "date_to": _dt(2100, 1, 1)}, recursive=True)
    assert len(results) == 2


def test_scan_exclude(sample_tree):
    results = scan_files(
        str(sample_tree), [], {"exclude_patterns": ["*.pdf"]}, recursive=True)
    assert all(not r.name.lower().endswith(".pdf") for r in results)
    assert len(results) > 0


def test_scan_nonexistent():
    import pytest

    with pytest.raises(FileNotFoundError):
        scan_files("C:\\nonexistent_path_xyz", [], {})


def test_delete_cancel_returns_partial(tmp_path):
    from app.modules.remover.deleter import delete_files
    from app.core.workers import CancelledError, OperationControl

    files = []
    for i in range(20):
        p = tmp_path / f"f{i}.txt"
        p.write_text("x")
        files.append(p)
    ctrl = OperationControl()
    calls = {"n": 0}

    def checker():
        calls["n"] += 1
        if calls["n"] > 3:
            ctrl.cancel()
            raise CancelledError("cancelled")

    deleted, failed = delete_files(files, cancel_check=checker, threads=1)
    # Must not raise; returns whatever was processed before cancel.
    assert isinstance(deleted, list)
    assert isinstance(failed, list)
    assert len(deleted) + len(failed) <= len(files)

