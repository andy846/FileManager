"""Tests for the streaming search engine."""

from app.core.search import SearchOptions, iter_search


def _make_tree(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "report.pdf").write_bytes(b"x" * 200)
    (tmp_path / "docs" / "notes.txt").write_text("hello", encoding="utf-8")
    (tmp_path / "photo.JPG").write_bytes(b"x" * 50)
    (tmp_path / "skip.tmp").write_bytes(b"x" * 10)
    (tmp_path / "archive").mkdir()
    (tmp_path / "archive" / "old.pdf").write_bytes(b"x" * 500)
    return tmp_path


def test_search_by_name_and_extension(tmp_path):
    root = _make_tree(tmp_path)
    options = SearchOptions(roots=[str(root)], name="*.pdf")
    names = {info.name for info in iter_search(options)}
    assert names == {"report.pdf", "old.pdf"}

    options = SearchOptions(roots=[str(root)], extensions=["txt"])
    assert [info.name for info in iter_search(options)] == ["notes.txt"]


def test_search_size_and_exclude(tmp_path):
    root = _make_tree(tmp_path)
    options = SearchOptions(
        roots=[str(root)], min_size=100, exclude=["archive/"]
    )
    names = {info.name for info in iter_search(options)}
    assert "report.pdf" in names
    assert "old.pdf" not in names
    assert "photo.JPG" not in names


def test_search_regex_and_non_recursive(tmp_path):
    root = _make_tree(tmp_path)
    options = SearchOptions(
        roots=[str(root)], name=r"^notes", use_regex=True,
    )
    assert [info.name for info in iter_search(options)] == ["notes.txt"]

    shallow = SearchOptions(roots=[str(root)], name="photo", recursive=False)
    assert [info.name for info in iter_search(shallow)] == ["photo.JPG"]


def test_search_progress(tmp_path):
    root = _make_tree(tmp_path)
    seen = []
    list(iter_search(
        SearchOptions(roots=[str(root)]),
        progress=lambda scanned, matched: seen.append((scanned, matched)),
    ))
    assert seen and seen[-1][0] >= 5
