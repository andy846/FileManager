"""Regression tests for destructive operations and cancellation safety."""

import threading
import zipfile
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.core.archive import create_zip, extract_archive
from app.core.compare import CompareResult, build_sync_plan
from app.core.models import CopyTask, STATUS_FAILED
from app.core.workers import CancelledError, OperationControl
from app.modules.remover.deleter import delete_files


def test_cancel_wakes_paused_worker():
    control = OperationControl()
    control.pause()
    finished = threading.Event()
    thread = threading.Thread(
        target=lambda: (control.wait_if_paused(), finished.set()), daemon=True
    )
    thread.start()
    assert not finished.wait(0.05)
    control.cancel()
    assert finished.wait(1)
    thread.join(timeout=1)


def test_concurrent_copies_have_distinct_temp_files(tmp_path, monkeypatch):
    import app.core.transfer as transfer

    src_a = tmp_path / "a.bin"
    src_b = tmp_path / "b.bin"
    src_a.write_bytes(b"A" * 200_000)
    src_b.write_bytes(b"B" * 200_000)
    dst = tmp_path / "result.bin"
    barrier = threading.Barrier(2)
    temps = set()
    lock = threading.Lock()
    actual_copy = transfer._copy_python

    monkeypatch.setattr(transfer, "_copy_native", lambda *_: False)

    def spy_copy(src, temp, control, chunk_size=transfer.COPY_CHUNK_SIZE):
        with lock:
            temps.add(temp)
        barrier.wait(timeout=5)
        return actual_copy(src, temp, control, chunk_size)

    monkeypatch.setattr(transfer, "_copy_python", spy_copy)
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(transfer.copy_file, str(src), str(dst), verify="off")
            for src in (src_a, src_b)
        ]
        for future in futures:
            future.result(timeout=10)

    assert len(temps) == 2
    assert dst.read_bytes() in (src_a.read_bytes(), src_b.read_bytes())
    assert all(not __import__("os").path.exists(temp) for temp in temps)


def test_failed_trash_backup_prevents_overwrite(app, tmp_path, monkeypatch):
    from app.modules.copier import worker as copier

    source = tmp_path / "new.txt"
    target = tmp_path / "existing.txt"
    source.write_text("new")
    target.write_text("old")
    task = CopyTask(id=1, src=str(source), dst=str(target), size=3)
    monkeypatch.setattr(copier, "send_to_trash", lambda _p: (False, "blocked"))
    worker = copier.TransferWorker(
        OperationControl(), [task],
        {"conflict_mode": "overwrite", "to_trash_on_overwrite": True},
    )
    worker._process(task, threading.Lock(), threading.Lock(), {"bytes": 0})
    assert task.status == STATUS_FAILED
    assert target.read_text() == "old"
    assert source.read_text() == "new"


def test_delete_cancel_stops_submitting_and_audits_completed(tmp_path):
    paths = []
    for index in range(40):
        path = tmp_path / f"file_{index:03d}.txt"
        path.write_text("keep")
        paths.append(str(path))
    control = OperationControl()

    def on_progress(done, _total):
        if done == 1:
            control.cancel()

    deleted, failed = delete_files(
        paths, permanent=True, threads=2, cancel_check=control.checkpoint,
        progress_callback=on_progress,
    )
    assert 1 <= len(deleted) <= 2
    assert not failed
    assert {p for p in paths if not __import__("os").path.exists(p)} == set(deleted)


def test_sync_rejects_overlapping_roots(tmp_path):
    left = tmp_path / "data"
    right = left / "backup"
    right.mkdir(parents=True)
    result = CompareResult(left=str(left), right=str(right))
    with pytest.raises(ValueError, match="不可相同"):
        build_sync_plan(result, "l2r", mirror=False)


def test_mirror_rejects_incomplete_scan(tmp_path):
    left = tmp_path / "left"
    right = tmp_path / "right"
    left.mkdir()
    right.mkdir()
    result = CompareResult(left=str(left), right=str(right), errors=1)
    with pytest.raises(ValueError, match="無法讀取"):
        build_sync_plan(result, "l2r", mirror=True)


def test_cancelled_extraction_keeps_original_file(tmp_path):
    archive_path = tmp_path / "new.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("existing.txt", b"x" * (3 * 1024 * 1024))
    dest = tmp_path / "dest"
    dest.mkdir()
    target = dest / "existing.txt"
    target.write_bytes(b"ORIGINAL")

    class CancelAfterTwoChecks:
        def __init__(self):
            self.count = 0

        def wait_if_paused(self):
            pass

        def checkpoint(self):
            self.count += 1
            if self.count >= 3:
                raise CancelledError("stop")

    result = extract_archive(
        str(archive_path), str(dest), overwrite=True,
        control=CancelAfterTwoChecks(),
    )
    assert result["cancelled"] is True
    assert target.read_bytes() == b"ORIGINAL"
    assert not list(dest.glob(".fm-extract-*.part"))


def test_cancelled_zip_creation_preserves_existing_archive(tmp_path):
    output = tmp_path / "result.zip"
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("original.txt", "keep")
    original = output.read_bytes()
    source = tmp_path / "source"
    source.mkdir()
    (source / "a.txt").write_text("a")
    (source / "b.txt").write_text("b")
    control = OperationControl()

    result = create_zip(
        str(output), [str(source)], control=control,
        progress=lambda *_: control.cancel(),
    )
    assert result["cancelled"] is True
    assert result["committed"] is False
    assert output.read_bytes() == original
    assert not list(tmp_path.glob(".fm-zip-*.part"))


def test_archive_rejects_symlink_directory_escape(tmp_path):
    from app.core.archive import _safe_target

    dest = tmp_path / "dest"
    outside = tmp_path / "outside"
    dest.mkdir()
    outside.mkdir()
    try:
        (dest / "link").symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("Directory symlinks unavailable on this host")
    assert _safe_target(str(dest), "link/escape.txt") is None
