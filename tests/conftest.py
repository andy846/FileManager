import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402  (must follow the env setup above)


@pytest.fixture(scope="session", autouse=True)
def isolate_settings(tmp_path_factory):
    from PyQt6.QtCore import QSettings

    settings_dir = str(tmp_path_factory.mktemp("settings"))
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope,
                      settings_dir)


@pytest.fixture
def sample_tree(tmp_path):
    """Create a small file tree for scanning tests."""
    files = {
        "report.pdf": 2 * 1024 * 1024,
        "notes.txt": 100,
        "data.xlsx": 5 * 1024 * 1024,
        "image.jpg": 500 * 1024,
        "sub/deep.pdf": 3 * 1024 * 1024,
        "sub/keep_this.txt": 200,
        "backup.PDF": 1024,
    }
    for name, size in files.items():
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x" * size)
    return tmp_path


@pytest.fixture
def app():
    from PyQt6.QtWidgets import QApplication

    a = QApplication.instance() or QApplication(sys.argv)
    yield a
