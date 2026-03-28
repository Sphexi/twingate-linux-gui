# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec file for twingate-tray
# Build: pyinstaller packaging/twingate-tray.spec

import os
import sys

block_cipher = None

PROJECT_DIR = os.path.abspath(os.path.join(os.path.dirname(SPECPATH), ".."))
SRC_DIR = os.path.join(PROJECT_DIR, "src")

a = Analysis(
    [os.path.join(SRC_DIR, "twingate_tray", "__main__.py")],
    pathex=[SRC_DIR],
    binaries=[],
    datas=[
        # Bundle SVG icons
        (
            os.path.join(SRC_DIR, "twingate_tray", "resources", "icons", "*.svg"),
            os.path.join("twingate_tray", "resources", "icons"),
        ),
        # Bundle polkit policy (installed separately, but included for reference)
        (
            os.path.join(SRC_DIR, "twingate_tray", "resources", "org.twingatetray.policy"),
            os.path.join("twingate_tray", "resources"),
        ),
    ],
    hiddenimports=[
        "twingate_tray",
        "twingate_tray.app",
        "twingate_tray.client",
        "twingate_tray.config",
        "twingate_tray.icons",
        "twingate_tray.poller",
        "twingate_tray.tray",
    ],
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

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="twingate-tray",
    debug=False,
    bootloader_ignore_signals=False,
    strip=True,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
