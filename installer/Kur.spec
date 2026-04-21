# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

project_dir = Path(SPECPATH).resolve()  # noqa: F821
bundle_dir = project_dir / "bundle"

# Everything inside bundle/ ships alongside the installer and is extracted at install-time.
datas = [(str(bundle_dir), ".")]

a = Analysis(  # noqa: F821
    ["installer.py"],
    pathex=[str(project_dir)],
    binaries=[],
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter.test", "unittest", "pydoc"],
    noarchive=False,
)
pyz = PYZ(a.pure)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz, a.scripts, a.binaries, a.datas, [],
    name="Kur",
    debug=False, bootloader_ignore_signals=False,
    strip=False, upx=False, upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False, target_arch=None,
    icon=str(bundle_dir / "micky.ico") if (bundle_dir / "micky.ico").exists() else None,
    uac_admin=False,
)
