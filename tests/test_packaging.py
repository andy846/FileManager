"""Guard against drift between the UI version and the exe metadata."""

import os
import re

from app.core.constants import APP_VERSION, APP_VERSION_TUPLE

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_version_info_matches_constants():
    path = os.path.join(ROOT, "version_info.txt")
    with open(path, encoding="utf-8") as f:
        text = f.read()

    match = re.search(r"filevers=\(([^)]+)\)", text)
    assert match, "filevers missing from version_info.txt"
    filevers = tuple(int(p.strip()) for p in match.group(1).split(","))
    assert filevers == APP_VERSION_TUPLE

    # APP_VERSION ("1.0.0") must be the dotted form of the tuple prefix.
    assert APP_VERSION == ".".join(str(p) for p in APP_VERSION_TUPLE[:3])
