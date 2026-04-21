# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

project_dir = Path(SPECPATH).resolve()  # noqa: F821
icon = project_dir / "bundle" / "micky.ico"

a = Analysis(  # noqa: F821
    ["uninstaller.py"],
    pathex=[str(project_dir)],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter.test", "unittest", "pydoc"],
    noarchive=False,
)
pyz = PYZ(a.pure)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz, a.scripts, a.binaries, a.datas, [],
    name="Kaldir",
    debug=False, bootloader_ignore_signals=False,
    strip=False, upx=False, upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False, target_arch=None,
    icon=str(icon) if icon.exists() else None,
    uac_admin=False,
)
