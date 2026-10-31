from app.core.utils import (
    format_size, parse_size_to_bytes, matches_exclusion, send_to_trash,
)


def test_format_size():
    assert format_size(0) == "0 B"
    assert format_size(1023) == "1023 B"
    assert format_size(1024) == "1.0 KB"
    assert format_size(1024 * 1024 * 1024) == "1.0 GB"


def test_parse_size_to_bytes():
    assert parse_size_to_bytes(1, "MB") == 1024 * 1024
    assert parse_size_to_bytes(1, "GB") == 1024 ** 3
    assert parse_size_to_bytes(-5, "MB") == 0


def test_matches_exclusion():
    assert matches_exclusion("a.tmp", ["*.tmp"])
    assert matches_exclusion("x/y/temp/old.pdf", ["temp/"])
    assert not matches_exclusion("good.pdf", ["*.tmp", "temp/"])
    assert matches_exclusion("KEEP_me.pdf", ["*keep*"])


def test_matches_exclusion_precision():
    # The dot in a glob must be literal, not "any character".
    assert not matches_exclusion("axtmp", ["*.tmp"])
    assert not matches_exclusion("report2pdf", ["*.pdf"])
    assert matches_exclusion("sub/a.tmp", ["*.tmp"])


def test_send_to_trash(tmp_path):
    f = tmp_path / "delme.txt"
    f.write_text("bye")
    ok, err = send_to_trash(str(f))
    assert ok, err
    assert not f.exists()
