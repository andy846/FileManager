"""Data models shared across the application."""

import os
from dataclasses import dataclass, field
from typing import List, Tuple

_STATUS_PENDING = "pending"
STATUS_DONE = "done"
STATUS_SKIPPED = "skipped"
STATUS_FAILED = "failed"


@dataclass
class FileInfo:
    """A single file discovered during a scan."""

    path: str
    name: str = ""
    size: int = 0
    modified: float = 0.0
    extension: str = ""
    selected: bool = True

    def __post_init__(self):
        if not self.name:
            self.name = os.path.basename(str(self.path))
        if not self.extension and self.name:
            _, ext = os.path.splitext(self.name)
            self.extension = ext.lower().lstrip(".")


@dataclass
class CopyTask:
    """A single copy/move job."""

    id: int
    src: str
    dst: str
    size: int = 0
    status: str = _STATUS_PENDING
    error: str = ""
    bytes_copied: int = 0

    def reset(self):
        self.status = _STATUS_PENDING
        self.error = ""
        self.bytes_copied = 0


@dataclass
class OperationRecord:
    """A persisted record of a completed operation (history)."""

    id: int
    module: str
    timestamp: str
    folder: str
    detail: str
    files_processed: int = 0
    files_failed: int = 0
    size_freed_bytes: int = 0
    log_files: List[str] = field(default_factory=list)


@dataclass
class DeletionResult:
    """Result of a delete / trash operation."""

    folder: str
    extensions: List[str] = field(default_factory=list)
    deleted: List[str] = field(default_factory=list)
    failed: List[Tuple[str, str]] = field(default_factory=list)
    total_size_freed: int = 0
    started: str = ""
    finished: str = ""


@dataclass
class DuplicateGroup:
    """A group of files that share the same hash."""

    hash: str
    size: int
    files: List[FileInfo] = field(default_factory=list)

    @property
    def is_duplicate(self):
        return len(self.files) > 1

    @property
    def wasted_space(self):
        return self.size * max(0, len(self.files) - 1)
