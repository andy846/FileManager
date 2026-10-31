# -*- mode: python ; coding: utf-8 -*-
import os

block_cipher = None

app_dir = os.path.dirname(os.path.abspath(SPEC))
added_files = [
    (os.path.join(app_dir, "assets", "app_icon.ico"), "assets"),
    (os.path.join(app_dir, "assets", "i18n"), "assets/i18n"),
]
icon_file = os.path.join(app_dir, "assets", "app_icon.ico")
version_file = os.path.join(app_dir, "version_info.txt")

a = Analysis(
    [os.path.join(app_dir, "main.py")],
    pathex=[app_dir],
    binaries=[],
    datas=added_files,
    hiddenimports=["PyQt6", "PyQt6.QtCore", "PyQt6.QtWidgets", "PyQt6.QtGui",
                   "PyQt6.QtSvg", "send2trash", "openpyxl",
                   "app.core.drives", "app.ui.network_dialog"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# onedir build: the exe loads its libraries from the _internal folder
# next to it instead of self-extracting to %TEMP% at every launch.
# Self-extracting onefile builds are a common trigger for antivirus
# heuristics (Symantec Endpoint Protection), so keep this onedir.
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="FileManager",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=icon_file,
    version=version_file,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name="FileManager",
)
