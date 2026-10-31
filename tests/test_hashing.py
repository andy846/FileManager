"""Tests for streaming hashes and file collection."""

import hashlib

from app.core.hashing import collect_files, hash_file, hash_tree


def test_hash_file_algorithms(tmp_path):
    path = tmp_path / "sample.bin"
    data = b"hello world" * 1000
    path.write_bytes(data)
    assert hash_file(path, "sha256") == hashlib.sha256(data).hexdigest()
    assert hash_file(path, "sha1") == hashlib.sha1(data).hexdigest()
    assert hash_file(path, "md5") == hashlib.md5(data).hexdigest()


def test_collect_files_file_and_folder(tmp_path):
    folder = tmp_path / "folder"
    folder.mkdir()
    (folder / "a.txt").write_text("a", encoding="utf-8")
    (folder / "sub").mkdir()
    (folder / "sub" / "b.txt").write_text("bb", encoding="utf-8")
    single = tmp_path / "single.txt"
    single.write_text("single", encoding="utf-8")

    collected = dict(collect_files([single, folder]))
    names = {path.replace("\\", "/").split("/")[-1] for path in collected}
    assert names == {"single.txt", "a.txt", "b.txt"}

    shallow = dict(collect_files([folder], recursive=False))
    assert len(shallow) == 1


def test_hash_tree_changes_with_content_and_names(tmp_path):
    folder = tmp_path / "tree"
    folder.mkdir()
    (folder / "a.txt").write_text("a", encoding="utf-8")
    first = hash_tree(folder)
    (folder / "b.txt").write_text("b", encoding="utf-8")
    second = hash_tree(folder)
    assert first != second
    (folder / "b.txt").write_text("changed", encoding="utf-8")
    assert hash_tree(folder) != second
