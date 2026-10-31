"""Drive metadata and UNC helper tests (no live network required)."""

import os

from app.core.drives import (
    NetworkError, connect_network_share, ensure_network_share,
    list_drive_entries, list_server_shares, normalize_unc_server,
    unc_share_root,
)
from app.core.utils import server_from_path


def test_normalize_unc_server_accepts_ip_and_share_paths():
    assert normalize_unc_server("10.8.17.66") == "\\\\10.8.17.66"
    assert normalize_unc_server("//10.8.17.66/share/folder") == (
        "\\\\10.8.17.66"
    )
    assert normalize_unc_server("\\\\10.8.17.66\\share") == (
        "\\\\10.8.17.66"
    )
    assert normalize_unc_server("") == ""


def test_server_from_path_for_share_and_server_root():
    assert server_from_path("\\\\server\\share\\folder") == "\\\\server"
    assert server_from_path("\\\\server") == "\\\\server"
    assert server_from_path("C:\\temp") == ""


def test_unc_share_root_for_deep_file_path():
    assert unc_share_root("\\\\server\\share\\folder\\file.txt") == (
        "\\\\server\\share"
    )
    assert unc_share_root("\\\\server\\share") == "\\\\server\\share"
    assert unc_share_root("C:\\temp") == ""


def test_drive_entries_include_system_drive():
    entries = list_drive_entries()
    assert entries
    system = next(
        (entry for entry in entries if entry.get("letter") == "C"), None
    )
    if os.name == "nt" and system is not None:
        assert system["root"] == "C:\\"
        assert system["kind"] in {"fixed", "network"}


def test_non_unc_connection_is_rejected():
    ok, error = connect_network_share("C:\\")
    assert not ok
    assert error


def test_server_root_requires_a_share():
    ok, error = ensure_network_share("\\\\server")
    assert not ok
    assert "共享" in error


def test_blank_server_raises_network_error():
    try:
        list_server_shares("")
    except NetworkError as exc:
        assert str(exc)
    else:  # pragma: no cover - defensive
        raise AssertionError("expected NetworkError")
