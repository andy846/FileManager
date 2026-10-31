"""Regression tests for destructive operations and cancellation safety."""

import os
import pathlib
import threading
import zipfile
from io import BytesIO
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.core.archive import create_zip, extract_archive
from app.core.compare import CompareResult, SyncWorker, build_sync_plan
from app.core.models import CopyTask, STATUS_FAILED
from app.core.transfer import DestinationExistsError, copy_file, move_file
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
    worker._process(task, threading.Lock(),
                    {"done": 0, "skipped": 0, "failed": 0,
                     "cancelled": 0, "bytes": 0})
    assert task.status == STATUS_FAILED
    assert target.read_text() == "old"
    assert source.read_text() == "new"


def test_skip_mode_never_overwrites_existing_destination(tmp_path):
    source = tmp_path / "new.bin"
    target = tmp_path / "existing.bin"
    source.write_bytes(b"NEW")
    target.write_bytes(b"ORIGINAL")
    with pytest.raises(DestinationExistsError):
        copy_file(str(source), str(target), conflict="skip", verify="off")
    assert target.read_bytes() == b"ORIGINAL"
    assert source.read_bytes() == b"NEW"


def test_concurrent_skip_commits_exactly_once(tmp_path):
    source_a = tmp_path / "a.bin"
    source_b = tmp_path / "b.bin"
    target = tmp_path / "shared.bin"
    source_a.write_bytes(b"A" * 500_000)
    source_b.write_bytes(b"B" * 500_000)

    results = []
    barrier = threading.Barrier(2)

    def run(source):
        barrier.wait(timeout=5)
        try:
            copy_file(str(source), str(target), conflict="skip",
                      verify="off")
            results.append("ok")
        except DestinationExistsError:
            results.append("exists")

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(run, s) for s in (source_a, source_b)]
        for future in futures:
            future.result(timeout=10)

    assert sorted(results) == ["exists", "ok"]
    assert target.read_bytes() in (source_a.read_bytes(), source_b.read_bytes())


def test_concurrent_rename_commits_unique_destinations(tmp_path):
    source_a = tmp_path / "a.bin"
    source_b = tmp_path / "b.bin"
    target = tmp_path / "shared.bin"
    source_a.write_bytes(b"A" * 200_000)
    source_b.write_bytes(b"B" * 200_000)

    committed = []
    lock = threading.Lock()

    def on_commit(final):
        with lock:
            committed.append(final)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(
                copy_file, str(src), str(target), conflict="rename",
                verify="off", on_commit=on_commit,
            )
            for src in (source_a, source_b)
        ]
        for future in futures:
            future.result(timeout=10)

    assert len(committed) == 2
    assert len(set(os.path.normcase(p) for p in committed)) == 2
    contents = sorted(pathlib.Path(p).read_bytes() for p in committed)
    assert contents == sorted((source_a.read_bytes(), source_b.read_bytes()))


def test_move_skip_mode_keeps_source_when_destination_exists(tmp_path):
    source = tmp_path / "move.bin"
    target = tmp_path / "exists.bin"
    source.write_bytes(b"NEW")
    target.write_bytes(b"ORIGINAL")
    with pytest.raises(DestinationExistsError):
        move_file(str(source), str(target), conflict="skip", verify="off")
    assert source.read_bytes() == b"NEW"
    assert target.read_bytes() == b"ORIGINAL"


def test_overwrite_backup_failure_preserves_destination(tmp_path):
    source = tmp_path / "new.bin"
    target = tmp_path / "existing.bin"
    source.write_bytes(b"NEW")
    target.write_bytes(b"ORIGINAL")

    def fail_backup(path):
        raise RuntimeError("backup refused")

    with pytest.raises(RuntimeError, match="backup refused"):
        copy_file(
            str(source), str(target), conflict="overwrite", verify="off",
            backup_overwrite=fail_backup,
        )
    assert target.read_bytes() == b"ORIGINAL"
    assert not list(tmp_path.glob("*.tmp~"))


def test_interrupted_cross_volume_move_keeps_both_copies(
        tmp_path, monkeypatch):
    import app.core.transfer as transfer

    monkeypatch.setattr(transfer, "_same_device", lambda _s, _d: False)
    source = tmp_path / "src.bin"
    target_dir = tmp_path / "dest"
    target_dir.mkdir()
    target = target_dir / "src.bin"
    source.write_bytes(b"data" * 1000)
    control = OperationControl()

    def cancel_after_commit(final):
        control.cancel()

    with pytest.raises(CancelledError):
        move_file(
            str(source), str(target), control=control, verify="off",
            on_commit=cancel_after_commit,
        )
    # Neither copy may be lost when the source removal is interrupted.
    assert source.read_bytes() == b"data" * 1000
    assert target.read_bytes() == b"data" * 1000


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


def test_delete_cancellation_audit_reconciles_all_paths(tmp_path):
    paths = []
    for index in range(50):
        path = tmp_path / f"keep_{index:03d}.txt"
        path.write_text("keep")
        paths.append(str(path))
    control = OperationControl()

    def on_progress(done, _total):
        if done == 1:
            control.cancel()

    deleted, failed, cancelled = delete_files(
        paths, permanent=True, threads=2, cancel_check=control.checkpoint,
        progress_callback=on_progress, include_cancelled=True,
    )
    assert not failed
    assert len(deleted) + len(cancelled) == len(paths)
    assert set(deleted).isdisjoint(set(cancelled))
    for path in cancelled:
        assert os.path.exists(path)
    for path in deleted:
        assert not os.path.exists(path)


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


def test_mirror_delete_aborts_when_source_root_is_gone(tmp_path, monkeypatch):
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()
    victim = target / "extra.txt"
    victim.write_text("keep")
    actions = [{
        "action": "delete",
        "dst": str(victim),
        "relative": "extra.txt",
        "source_root": str(source),
        "target_root": str(target),
    }]
    # Source vanished between scan and execution.
    import shutil
    shutil.rmtree(source)
    import app.core.compare as compare_module
    monkeypatch.setattr(
        compare_module, "send_to_trash",
        lambda _p: (_ for _ in ()).throw(AssertionError("must not trash")),
    )
    worker = SyncWorker(actions)
    summaries = []
    worker.completed.connect(summaries.append)
    worker.run()
    assert summaries[0]["failed"] == 1
    assert summaries[0]["deleted"] == 0
    assert victim.exists()


def test_mirror_delete_rejects_target_escape(tmp_path, monkeypatch):
    source = tmp_path / "source"
    target = tmp_path / "target"
    outside = tmp_path / "outside.txt"
    source.mkdir()
    target.mkdir()
    outside.write_text("keep")
    actions = [{
        "action": "delete",
        "dst": str(outside),
        "relative": "outside.txt",
        "source_root": str(source),
        "target_root": str(target),
    }]
    import app.core.compare as compare_module
    monkeypatch.setattr(
        compare_module, "send_to_trash",
        lambda _p: (_ for _ in ()).throw(AssertionError("must not trash")),
    )
    worker = SyncWorker(actions)
    summaries = []
    worker.completed.connect(summaries.append)
    worker.run()
    assert summaries[0]["failed"] == 1
    assert outside.exists()


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


def test_archive_rejects_windows_reserved_and_trailing_names():
    from app.core.archive import sanitize_member

    for name in ("CON.txt", "NUL", "aux.log", "folder/COM1.txt",
                 "LPT2", "folder/PRN"):
        assert sanitize_member(name) is None, name
    assert sanitize_member("normal.txt") == "normal.txt"


def test_member_stream_cannot_exceed_declared_size(tmp_path):
    from app.core.archive import _write_stream_atomically

    target = tmp_path / "out.bin"
    source = BytesIO(b"x" * 10)
    with pytest.raises(ValueError, match="宣告大小"):
        _write_stream_atomically(source, str(target), max_bytes=5)
    assert not target.exists()
    assert not list(tmp_path.glob(".fm-extract-*.part"))


def test_extraction_failure_records_and_preserves_old_file(
        tmp_path, monkeypatch):
    import app.core.archive as archive_module

    archive_path = tmp_path / "one.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("existing.txt", b"new-content")
    dest = tmp_path / "dest"
    dest.mkdir()
    target = dest / "existing.txt"
    target.write_bytes(b"ORIGINAL")

    def broken_writer(source, path, control=None, max_bytes=None):
        raise OSError("disk full")

    monkeypatch.setattr(
        archive_module, "_write_stream_atomically", broken_writer
    )
    result = extract_archive(str(archive_path), str(dest), overwrite=True)
    assert result["failed"] == 1
    assert result["extracted"] == 0
    assert target.read_bytes() == b"ORIGINAL"
