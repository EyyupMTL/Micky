"""Final release builder.

Order of operations:
  1. Build Micky.exe (the main app) via pc/Micky.spec
  2. Build Kaldir.exe (uninstaller) via installer/Kaldir.spec
  3. Stage everything Kur.exe needs into installer/bundle/:
       Micky.exe, Kaldir.exe, vbcable/, Micky.apk, micky.ico
  4. Build Kur.exe (installer) via installer/Kur.spec (bundles that dir)
  5. Copy final artifacts into release/

Run:  python build_release.py
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PC = ROOT / "pc"
INST = ROOT / "installer"
RELEASE = ROOT / "release"
BUNDLE = INST / "bundle"


def run(cmd: list[str], cwd: Path) -> None:
    print(f"\n$ (in {cwd.name}) {' '.join(cmd)}")
    r = subprocess.run(cmd, cwd=cwd)
    if r.returncode != 0:
        raise SystemExit(f"command failed: {cmd[:2]} ({r.returncode})")


def clean(*paths: Path) -> None:
    for p in paths:
        if p.exists():
            if p.is_dir():
                shutil.rmtree(p, ignore_errors=True)
            else:
                try:
                    p.unlink()
                except Exception:
                    pass


def step(title: str) -> None:
    line = "-" * 60
    print(f"\n{line}\n  {title}\n{line}")


def main() -> None:
    py = sys.executable
    pyi = [py, "-m", "PyInstaller", "--clean", "--noconfirm"]

    # --- 1) Main app ----------------------------------------------------
    step("1/4  Micky.exe (main app)")
    clean(PC / "build", PC / "dist")
    run([py, "make_icon.py"], cwd=PC)
    run(pyi + ["Micky.spec"], cwd=PC)
    micky_exe = PC / "dist" / "Micky.exe"
    if not micky_exe.is_file():
        raise SystemExit("Micky.exe not produced")

    # --- 2) Uninstaller -------------------------------------------------
    step("2/4  Kaldir.exe (uninstaller)")
    # Make sure there's an icon in installer/bundle/ for Kaldir.spec to use
    BUNDLE.mkdir(parents=True, exist_ok=True)
    shutil.copy2(PC / "assets" / "micky.ico", BUNDLE / "micky.ico")
    clean(INST / "build", INST / "dist")
    run(pyi + ["Kaldir.spec"], cwd=INST)
    kaldir_exe = INST / "dist" / "Kaldir.exe"
    if not kaldir_exe.is_file():
        raise SystemExit("Kaldir.exe not produced")

    # --- 3) Stage bundle for the installer ------------------------------
    step("3/4  Stage bundle/ for installer")
    # Clean bundle except icon (already placed)
    for child in list(BUNDLE.iterdir()):
        if child.name == "micky.ico":
            continue
        if child.is_dir():
            shutil.rmtree(child, ignore_errors=True)
        else:
            try: child.unlink()
            except Exception: pass

    shutil.copy2(micky_exe, BUNDLE / "Micky.exe")
    shutil.copy2(kaldir_exe, BUNDLE / "Kaldir.exe")

    # VB-Cable package
    vbcable_src = PC / "vbcable"
    if vbcable_src.is_dir():
        shutil.copytree(vbcable_src, BUNDLE / "vbcable", dirs_exist_ok=True)

    # Android APK (optional)
    apk = ROOT / "Micky.apk"
    if apk.is_file():
        shutil.copy2(apk, BUNDLE / "Micky.apk")

    print("Bundle contents:")
    for p in sorted(BUNDLE.rglob("*"))[:40]:
        print("  ", p.relative_to(BUNDLE))

    # --- 4) Build installer --------------------------------------------
    step("4/4  Kur.exe (installer)")
    # Clean previous build output (but not bundle)
    clean(INST / "build")
    # Remove only Kur-specific dist file if present
    dist_kur = INST / "dist" / "Kur.exe"
    if dist_kur.exists(): dist_kur.unlink()
    run(pyi + ["Kur.spec"], cwd=INST)
    kur_exe = INST / "dist" / "Kur.exe"
    if not kur_exe.is_file():
        raise SystemExit("Kur.exe not produced")

    # --- Copy final artifacts into release/ ----------------------------
    step("DONE  Copying to release/")
    RELEASE.mkdir(parents=True, exist_ok=True)
    # Clear old release
    for p in list(RELEASE.iterdir()):
        if p.is_dir(): shutil.rmtree(p, ignore_errors=True)
        else:
            try: p.unlink()
            except Exception: pass
    shutil.copy2(kur_exe, RELEASE / "Micky-Kurulum.exe")
    shutil.copy2(micky_exe, RELEASE / "Micky.exe")
    shutil.copy2(kaldir_exe, RELEASE / "Micky-Kaldir.exe")
    if apk.is_file():
        shutil.copy2(apk, RELEASE / "Micky.apk")
    print("Release folder:")
    for p in sorted(RELEASE.iterdir()):
        size_mb = p.stat().st_size / 1024 / 1024
        print(f"  {p.name:<30} {size_mb:6.1f} MB")


if __name__ == "__main__":
    main()
