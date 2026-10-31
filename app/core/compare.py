"""Pure two-folder comparison and synchronisation planning."""

import os
import stat
from dataclasses import dataclass, field

from PyQt6.QtCore import QThread, pyqtSignal

from app.core.hashing import hash_file
from app.core.transfer import copy_file
from app.core.utils import extended_path, send_to_trash
from app.core.workers import CancelledError, OperationControl

STATUS_SAME = "same"
STATUS_ONLY_LEFT = "only_left"
STATUS_ONLY_RIGHT = "only_right"
STATUS_LEFT_NEWER = "left_newer"
STATUS_RIGHT_NEWER = "right_newer"
STATUS_CONTENT_DIFF = "content_diff"
STATUS_SIZE_DIFF = "size_diff"
STATUS_TYPE_CONFLICT = "type_conflict"

STATUS_LABELS = {
    STATUS_SAME: "相同",
    STATUS_ONLY_LEFT: "僅左側",
    STATUS_ONLY_RIGHT: "僅右側",
    STATUS_LEFT_NEWER: "左側較新",
    STATUS_RIGHT_NEWER: "右側較新",
    STATUS_CONTENT_DIFF: "內容不同",
    STATUS_SIZE_DIFF: "大小不同",
    STATUS_TYPE_CONFLICT: "類型衝突",
}

STATUS_ORDER = [
    STATUS_ONLY_LEFT, STATUS_ONLY_RIGHT, STATUS_LEFT_NEWER,
    STATUS_RIGHT_NEWER, STATUS_CONTENT_DIFF, STATUS_SIZE_DIFF,
    STATUS_TYPE_CONFLICT, STATUS_SAME,
]


@dataclass
class CompareEntry:
    relative: str
    left_path: str = ""
    right_path: str = ""
    left_size: int = 0
    right_size: int = 0
    left_mtime: float = 0.0
    right_mtime: float = 0.0
    left_is_dir: bool = False
    right_is_dir: bool = False
    status: str = STATUS_SAME

    @property
    def left_kind(self):
        return "資料夾" if self.left_is_dir else "檔案"

    @property
    def right_kind(self):
        return "資料夾" if self.right_is_dir else "檔案"


@dataclass
class CompareResult:
    left: str
    right: str
    entries: list = field(default_factory=list)
    counts: dict = field(default_factory=dict)
    errors: int = 0

    def total_differences(self):
        return sum(
            count for status, count in self.counts.items()
            if status != STATUS_SAME
        )


def _is_reparse(path):
    try:
        if os.path.islink(path):
            return True
        attrs = getattr(os.stat(path), "st_file_attributes", 0)
        return bool(attrs & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))
    except OSError:
        return True


def _collect(root, side, control=None, progress=None, recursive=True):
    found = {}
    errors = 0
    stack = [root]
    while stack:
        if control is not None:
            control.wait_if_paused()
            control.checkpoint()
        current = stack.pop()
        try:
            entries = os.scandir(current)
        except OSError:
            errors += 1
            continue
        with entries:
            for entry in entries:
                try:
                    if entry.is_dir(follow_symlinks=False):
                        if _is_reparse(entry.path):
                            continue
                        if recursive:
                            stack.append(entry.path)
                        is_dir = True
                        size = 0
                        mtime = entry.stat(follow_symlinks=False).st_mtime
                    elif entry.is_file(follow_symlinks=False):
                        stat_result = entry.stat(follow_symlinks=False)
                        is_dir = False
                        size = stat_result.st_size
                        mtime = stat_result.st_mtime
                    else:
                        continue
                except OSError:
                    errors += 1
                    continue
                relative = os.path.relpath(entry.path, root)
                key = os.path.normcase(relative)
                found[key] = {
                    "relative": relative,
                    "path": entry.path,
                    "size": int(size),
                    "mtime": float(mtime),
                    "is_dir": is_dir,
                }
                if progress is not None:
                    progress(side, len(found))
    return found, errors


def compare_folders(left, right, recursive=True, compare_hash=False,
                    ignore_timestamps=False, include_same=False,
                    control=None, progress=None):
    """Compare two directory trees and return a :class:`CompareResult`."""
    left = os.path.abspath(str(left))
    right = os.path.abspath(str(right))
    if not os.path.isdir(left) or not os.path.isdir(right):
        raise ValueError("左右兩邊都必須是有效資料夾")

    left_files, left_errors = _collect(
        left, "left", control, progress, recursive
    )
    right_files, right_errors = _collect(
        right, "right", control, progress, recursive
    )
    counts = {status: 0 for status in STATUS_ORDER}
    differences = []

    for key in sorted(set(left_files) | set(right_files)):
        left_info = left_files.get(key)
        right_info = right_files.get(key)
        if left_info and not right_info:
            status = STATUS_ONLY_LEFT
        elif right_info and not left_info:
            status = STATUS_ONLY_RIGHT
        elif left_info["is_dir"] and right_info["is_dir"]:
            status = STATUS_SAME
        elif left_info["is_dir"] != right_info["is_dir"]:
            status = STATUS_TYPE_CONFLICT
        elif left_info["size"] != right_info["size"]:
            status = STATUS_SIZE_DIFF
        else:
            same_content = True
            if compare_hash:
                if control is not None:
                    control.checkpoint()
                digest_left = hash_file(left_info["path"], "sha256", control)
                digest_right = hash_file(right_info["path"], "sha256", control)
                same_content = digest_left == digest_right
            if not same_content:
                status = STATUS_CONTENT_DIFF
            elif ignore_timestamps or abs(
                    left_info["mtime"] - right_info["mtime"]) <= 2:
                status = STATUS_SAME
            elif left_info["mtime"] > right_info["mtime"]:
                status = STATUS_LEFT_NEWER
            else:
                status = STATUS_RIGHT_NEWER

        counts[status] = counts.get(status, 0) + 1
        if status == STATUS_SAME and not include_same:
            continue
        display = (left_info or right_info)["relative"]
        differences.append(CompareEntry(
            relative=display,
            left_path=left_info["path"] if left_info else "",
            right_path=right_info["path"] if right_info else "",
            left_size=left_info["size"] if left_info else 0,
            right_size=right_info["size"] if right_info else 0,
            left_mtime=left_info["mtime"] if left_info else 0.0,
            right_mtime=right_info["mtime"] if right_info else 0.0,
            left_is_dir=bool(left_info and left_info["is_dir"]),
            right_is_dir=bool(right_info and right_info["is_dir"]),
            status=status,
        ))

    return CompareResult(
        left=left, right=right, entries=differences,
        counts=counts, errors=left_errors + right_errors,
    )


def _minimal_paths(paths):
    selected = []
    for path in sorted(paths, key=lambda item: item.count(os.sep)):
        normalized = os.path.normcase(os.path.normpath(path))
        if any(
            normalized == parent or normalized.startswith(parent + os.sep)
            for parent in selected
        ):
            continue
        selected.append(normalized)
    return selected


def _roots_overlap(left, right):
    """Reject identical, nested, or junction-aliased sync roots."""
    left = os.path.normcase(os.path.realpath(os.path.abspath(left)))
    right = os.path.normcase(os.path.realpath(os.path.abspath(right)))
    try:
        common = os.path.commonpath((left, right))
    except ValueError:  # Different Windows drives.
        return False
    return common in (left, right)


def build_sync_plan(result, direction, entries=None, include_only=True,
                    include_newer=True, include_diff=True, mirror=False):
    """Build copy/mkdir/delete actions for one sync direction.

    ``direction`` is ``"l2r"`` or ``"r2l"``. Mirror deletes extra target
    files; it never deletes the source side.
    """
    if direction not in ("l2r", "r2l"):
        raise ValueError("direction must be l2r or r2l")
    if _roots_overlap(result.left, result.right):
        raise ValueError("同步來源與目標不可相同、互相包含或指向同一位置")
    if mirror and result.errors:
        raise ValueError(
            f"資料夾比對有 {result.errors} 個無法讀取項目，已禁止鏡像刪除"
        )
    target_root = result.right if direction == "l2r" else result.left
    source_root = result.left if direction == "l2r" else result.right
    entries = list(result.entries if entries is None else entries)
    actions = []
    target_only = []

    def _action(**fields):
        fields["source_root"] = source_root
        fields["target_root"] = target_root
        return fields

    for entry in entries:
        if entry.status == STATUS_SAME:
            continue
        if direction == "l2r":
            source_path, target_path = entry.left_path, entry.right_path
            source_is_dir = entry.left_is_dir
            source_exists = bool(entry.left_path)
            target_exists = bool(entry.right_path)
        else:
            source_path, target_path = entry.right_path, entry.left_path
            source_is_dir = entry.right_is_dir
            source_exists = bool(entry.right_path)
            target_exists = bool(entry.left_path)

        if entry.status == STATUS_TYPE_CONFLICT:
            actions.append(_action(
                action="conflict",
                relative=entry.relative,
                message="類型衝突（檔案／資料夾）",
            ))
            continue

        if entry.status == STATUS_ONLY_LEFT or entry.status == STATUS_ONLY_RIGHT:
            if not source_exists and target_exists:
                if mirror:
                    target_only.append(target_path)
                continue
            if not include_only:
                continue
        elif entry.status in (STATUS_LEFT_NEWER, STATUS_RIGHT_NEWER):
            source_status = (STATUS_LEFT_NEWER if direction == "l2r"
                             else STATUS_RIGHT_NEWER)
            if entry.status != source_status and not mirror:
                continue
            if not include_newer:
                continue
        elif entry.status in (STATUS_CONTENT_DIFF, STATUS_SIZE_DIFF):
            if not include_diff:
                continue
        else:
            continue

        if not source_path and target_path:
            if mirror:
                target_only.append(target_path)
            continue
        if not source_path:
            continue
        destination = os.path.join(target_root, entry.relative)
        if source_exists and not target_exists and entry.status in (
                STATUS_ONLY_LEFT, STATUS_ONLY_RIGHT):
            if source_is_dir:
                actions.append(_action(
                    action="mkdir", dst=destination,
                    relative=entry.relative,
                ))
                continue
        if source_is_dir and target_exists:
            continue
        if source_is_dir:
            actions.append(_action(
                action="mkdir", dst=destination,
                relative=entry.relative,
            ))
        else:
            actions.append(_action(
                action="copy", src=source_path, dst=destination,
                relative=entry.relative,
            ))

    if mirror:
        for path in _minimal_paths(target_only):
            actions.append(_action(
                action="delete", dst=path,
                relative=os.path.relpath(path, target_root),
            ))

    actions.sort(key=lambda item: (
        0 if item["action"] == "mkdir" else 1 if item["action"] == "copy" else 2,
        item.get("relative", ""),
    ))
    return actions


class SyncWorker(QThread):
    """Execute a compare/sync plan with progress and cancellation."""

    progress = pyqtSignal(int, int, str)
    completed = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, actions, control=None, verify=True):
        super().__init__()
        self.actions = list(actions)
        self.control = control or OperationControl()
        self.verify = verify

    def cancel(self):
        self.control.cancel()

    def run(self):
        summary = {
            "copied": 0, "deleted": 0, "failed": 0, "skipped": 0,
            "conflicts": 0, "errors": [], "cancelled": False,
        }
        total = len(self.actions)
        try:
            for index, action in enumerate(self.actions, 1):
                self.control.wait_if_paused()
                self.control.checkpoint()
                kind = action["action"]
                try:
                    if kind == "mkdir":
                        os.makedirs(extended_path(action["dst"]), exist_ok=True)
                        summary["copied"] += 1
                    elif kind == "copy":
                        dst = action["dst"]
                        if os.path.isdir(extended_path(dst)):
                            raise RuntimeError("目標是資料夾，無法寫入檔案")
                        copy_file(
                            action["src"], dst, control=self.control,
                            verify="quick" if self.verify else "off",
                        )
                        summary["copied"] += 1
                    elif kind == "delete":
                        reason = _validate_delete_target(action)
                        if reason:
                            summary["failed"] += 1
                            summary["errors"].append(
                                (action["dst"], reason))
                            self.progress.emit(
                                index, total, action.get("relative", kind))
                            continue
                        ok, error = send_to_trash(action["dst"])
                        if ok:
                            summary["deleted"] += 1
                        else:
                            summary["failed"] += 1
                            summary["errors"].append((action["dst"], error))
                    else:
                        summary["conflicts"] += 1
                except CancelledError:
                    raise
                except Exception as exc:
                    summary["failed"] += 1
                    summary["errors"].append((action.get("dst", ""), str(exc)))
                self.progress.emit(index, total, action.get("relative", kind))
            summary["cancelled"] = self.control.is_cancelled()
        except CancelledError:
            summary["cancelled"] = True
        self.completed.emit(summary)


def _validate_delete_target(action):
    """Re-validate roots and containment immediately before a mirror delete.

    A scan can go stale between planning and execution: the source root may
    have been removed (turning mirror into a blind wipe) or the target may
    have been replaced by a junction into the source tree. Both cases must
    abort the destructive action instead of deleting.
    """
    target_root = action.get("target_root")
    source_root = action.get("source_root")
    path = action.get("dst", "")
    if not target_root or not source_root or not path:
        return "缺少同步根目錄資訊，已拒絕刪除"
    if not os.path.isdir(extended_path(target_root)):
        return "目標資料夾已無法存取，已拒絕刪除"
    if not os.path.isdir(extended_path(source_root)):
        return "來源資料夾已無法存取，已拒絕鏡像刪除"
    try:
        with os.scandir(extended_path(source_root)):
            pass
    except OSError:
        return "來源資料夾已無法讀取，已拒絕鏡像刪除"
    real_path = os.path.normcase(os.path.realpath(os.path.abspath(path)))
    real_target = os.path.normcase(os.path.realpath(os.path.abspath(target_root)))
    real_source = os.path.normcase(os.path.realpath(os.path.abspath(source_root)))
    try:
        if os.path.commonpath([real_path, real_target]) != real_target:
            return "刪除目標已超出同步目標資料夾，已拒絕刪除"
        if os.path.commonpath([real_path, real_source]) == real_source:
            return "刪除目標指向來源資料夾，已拒絕刪除"
    except ValueError:
        return "路徑位於不同磁碟，已拒絕刪除"
    relative = os.path.relpath(os.path.abspath(path), os.path.abspath(target_root))
    source_path = os.path.join(source_root, relative)
    try:
        os.lstat(extended_path(source_path))
    except FileNotFoundError:
        pass
    except OSError:
        return "無法確認來源項目，已拒絕鏡像刪除"
    else:
        return "來源項目已存在，已拒絕鏡像刪除"
    return ""
