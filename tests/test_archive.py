"""Tests for safe ZIP/TAR creation and extraction."""

import zipfile

import pytest

from app.core.archive import (
    create_zip, extract_archive, list_archive, sanitize_member,
)


def test_sanitize_member():
    assert sanitize_member("folder/file.txt") == "folder/file.txt"
    assert sanitize_member("../evil.txt") is None
    assert sanitize_member("folder/../../evil.txt") is None
    assert sanitize_member("C:/evil.txt") is None
    assert sanitize_member("/absolute.txt") is None
    assert sanitize_member("folder\\..\\evil.txt") is None


def test_zip_roundtrip(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "a.txt").write_text("hello", encoding="utf-8")
    (source / "sub").mkdir()
    (source / "sub" / "b.txt").write_text("world", encoding="utf-8")
    output = tmp_path / "archive.zip"

    summary = create_zip(output, [source])
    assert summary["added"] == 2
    names = {member.name.replace("\\", "/") for member in list_archive(output)}
    assert any(name.endswith("a.txt") for name in names)
    assert any(name.endswith("sub/b.txt") for name in names)

    dest = tmp_path / "extracted"
    result = extract_archive(output, dest)
    assert result["extracted"] == 2
    found = list(dest.rglob("b.txt"))
    assert len(found) == 1
    assert found[0].read_text(encoding="utf-8") == "world"


def test_extract_rejects_traversal(tmp_path):
    archive = tmp_path / "evil.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("../outside.txt", "bad")
        handle.writestr("safe.txt", "good")
    dest = tmp_path / "dest"
    result = extract_archive(archive, dest)
    assert result["skipped"] == 1
    assert result["extracted"] == 1
    assert not (tmp_path / "outside.txt").exists()
    assert (dest / "safe.txt").exists()


def test_extract_requires_supported_format(tmp_path):
    bad = tmp_path / "file.rar"
    bad.write_bytes(b"not an archive")
    with pytest.raises(ValueError):
        list_archive(bad)


def test_tar_roundtrip(tmp_path):
    import tarfile

    source = tmp_path / "source"
    source.mkdir()
    (source / "a.txt").write_text("tar", encoding="utf-8")
    archive_path = tmp_path / "archive.tar.gz"
    with tarfile.open(archive_path, "w:gz") as archive:
        archive.add(source, arcname="source")
    members = list_archive(archive_path)
    assert any(member.name.endswith("a.txt") for member in members)
    dest = tmp_path / "out"
    result = extract_archive(archive_path, dest)
    assert result["extracted"] >= 1
    assert list(dest.rglob("a.txt"))[0].read_text(encoding="utf-8") == "tar"
