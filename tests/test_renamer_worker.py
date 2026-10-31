"""Tests for the background rename preview/apply workers."""

import os


def test_apply_worker_allows_case_only_rename(app, tmp_path):
    """On case-insensitive filesystems the target "exists" already."""
    from app.modules.renamer.page import RenameApplyWorker

    src = tmp_path / "file.txt"
    src.write_text("x")
    dst = tmp_path / "FILE.txt"

    result = {}
    worker = RenameApplyWorker([(str(src), str(dst))])
    worker.done.connect(lambda changed, failures: result.update(
        changed=changed, failures=failures))
    worker.run()  # synchronous

    assert result["changed"] == 1
    assert result["failures"] == []
    assert dst.exists()


def test_apply_worker_skips_real_collision(app, tmp_path):
    from app.modules.renamer.page import RenameApplyWorker

    a = tmp_path / "a.txt"
    b = tmp_path / "b.txt"
    a.write_text("A")
    b.write_text("B")

    result = {}
    worker = RenameApplyWorker([(str(a), str(b))])
    worker.done.connect(lambda changed, failures: result.update(
        changed=changed, failures=failures))
    worker.run()

    assert result["changed"] == 0
    assert len(result["failures"]) == 1
    assert b.read_text() == "B"  # existing file untouched


def test_scan_then_apply_uses_exact_mapping(app, tmp_path):
    from app.modules.renamer.page import RenameScanWorker, RenameApplyWorker

    (tmp_path / "b.txt").write_text("x")
    (tmp_path / "a.txt").write_text("y")
    pattern = {"mode": "number", "prefix": "img_", "suffix": "",
               "start": 1, "pad": 3, "keep_ext": True}

    pairs = {}
    scanner = RenameScanWorker(str(tmp_path), pattern, True)
    scanner.preview_ready.connect(lambda p: pairs.setdefault("p", p))
    scanner.run()
    assert len(pairs["p"]) == 2

    result = {}
    applier = RenameApplyWorker(pairs["p"])
    applier.done.connect(lambda changed, failures: result.update(
        changed=changed, failures=failures))
    applier.run()

    assert result["changed"] == 2
    new_names = sorted(os.listdir(tmp_path))
    assert new_names == ["img_001.txt", "img_002.txt"]
