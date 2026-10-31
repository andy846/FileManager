"""Tests for folder comparison and sync planning."""

import os
import threading
from concurrent.futures import ThreadPoolExecutor
import pytest

from app.core.compare import (
    STATUS_CONTENT_DIFF, STATUS_LEFT_NEWER, STATUS_ONLY_LEFT,
    STATUS_ONLY_RIGHT, STATUS_SIZE_DIFF, STATUS_TYPE_CONFLICT,
    SyncWorker, build_sync_plan, compare_folders,
)


def _write(path, data=b"x", mtime=None):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(data)
    if mtime is not None:
        os.utime(path, (mtime, mtime))


def test_compare_statuses(tmp_path):
    left = tmp_path / "left"
    right = tmp_path / "right"
    left.mkdir()
    right.mkdir()
    _write(str(left / "same.txt"), b"same")
    _write(str(right / "same.txt"), b"same")
    _write(str(left / "only-left.txt"), b"left")
    _write(str(right / "only-right.txt"), b"right")
    _write(str(left / "size.txt"), b"longer")
    _write(str(right / "size.txt"), b"x")
    _write(str(left / "newer.txt"), b"new", mtime=2_000_000_000)
    _write(str(right / "newer.txt"), b"new", mtime=1_900_000_000)
    _write(str(left / "conflict"), b"file")
    (right / "conflict").mkdir()
    _write(str(left / "sub" / "nested.txt"), b"nested")
    _write(str(right / "sub" / "nested.txt"), b"nested")

    result = compare_folders(left, right)
    statuses = {entry.relative: entry.status for entry in result.entries}
    assert statuses["only-left.txt"] == STATUS_ONLY_LEFT
    assert statuses["only-right.txt"] == STATUS_ONLY_RIGHT
    assert statuses["size.txt"] == STATUS_SIZE_DIFF
    assert statuses["newer.txt"] == STATUS_LEFT_NEWER
    assert statuses["conflict"] == STATUS_TYPE_CONFLICT
    assert "same.txt" not in statuses

    shallow = compare_folders(left, right, recursive=False)
    assert all("nested" not in entry.relative for entry in shallow.entries)


def test_compare_hash_detects_same_size_difference(tmp_path):
    left = tmp_path / "left"
    right = tmp_path / "right"
    left.mkdir()
    right.mkdir()
    _write(str(left / "a.txt"), b"aaaa", mtime=1_900_000_000)
    _write(str(right / "a.txt"), b"bbbb", mtime=1_900_000_000)
    plain = compare_folders(left, right)
    assert plain.entries == []
    hashed = compare_folders(left, right, compare_hash=True)
    assert [entry.status for entry in hashed.entries] == [STATUS_CONTENT_DIFF]


def test_sync_plan_and_worker_copy(tmp_path):
    left = tmp_path / "left"
    right = tmp_path / "right"
    left.mkdir()
    right.mkdir()
    _write(str(left / "a.txt"), b"a")
    _write(str(left / "sub" / "b.txt"), b"b")
    _write(str(right / "extra.txt"), b"extra")
    result = compare_folders(left, right)

    plan = build_sync_plan(result, "l2r", mirror=False)
    actions = {action["action"] for action in plan}
    assert "copy" in actions and "mkdir" in actions
    assert all(action["action"] != "delete" for action in plan)

    worker = SyncWorker(plan)
    summaries = []
    worker.completed.connect(summaries.append)
    worker.run()
    assert summaries[0]["failed"] == 0
    assert (right / "a.txt").read_bytes() == b"a"
    assert (right / "sub" / "b.txt").read_bytes() == b"b"

    mirror = build_sync_plan(result, "l2r", mirror=True)
    assert any(action["action"] == "delete"
               and action["relative"] == "extra.txt" for action in mirror)


def test_sync_plan_does_not_delete_without_mirror(tmp_path):
    left = tmp_path / "left"
    right = tmp_path / "right"
    left.mkdir()
    right.mkdir()
    _write(str(right / "extra.txt"), b"x")
    result = compare_folders(left, right)
    plan = build_sync_plan(result, "l2r", mirror=False)
    assert plan == []


def test_sync_worker_reports_conflicts():
    worker = SyncWorker([
        {"action": "conflict", "relative": "same-name",
         "message": "類型衝突"},
    ])
    summaries = []
    worker.completed.connect(summaries.append)
    worker.run()
    assert summaries[0]["conflicts"] == 1
    assert summaries[0]["failed"] == 0


def test_sync_worker_overwrites_newer_target(tmp_path):
    left = tmp_path / "left"
    right = tmp_path / "right"
    left.mkdir()
    right.mkdir()
    _write(str(left / "a.txt"), b"new", mtime=2_000_000_000)
    _write(str(right / "a.txt"), b"old", mtime=1_900_000_000)
    result = compare_folders(left, right)
    plan = build_sync_plan(result, "l2r")
    worker = SyncWorker(plan)
    summaries = []
    worker.completed.connect(summaries.append)
    worker.run()
    assert summaries[0]["copied"] == 1
    assert (right / "a.txt").read_bytes() == b"new"


@pytest.mark.parametrize("directory", [False, True])
def test_mirror_refuses_target_changed_after_preview(tmp_path, monkeypatch, directory):
    from app.core import compare

    left = tmp_path / "left"
    right = tmp_path / "right"
    left.mkdir()
    right.mkdir()
    victim = right / "extra"
    if directory:
        victim.mkdir()
        changed = victim / "child.txt"
    else:
        changed = victim
    changed.write_text("original")
    actions = build_sync_plan(compare_folders(left, right), "l2r", mirror=True)
    changed.write_text("changed by another process")
    monkeypatch.setattr(compare, "send_to_trash", lambda _: pytest.fail("must not delete"))
    worker = SyncWorker(actions)
    summaries = []
    worker.completed.connect(summaries.append)
    worker.run()
    assert summaries[0]["failed"] == 1
    assert changed.read_text() == "changed by another process"


def test_mirror_unchanged_target_is_trashed(tmp_path, monkeypatch):
    from app.core import compare

    left, right = tmp_path / "left", tmp_path / "right"
    left.mkdir()
    right.mkdir()
    victim = right / "extra.txt"
    victim.write_text("original")
    actions = build_sync_plan(compare_folders(left, right), "l2r", mirror=True)
    trashed = []
    monkeypatch.setattr(compare, "send_to_trash", lambda path: (trashed.append(path) or True, ""))
    worker = SyncWorker(actions)
    summaries = []
    worker.completed.connect(summaries.append)
    worker.run()
    assert summaries[0]["deleted"] == 1
    assert len(trashed) == 1


def test_concurrent_mirror_jobs_do_not_trash_same_target_twice(tmp_path, monkeypatch):
    from app.core import compare

    left, right = tmp_path / "left", tmp_path / "right"
    left.mkdir()
    right.mkdir()
    victim = right / "extra.txt"
    victim.write_text("original")
    actions = build_sync_plan(compare_folders(left, right), "l2r", mirror=True)
    barrier = threading.Barrier(2)
    calls = []

    def trash(path):
        calls.append(path)
        os.rename(path, str(tmp_path / "recovered.txt"))
        return True, ""

    monkeypatch.setattr(compare, "send_to_trash", trash)

    def run():
        worker = SyncWorker(actions)
        results = []
        worker.completed.connect(results.append)
        barrier.wait(timeout=5)
        worker.run()
        return results[0]

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(run) for _ in range(2)]
        results = [future.result(timeout=10) for future in futures]
    assert len(calls) == 1
    assert sum(result["deleted"] for result in results) == 1
    assert sum(result["failed"] for result in results) == 1
    assert (tmp_path / "recovered.txt").read_text() == "original"


def test_mirror_rechecks_source_after_target_snapshot(tmp_path, monkeypatch):
    from app.core import compare

    left, right = tmp_path / "left", tmp_path / "right"
    left.mkdir()
    right.mkdir()
    victim = right / "extra.txt"
    victim.write_text("original")
    actions = build_sync_plan(compare_folders(left, right), "l2r", mirror=True)
    snapshot = compare._snapshot_delete_target

    def concurrent_source(*args, **kwargs):
        result = snapshot(*args, **kwargs)
        (left / "extra.txt").write_text("new")
        return result

    monkeypatch.setattr(compare, "_snapshot_delete_target", concurrent_source)
    monkeypatch.setattr(compare, "send_to_trash", lambda _: pytest.fail("must not delete"))
    worker = SyncWorker(actions)
    summaries = []
    worker.completed.connect(summaries.append)
    worker.run()
    assert summaries[0]["failed"] == 1
    assert victim.read_text() == "original"


def test_mirror_cancel_while_waiting_for_delete_lock(tmp_path, monkeypatch):
    from app.core import compare
    from app.core.workers import OperationControl

    left, right = tmp_path / "left", tmp_path / "right"
    left.mkdir()
    right.mkdir()
    victim = right / "extra.txt"
    victim.write_text("original")
    actions = build_sync_plan(compare_folders(left, right), "l2r", mirror=True)
    monkeypatch.setattr(compare, "send_to_trash", lambda _: pytest.fail("must not delete"))
    control = OperationControl()
    worker = SyncWorker(actions, control=control)
    summaries = []
    worker.completed.connect(summaries.append)
    started = threading.Event()

    def run():
        started.set()
        worker.run()

    compare._MIRROR_DELETE_LOCK.acquire()
    try:
        thread = threading.Thread(target=run)
        thread.start()
        assert started.wait(2)
        control.cancel()
        thread.join(timeout=3)
        assert not thread.is_alive()
    finally:
        compare._MIRROR_DELETE_LOCK.release()
    # Queued Qt signals may not be delivered without an event loop; the file
    # itself verifies that cancellation prevented the destructive operation.
    assert victim.read_text() == "original"
