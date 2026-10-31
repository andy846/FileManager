"""Tests for the shared copy/move transfer engine."""

import pytest

from app.core.transfer import (
    copy_file, move_file, retry_operation, verify_mode,
)
from app.core.workers import CancelledError, OperationControl


def test_verify_mode_accepts_bool_and_string():
    assert verify_mode(True) == "quick"
    assert verify_mode(False) == "off"
    assert verify_mode("full") == "full"
    assert verify_mode("unknown") == "quick"


def test_copy_file_quick_and_full_verification(tmp_path):
    source = tmp_path / "source.bin"
    source.write_bytes(b"hello" * 10000)

    quick = tmp_path / "out" / "quick.bin"
    full = tmp_path / "out" / "full.bin"
    assert copy_file(str(source), str(quick), verify="quick") == source.stat().st_size
    assert copy_file(str(source), str(full), verify="full") == source.stat().st_size
    assert quick.read_bytes() == source.read_bytes()
    assert full.read_bytes() == source.read_bytes()


def test_copy_file_can_be_cancelled(tmp_path):
    source = tmp_path / "source.bin"
    source.write_bytes(b"x" * 100)
    control = OperationControl()
    control.cancel()
    with pytest.raises(CancelledError):
        copy_file(str(source), str(tmp_path / "out.bin"), control=control)


def test_move_same_device_removes_source(tmp_path):
    source = tmp_path / "move.bin"
    source.write_bytes(b"move" * 100)
    expected = source.stat().st_size
    target = tmp_path / "moved" / "move.bin"
    assert move_file(str(source), str(target), verify="quick") == expected
    assert target.read_bytes() == b"move" * 100
    assert not source.exists()


def test_retry_operation_retries_transient_error():
    calls = []

    def flaky():
        calls.append(1)
        if len(calls) < 3:
            exc = OSError(53, "network path")
            exc.winerror = 53
            raise exc
        return "ok"

    assert retry_operation(flaky, attempts=2) == "ok"
    assert len(calls) == 3
