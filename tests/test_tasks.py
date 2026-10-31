"""Tests for the session task registry."""

from app.core.tasks import (
    STATUS_CANCELLED, STATUS_DONE, STATUS_PAUSED, STATUS_RUNNING, TaskManager,
)
from app.core.workers import OperationControl


def test_task_lifecycle(app):
    manager = TaskManager()
    control = OperationControl()
    task = manager.add(
        "copy", "複製測試", "copy", control=control, total=10
    )
    assert manager.active_count() == 1
    manager.update(task, done=4, message="處理中")
    assert task.percent == 40
    manager.toggle_pause(task)
    assert task.status == STATUS_PAUSED
    assert control.is_paused()
    manager.toggle_pause(task)
    assert task.status == STATUS_RUNNING
    manager.finish(task, STATUS_DONE, message="完成")
    assert task.status == STATUS_DONE
    assert manager.active_count() == 0
    assert task.finished_at is not None

    manager.clear_finished()
    assert manager.tasks() == []


def test_task_cancel_with_control(app):
    manager = TaskManager()
    control = OperationControl()
    task = manager.add("scan", "掃描", control=control)
    manager.cancel(task)
    assert control.is_cancelled()
    manager.finish(task, STATUS_CANCELLED)
    assert task.status == STATUS_CANCELLED


def test_task_pause_is_explicit(app):
    manager = TaskManager()
    control = OperationControl()
    pausable = manager.add("scan", "可暫停", control=control)
    fixed = manager.add("scan", "不可暫停", control=control, pausable=False)
    assert pausable.can_pause is True
    assert fixed.can_pause is False


def test_task_center_dialog(app):
    from app.ui.task_center import TaskCenterDialog

    manager = TaskManager()
    task = manager.add("copy", "複製 10 個檔案", "copy", total=10)
    manager.update(task, done=3)
    dialog = TaskCenterDialog(manager)
    try:
        assert dialog.table.rowCount() == 1
        bar = dialog.table.cellWidget(0, 2)
        assert bar.value() == 30
        dialog.table.selectRow(0)
        dialog._update_buttons()
        assert dialog.cancel_btn.isEnabled()
    finally:
        dialog.close()
        dialog.deleteLater()
