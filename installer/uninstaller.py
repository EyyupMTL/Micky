"""Micky Kaldırma — Kaldir.exe."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import ttk

APP_NAME = "Micky"
INSTALL_ROOT = Path.home() / "AppData" / "Local" / "Programs" / APP_NAME
START_MENU = Path.home() / "AppData" / "Roaming" / "Microsoft" / "Windows" / "Start Menu" / "Programs" / APP_NAME
DESKTOP = Path.home() / "Desktop"

BG = "#0e1116"
PANEL = "#151a22"
PANEL_LIGHT = "#1d2430"
ACCENT = "#8affc1"
ACCENT_DIM = "#5cc98a"
DANGER = "#ff6b6b"
TEXT = "#e6edf3"
TEXT_DIM = "#8b96a7"
BORDER = "#242c3a"


def _remove_registry() -> None:
    import winreg
    key_path = rf"Software\Microsoft\Windows\CurrentVersion\Uninstall\{APP_NAME}"
    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key_path)
    except OSError:
        pass


def _safe_rm_tree(p: Path) -> None:
    if not p.exists():
        return
    try:
        shutil.rmtree(p, ignore_errors=True)
    except Exception:
        pass


def _safe_rm(p: Path) -> None:
    try:
        if p.is_file() or p.is_symlink():
            p.unlink(missing_ok=True)
    except Exception:
        pass


def _kill_running() -> None:
    try:
        subprocess.run(
            ["taskkill", "/IM", "Micky.exe", "/F"],
            capture_output=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception:
        pass


def do_uninstall(log_cb, progress_cb) -> None:
    def say(m): log_cb(m)

    say("Açık Micky örnekleri kapatılıyor…")
    _kill_running()
    progress_cb(10)

    say(f"Kısayollar kaldırılıyor…")
    _safe_rm(DESKTOP / "Micky.lnk")
    _safe_rm_tree(START_MENU)
    progress_cb(25)

    say("Add/Remove Programs kaydı siliniyor…")
    _remove_registry()
    progress_cb(45)

    say(f"Program klasörü siliniyor: {INSTALL_ROOT}")
    # Try to move/delete. If files locked (we're running from there!), schedule a self-deleting cleanup.
    me = Path(sys.executable).resolve() if getattr(sys, "frozen", False) else None
    if INSTALL_ROOT.exists():
        # Remove everything except maybe our own exe
        for child in INSTALL_ROOT.iterdir():
            if me and child.resolve() == me:
                continue
            if child.is_dir():
                _safe_rm_tree(child)
            else:
                _safe_rm(child)
    progress_cb(80)

    # Schedule removal of our own exe + parent dir after we exit
    if me and me.exists():
        bat = Path(os.environ["TEMP"]) / "micky_cleanup.bat"
        bat.write_text(
            "@echo off\r\n"
            "timeout /t 2 >nul\r\n"
            f"del \"{me}\" >nul 2>&1\r\n"
            f"rmdir /s /q \"{INSTALL_ROOT}\" >nul 2>&1\r\n"
            f"del \"%~f0\" >nul 2>&1\r\n",
            encoding="ascii",
        )
        subprocess.Popen(
            ["cmd", "/c", str(bat)],
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) | 0x00000008,  # DETACHED_PROCESS
            close_fds=True,
        )
    progress_cb(100)
    say("Kaldırma tamamlandı. Bu pencereyi kapatabilirsin.")


def silent() -> None:
    """Run uninstall silently — for QuietUninstallString."""
    def ignore(*_a, **_k): pass
    try:
        do_uninstall(ignore, ignore)
    except Exception:
        pass


# --- GUI ---------------------------------------------------------------
def _enable_dpi_awareness() -> None:
    import ctypes as _c
    try:
        _c.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            _c.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


class UninstallerApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(f"{APP_NAME} Kaldır")
        self.minsize(580, 460)
        self.geometry("600x500")
        self.configure(bg=BG)
        ico = INSTALL_ROOT / "micky.ico"
        if ico.exists():
            try: self.iconbitmap(str(ico))
            except Exception: pass
        self._running = False
        self._build_ui()

    def _build_ui(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("Micky.Horizontal.TProgressbar",
                        background=ACCENT, troughcolor=PANEL_LIGHT, borderwidth=0)

        header = tk.Frame(self, bg=BG)
        header.pack(side="top", fill="x", padx=26, pady=(22, 6))
        tk.Label(header, text="◉ Micky", bg=BG, fg=ACCENT,
                 font=("Segoe UI Semibold", 24)).pack(side="left")
        tk.Label(header, text="Kaldırma", bg=BG, fg=TEXT_DIM,
                 font=("Segoe UI", 11)).pack(side="left", padx=(10, 0), pady=(10, 0))

        bottom = tk.Frame(self, bg=BG)
        bottom.pack(side="bottom", fill="x", padx=22, pady=(0, 18))
        self.close_btn = tk.Button(
            bottom, text="Vazgeç", command=self.destroy,
            bg=PANEL_LIGHT, fg=TEXT, bd=0, activebackground=BORDER, activeforeground=TEXT,
            font=("Segoe UI", 11), height=2, width=14, cursor="hand2",
        )
        self.close_btn.pack(side="right", padx=(8, 0))
        self.remove_btn = tk.Button(
            bottom, text="Kaldır", command=self._on_run,
            bg=DANGER, fg="#ffffff", bd=0, activebackground="#d45353", activeforeground="#ffffff",
            font=("Segoe UI Semibold", 12), height=2, width=18, cursor="hand2",
        )
        self.remove_btn.pack(side="right")

        body = tk.Frame(self, bg=PANEL, highlightthickness=1, highlightbackground=BORDER)
        body.pack(side="top", fill="both", expand=True, padx=22, pady=(10, 10))
        tk.Label(body, text=f"Şu dizin silinecek:", bg=PANEL, fg=TEXT_DIM,
                 font=("Segoe UI", 11)).pack(anchor="w", padx=18, pady=(16, 0))
        tk.Label(body, text=str(INSTALL_ROOT), bg=PANEL, fg=TEXT,
                 font=("Consolas", 10)).pack(anchor="w", padx=18)
        tk.Label(
            body,
            text=(
                "Not: Sanal mikrofon sürücüsü (VB-Cable) sistem çapında kurulmuş\n"
                "olabilir — o, 'Uygulamalar & özellikler' listesinde ayrı durur."
            ),
            bg=PANEL, fg=TEXT_DIM, font=("Segoe UI", 10), justify="left",
        ).pack(anchor="w", padx=18, pady=(14, 6))

        self.progress = ttk.Progressbar(
            body, style="Micky.Horizontal.TProgressbar", mode="determinate",
            maximum=100, length=500,
        )
        self.progress.pack(fill="x", padx=18, pady=(8, 6))

        log_frame = tk.Frame(body, bg=PANEL)
        log_frame.pack(fill="both", expand=True, padx=18, pady=(4, 16))
        self.log = tk.Text(
            log_frame, height=5, bg=PANEL_LIGHT, fg=TEXT, bd=0,
            relief="flat", font=("Consolas", 9), wrap="word", state="disabled",
        )
        self.log.pack(fill="both", expand=True)

    def _log(self, msg: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", msg + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _progress(self, v: int) -> None:
        self.progress["value"] = v

    def _on_run(self) -> None:
        if self._running:
            return
        self._running = True
        self.remove_btn.configure(state="disabled", text="Kaldırılıyor…")

        def run():
            try:
                do_uninstall(
                    log_cb=lambda m: self.after(0, self._log, m),
                    progress_cb=lambda v: self.after(0, self._progress, v),
                )
                self.after(0, self._done)
            except Exception as e:
                self.after(0, lambda: self._log(f"HATA: {e}"))
                self.after(0, lambda: self.remove_btn.configure(state="normal", text="Tekrar dene"))
                self._running = False

        threading.Thread(target=run, daemon=True).start()

    def _done(self) -> None:
        self.remove_btn.configure(text="Tamam", state="normal", command=self.destroy)
        self.close_btn.configure(text="Kapat")
        self._running = False


def main() -> None:
    if "--silent" in sys.argv or "/silent" in sys.argv:
        silent()
        return
    _enable_dpi_awareness()
    app = UninstallerApp()
    app.mainloop()


if __name__ == "__main__":
    main()
