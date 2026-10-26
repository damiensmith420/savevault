# -*- mode: python ; coding: utf-8 -*-
#
# SaveVault — PyInstaller build spec
#
# Build with:
#   pyinstaller build.spec
#
# Output: dist/SaveVault.exe  (single-file, no console window)

import sys
from pathlib import Path

block_cipher = None

# Resolve the project root relative to this spec file
project_root = Path(SPECPATH)  # noqa: F821  (SPECPATH injected by PyInstaller)

a = Analysis(
    [str(project_root / "main.py")],
    pathex=[str(project_root)],
    binaries=[],
    datas=[
        # Include the assets directory so icon.ico is bundled
        (str(project_root / "assets"), "assets"),
        # Include customtkinter's bundled theme JSON files
        # (required at runtime when running from a frozen exe)
    ],
    hiddenimports=[
        # Google API discovery / transport internals
        "googleapiclient.discovery",
        "googleapiclient.http",
        "googleapiclient.errors",
        "google.auth.transport.requests",
        "google.oauth2.credentials",
        "google_auth_oauthlib.flow",
        # Pillow image formats used by CustomTkinter
        "PIL._tkinter_finder",
        "PIL.Image",
        "PIL.ImageTk",
        # Tkinter
        "tkinter",
        "tkinter.filedialog",
        "tkinter.messagebox",
        # CustomTkinter
        "customtkinter",
        "darkdetect",
        # Standard library
        "queue",
        "threading",
        "webbrowser",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Trim unused heavy packages
        "matplotlib",
        "numpy",
        "pandas",
        "scipy",
        "IPython",
        "jupyter",
        "notebook",
        "pytest",
        "sphinx",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="SaveVault",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,           # Compress with UPX if available (smaller exe)
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,      # Windowed — no console popup
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(project_root / "assets" / "icon.ico"),
    onefile=True,       # Single .exe
)
