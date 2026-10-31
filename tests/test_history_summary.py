"""Tests for dashboard/history aggregation."""

from app.core.history import summarize_history


def test_summarize_history_totals_and_modules():
    records = [
        {
            "module": "copy", "files_processed": 3, "files_failed": 0,
            "size_freed_bytes": 0,
        },
        {
            "module": "remove", "files_processed": 4, "files_failed": 1,
            "size_freed_bytes": 2048,
        },
        {
            "module": "remove", "files_processed": 1, "files_failed": 0,
            "size_freed_bytes": 1024,
        },
    ]
    summary = summarize_history(records)
    assert summary["operations"] == 3
    assert summary["processed"] == 8
    assert summary["failed"] == 1
    assert summary["freed_bytes"] == 3072
    assert summary["by_module"]["remove"]["operations"] == 2
    assert summary["by_module"]["remove"]["freed_bytes"] == 3072
    assert summary["success_rate"] == 8 / 9


def test_summarize_history_ignores_bad_records():
    summary = summarize_history([None, "bad", {"module": "copy"}])
    assert summary["operations"] == 1
    assert summary["processed"] == 0
    assert summary["success_rate"] == 0.0
