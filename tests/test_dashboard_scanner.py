"""Tests for the dashboard folder scanner and its cache."""

import os
import pytest

from app.core.workers import CancelledError, OperationControl
from app.modules.dashboard.scanner import ScanSummary, scan_folder
from app.modules.dashboard.cache import load_cache, save_cache


class _FakeQ:
    def __init__(self, path):
        self._path = str(path)

    def fileName(self):
        return self._path


class _FakeSettings:
    def __init__(self, path):
        self.q = _FakeQ(path)


def test_scan_folder_totals_categories_and_rankings(sample_tree):
    summary = scan_folder(sample_tree)

    expected = (2 * 1024 * 1024 + 100 + 5 * 1024 * 1024 + 500 * 1024
                + 3 * 1024 * 1024 + 200 + 1024)
    assert summary.files == 7
    assert summary.folders == 1
    assert summary.total_size == expected
    assert summary.categories["documents"] == expected - 500 * 1024
    assert summary.categories["images"] == 500 * 1024
    assert summary.top_files[0]["name"] == "data.xlsx"
    assert summary.top_files[0]["size"] == 5 * 1024 * 1024
    assert summary.top_folders[0]["name"] == "（根目錄檔案）"
    assert any(item["name"] == "sub" for item in summary.top_folders)
    assert summary.age_buckets["week"] == expected
    assert summary.errors == 0

    pdf = next(item for item in summary.extensions if item["extension"] == "pdf")
    assert pdf["count"] == 3
    assert pdf["size"] == 2 * 1024 * 1024 + 3 * 1024 * 1024 + 1024


def test_parallel_scan_matches_sequential_totals(sample_tree):
    sequential = scan_folder(sample_tree, workers=1)
    parallel = scan_folder(sample_tree, workers=4)
    assert parallel.files == sequential.files
    assert parallel.folders == sequential.folders
    assert parallel.total_size == sequential.total_size
    assert parallel.junk_files == sequential.junk_files
    assert parallel.old_large_files == sequential.old_large_files
    assert [item["name"] for item in parallel.top_files] == [
        item["name"] for item in sequential.top_files
    ]


def test_scan_folder_can_be_cancelled(sample_tree):
    control = OperationControl()
    control.cancel()
    with pytest.raises(CancelledError):
        scan_folder(sample_tree, control=control)


def test_scan_folder_rejects_missing_root(tmp_path):
    with pytest.raises(ValueError):
        scan_folder(tmp_path / "missing")


def test_scan_summary_roundtrip(sample_tree):
    summary = scan_folder(sample_tree)
    restored = ScanSummary.from_dict(summary.as_dict())
    assert restored.root == summary.root
    assert restored.total_size == summary.total_size
    assert restored.top_files == summary.top_files
    assert restored.categories["documents"] == summary.categories["documents"]


def test_cache_roundtrip(sample_tree, tmp_path):
    settings = _FakeSettings(tmp_path / "settings.ini")
    summary = scan_folder(sample_tree)
    assert save_cache(settings, summary) is True
    loaded = load_cache(settings)
    assert loaded is not None
    assert loaded.root == summary.root
    assert loaded.total_size == summary.total_size
    assert loaded.top_files[0]["path"] == summary.top_files[0]["path"]


def test_cache_ignores_missing_root(sample_tree, tmp_path):
    settings = _FakeSettings(tmp_path / "settings.ini")
    summary = scan_folder(sample_tree)
    summary.root = os.path.join(str(tmp_path), "gone")
    assert save_cache(settings, summary) is True
    assert load_cache(settings) is None
