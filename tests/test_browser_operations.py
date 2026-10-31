"""Tests for browser file operations (copy/move planning and execution)."""

import pytest

from app.modules.browser.operations import (
    FileOpsWorker, build_plan, unique_path,
)


def _run(worker):
    summaries = []
    worker.completed.connect(summaries.append)
    worker.run()
    assert summaries
    return summaries[0]


def test_unique_path(tmp_path):
    target = tmp_path / "file.txt"
    target.write_text("a", encoding="utf-8")
    first = unique_path(target)
    assert first.endswith("file (1).txt")
    open(first, "w", encoding="utf-8").write("b")
    assert unique_path(target).endswith("file (2).txt")


def test_build_plan_files_and_directories(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "a.txt").write_text("a", encoding="utf-8")
    (source / "empty").mkdir()
    (source / "nested").mkdir()
    (source / "nested" / "b.txt").write_text("bb", encoding="utf-8")
    dest = tmp_path / "dest"
    dest.mkdir()

    plan, source_dirs = build_plan([source], dest)
    files = [entry for entry in plan if entry["kind"] == "file"]
    assert len(files) == 2
    assert str(source) in source_dirs


def test_build_plan_rejects_folder_into_itself(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    with pytest.raises(ValueError):
        build_plan([source], source)


def test_build_plan_rejects_copy_into_same_parent(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    with pytest.raises(ValueError):
        build_plan([source], tmp_path)

    file_path = tmp_path / "a.txt"
    file_path.write_text("a", encoding="utf-8")
    with pytest.raises(ValueError):
        build_plan([file_path], tmp_path)


def test_parallel_copy_of_many_files(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    files = []
    for index in range(20):
        path = source / f"file-{index}.txt"
        path.write_text(f"value-{index}", encoding="utf-8")
        files.append(path)
    dest = tmp_path / "dest"
    dest.mkdir()

    worker = FileOpsWorker(
        "copy", files, dest, conflict="skip", threads=4,
        verify_mode="quick",
    )
    summary = _run(worker)
    assert summary["done"] == 20
    assert summary["failed"] == 0
    for index in range(20):
        assert (dest / f"file-{index}.txt").read_text(encoding="utf-8") == (
            f"value-{index}"
        )


def test_copy_file_and_folder_preserves_source(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "a.txt").write_text("hello", encoding="utf-8")
    (source / "empty").mkdir()
    dest = tmp_path / "dest"
    dest.mkdir()

    worker = FileOpsWorker("copy", [source], dest, conflict="skip")
    summary = _run(worker)
    assert summary["failed"] == 0
    assert summary["done"] == 1
    assert (dest / "source" / "a.txt").read_text(encoding="utf-8") == "hello"
    assert (dest / "source" / "empty").is_dir()
    assert (source / "a.txt").exists()


def test_move_removes_source(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "a.txt").write_text("hello", encoding="utf-8")
    nested = source / "nested"
    nested.mkdir()
    (nested / "b.txt").write_text("world", encoding="utf-8")
    dest = tmp_path / "dest"
    dest.mkdir()

    worker = FileOpsWorker("move", [source], dest, conflict="skip")
    summary = _run(worker)
    assert summary["failed"] == 0
    assert summary["done"] == 2
    assert not source.exists()
    assert (dest / "source" / "a.txt").exists()
    assert (dest / "source" / "nested" / "b.txt").exists()


def test_conflict_skip_and_rename(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "a.txt").write_text("new", encoding="utf-8")
    dest = tmp_path / "dest"
    dest.mkdir()
    (dest / "source").mkdir()
    (dest / "source" / "a.txt").write_text("old", encoding="utf-8")

    worker = FileOpsWorker("copy", [source], dest, conflict="skip")
    summary = _run(worker)
    assert summary["skipped"] == 1
    assert (dest / "source" / "a.txt").read_text(encoding="utf-8") == "old"

    worker = FileOpsWorker("copy", [source], dest, conflict="rename")
    summary = _run(worker)
    assert summary["done"] == 1
    assert (dest / "source" / "a (1).txt").read_text(encoding="utf-8") == "new"


def test_move_keeps_skipped_files(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "a.txt").write_text("new", encoding="utf-8")
    dest = tmp_path / "dest"
    dest.mkdir()
    (dest / "source").mkdir()
    (dest / "source" / "a.txt").write_text("old", encoding="utf-8")

    worker = FileOpsWorker("move", [source], dest, conflict="skip")
    summary = _run(worker)
    assert summary["skipped"] == 1
    assert (source / "a.txt").exists()
    assert (dest / "source" / "a.txt").read_text(encoding="utf-8") == "old"


def test_operation_dialog_copies(app, tmp_path):
    from PyQt6.QtTest import QTest

    from app.core.i18n import set_language
    from app.modules.browser.operations import OperationDialog

    set_language("zh_TW")
    source = tmp_path / "a.txt"
    source.write_text("hello", encoding="utf-8")
    dest = tmp_path / "dest"
    dest.mkdir()

    dialog = OperationDialog(None, "copy", [source], str(dest))
    try:
        dialog.start()
        dialog.worker.wait(5000)
        QTest.qWait(100)
        assert (dest / "a.txt").read_text(encoding="utf-8") == "hello"
        assert "完成 1" in dialog.status.text()
    finally:
        dialog.close()
        dialog.deleteLater()
        set_language("en")
