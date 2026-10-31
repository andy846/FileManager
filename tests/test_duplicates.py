from app.modules.duplicates.scanner import find_duplicates


def test_find_duplicates(tmp_path):
    (tmp_path / "a.txt").write_text("hello world")
    (tmp_path / "b.txt").write_text("hello world")
    (tmp_path / "c.txt").write_text("different content")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "d.txt").write_text("hello world")
    groups = find_duplicates(str(tmp_path), recursive=True)
    # one group: a, b, sub/d (3 identical)
    assert len(groups) == 1
    assert len(groups[0].files) == 3


def test_no_duplicates(tmp_path):
    (tmp_path / "a.txt").write_text("aaa")
    (tmp_path / "b.txt").write_text("bbb")
    groups = find_duplicates(str(tmp_path), recursive=True)
    assert groups == []


def test_zero_bytes_excluded(tmp_path):
    (tmp_path / "a.txt").write_text("")
    (tmp_path / "b.txt").write_text("")
    groups = find_duplicates(str(tmp_path), recursive=True)
    assert groups == []


def test_prefix_collision_uses_full_hash(tmp_path):
    # Files larger than the 64 KiB quick-hash window whose first blocks are
    # identical must be disambiguated by the full-hash pass.
    head = b"A" * 65536
    (tmp_path / "x.bin").write_bytes(head + b"1" * 100)
    (tmp_path / "y.bin").write_bytes(head + b"2" * 100)
    assert find_duplicates(str(tmp_path), recursive=True) == []

    # An exact-content twin must still be detected.
    (tmp_path / "z.bin").write_bytes(head + b"1" * 100)
    groups = find_duplicates(str(tmp_path), recursive=True)
    assert len(groups) == 1
    assert len(groups[0].files) == 2


def test_find_duplicates_reports_scan_quick_full_phases(tmp_path):
    data = b"A" * (65536 + 512)
    (tmp_path / "a.bin").write_bytes(data)
    (tmp_path / "b.bin").write_bytes(data)

    updates = []
    find_duplicates(
        str(tmp_path), recursive=True, progress_callback=updates.append
    )

    phases = [update.phase for update in updates]
    assert "scan" in phases
    assert "quick" in phases
    assert "full" in phases

    quick = [update for update in updates if update.phase == "quick"]
    assert quick[-1].done == quick[-1].total == 2

    full = [update for update in updates if update.phase == "full"]
    assert full[-1].total == 2 * len(data)
    assert full[-1].done == full[-1].total > 0
    assert updates[-1].phase == "full"


def test_find_duplicates_cancel(tmp_path):
    from app.core.workers import CancelledError, OperationControl

    for i in range(30):
        (tmp_path / f"f{i}.txt").write_text("content")
    ctrl = OperationControl()
    calls = {"n": 0}

    def checker():
        calls["n"] += 1
        if calls["n"] > 2:
            ctrl.cancel()
            raise CancelledError("cancelled")

    # Must not raise; returns whatever was processed before cancel.
    groups = find_duplicates(str(tmp_path), recursive=True,
                             cancel_check=checker)
    assert isinstance(groups, list)
