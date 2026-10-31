import os
import csv

from app.modules.copier.scanner import (
    build_tasks, parse_patterns_text, passes_size_filter,
)


def test_parse_patterns_text():
    text = "a.pdf\nb*.xlsx, c.txt"
    pats = parse_patterns_text(text)
    assert pats == ["a.pdf", "b*.xlsx", "c.txt"]


def test_build_tasks_ext(sample_tree, tmp_path):
    target = tmp_path / "out"
    tasks = build_tasks(str(sample_tree), str(target), "ext",
                        {"extensions": ["pdf"]})
    # report.pdf, sub/deep.pdf, backup.PDF
    assert len(tasks) == 3


def test_build_tasks_custom(sample_tree, tmp_path):
    target = tmp_path / "out"
    tasks = build_tasks(str(sample_tree), str(target), "custom",
                        {"patterns_text": "*.txt"})
    assert len(tasks) == 2  # notes.txt, sub/keep_this.txt


def test_build_tasks_csv(sample_tree, tmp_path):
    target = tmp_path / "out"
    csv_path = tmp_path / "list.csv"
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["report.pdf"])
        w.writerow(["missing.pdf"])
    tasks = build_tasks(str(sample_tree), str(target), "csv",
                        {"csv_path": str(csv_path)})
    assert len(tasks) == 1
    assert tasks[0].src.endswith("report.pdf")


def test_size_filter():
    assert not passes_size_filter(10, 1, 0)  # min 1 MB -> 10 bytes fails
    assert passes_size_filter(2 * 1024 * 1024, 1, 5)


def test_preserve_structure(sample_tree, tmp_path):
    target = tmp_path / "out"
    tasks = build_tasks(str(sample_tree), str(target), "ext",
                        {"extensions": ["pdf"], "preserve_structure": True})
    dests = [os.path.relpath(t.dst, str(target)) for t in tasks]
    assert any(d == os.path.join("sub", "deep.pdf") for d in dests)


def test_excludes_target(sample_tree, tmp_path):
    # target inside source should be excluded
    tasks = build_tasks(str(sample_tree), str(sample_tree / "out"), "ext",
                        {"extensions": ["pdf"]})
    assert all(not t.src.startswith(str(sample_tree / "out")) for t in tasks)


def test_build_tasks_path_separator_pattern(sample_tree, tmp_path):
    # Patterns using "/" must match Windows rel paths using "\".
    tasks = build_tasks(str(sample_tree), str(tmp_path / "out"), "custom",
                        {"patterns_text": "sub/deep.pdf"})
    assert len(tasks) == 1
    assert tasks[0].src.endswith(os.path.join("sub", "deep.pdf"))
