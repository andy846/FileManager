import os

from app.modules.renamer.page import RenamerPage


def _out(name, pattern):
    p = RenamerPage.__new__(RenamerPage)
    return p._rename_one(os.path.join("/tmp", name), pattern)


def test_rename_replace():
    out = _out("my_old_file.txt", {"mode": "replace", "find": "old",
                                   "replace": "new", "keep_ext": True})
    assert out == os.path.join("/tmp", "my_new_file.txt")


def test_rename_prefix_suffix():
    out = _out("file.txt", {"mode": "prefix", "prefix": "pre_", "keep_ext": True})
    assert out == os.path.join("/tmp", "pre_file.txt")
    out2 = _out("file.txt", {"mode": "suffix", "suffix": "_end", "keep_ext": True})
    assert out2 == os.path.join("/tmp", "file_end.txt")


def test_rename_number():
    pattern = {"mode": "number", "prefix": "img_", "suffix": "",
               "start": 1, "pad": 3, "keep_ext": True, "_i": 0}
    out = _out("x.jpg", pattern)
    assert out == os.path.join("/tmp", "img_001.jpg")
    out2 = _out("y.jpg", pattern)
    assert out2 == os.path.join("/tmp", "img_002.jpg")


def test_rename_case():
    out = _out("File.txt", {"mode": "upper", "keep_ext": True})
    assert out == os.path.join("/tmp", "FILE.txt")
