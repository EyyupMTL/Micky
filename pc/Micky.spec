# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

project_dir = Path(SPECPATH).resolve()  # noqa: F821

datas = [
    (str(project_dir / "vbcable"), "vbcable"),
    (str(project_dir / "assets" / "micky.ico"), "assets"),
    (str(project_dir / "rename_worker.py"), "."),
]

hiddenimports = [
    "customtkinter",
    "sounddevice",
    "numpy",
    "qrcode",
    "PIL.Image",
    "PIL.ImageDraw",
    "PIL.ImageTk",
]

a = Analysis(  # noqa: F821
    ["main.py"],
    pathex=[str(project_dir)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter.test", "unittest", "pydoc"],
    noarchive=False,
)
pyz = PYZ(a.pure)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="Micky",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(project_dir / "assets" / "micky.ico"),
)
