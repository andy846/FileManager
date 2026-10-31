"""Regression tests for the copy/move workers and the merged transfer page.

These cover the bugs that the original suite missed:
* The standalone move page used ``OperationControl`` without importing it
  (NameError on start); move now lives in the merged copy/move page.
* DuplicatesWorker referenced ``CancelledError`` without importing it.
* Copy verification only compared sizes.
"""

import threading

from app.core.models import CopyTask
from app.core.workers import OperationControl


def test_merged_copy_move_page_operation_switch(app):
    from app.core.i18n import set_language
    from app.core.settings import AppSettings
    from app.modules.copier.page import CopierPage

    set_language("en")
    page = CopierPage(AppSettings(), None)
    try:
        page._set_operation("copy", clear=False)
        assert page.operation == "copy"
        assert page.verb == "複製"
        assert page.start_btn.text() == "Start copy"
        assert page.retries.suffix() == " times"

        page._set_operation("move", clear=False)
        assert page.operation == "move"
        assert page.verb == "搬移"
        assert page.start_btn.text() == "Start move"
        assert page.history_module == "move"

        page._set_operation("copy", clear=False)
        assert page.operation == "copy"
    finally:
        page.deleteLater()


def test_duplicates_worker_imports_cancelled_error():
    from app.modules.duplicates import worker as dup_worker

    assert dup_worker.CancelledError is not None


def test_scan_worker_builds_tasks(app, sample_tree, tmp_path):
    from app.modules.copier.worker import ScanWorker

    got = {}
    worker = ScanWorker(OperationControl(), str(sample_tree),
                        str(tmp_path / "out"), "ext", {"extensions": ["pdf"]})
    worker.tasks_ready.connect(lambda tasks: got.setdefault("tasks", tasks))
    worker.run()  # run synchronously; no event loop required
    assert len(got["tasks"]) == 3


def test_scan_worker_reports_failure(app, tmp_path):
    from app.modules.copier.worker import ScanWorker

    errors = []
    worker = ScanWorker(OperationControl(), str(tmp_path / "missing"),
                        str(tmp_path / "out"), "ext", {"extensions": ["pdf"]})
    worker.scan_failed.connect(errors.append)
    worker.run()
    assert errors and "不存在" in errors[0]


def _run_process(worker, task):
    worker._process(task, threading.Lock(), threading.Lock(),
                    {"done": 0, "skipped": 0, "failed": 0, "bytes": 0})
    return task


def test_copy_worker_content_verification(app, tmp_path):
    from app.modules.copier.worker import TransferWorker

    src = tmp_path / "src.bin"
    src.write_bytes(b"hello" * 1000)
    dst = tmp_path / "out" / "src.bin"
    task = CopyTask(id=1, src=str(src), dst=str(dst), size=src.stat().st_size)
    worker = TransferWorker(OperationControl(), [task],
                            {"verify": True, "conflict_mode": "overwrite"})
    _run_process(worker, task)
    assert task.status == "done", task.error
    assert dst.read_bytes() == src.read_bytes()


def test_move_worker_same_device(app, tmp_path):
    from app.modules.copier.worker import TransferWorker

    src = tmp_path / "m.bin"
    src.write_bytes(b"move-me" * 500)
    dst = tmp_path / "moved" / "m.bin"
    task = CopyTask(id=1, src=str(src), dst=str(dst), size=src.stat().st_size)
    worker = TransferWorker(OperationControl(), [task],
                            {"verify": True, "conflict_mode": "overwrite"},
                            operation="move")
    _run_process(worker, task)
    assert task.status == "done", task.error
    assert dst.exists()
    assert not src.exists()


def test_move_start_does_not_raise(app, sample_tree, tmp_path):
    """The merged page must start a move scan without raising."""
    from app.core.settings import AppSettings
    from app.modules.copier.page import CopierPage

    page = CopierPage(AppSettings(), None)
    page._set_operation("move", clear=False)
    page.src.set_path(str(sample_tree))
    page.dst.set_path(str(tmp_path / "out"))
    page.rb_ext.setChecked(True)  # switch mode group to extensions
    page.chips.set_selected(["pdf"])
    page._on_start()  # must not raise
    assert page.scan_worker is not None
    assert page.operation == "move"
    page.control.cancel()
    page.scan_worker.wait(5000)


def test_trash_refused_without_send2trash(monkeypatch, tmp_path):
    import app.core.utils as utils

    victim = tmp_path / "keep.txt"
    victim.write_text("data")
    monkeypatch.setattr(utils, "_HAS_SEND2TRASH", False)
    ok, err = utils.send_to_trash(str(victim))
    assert not ok
    assert victim.exists()  # must never be permanently deleted silently
