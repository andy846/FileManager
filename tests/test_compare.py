"""Tests for folder comparison and sync planning."""

import os

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
