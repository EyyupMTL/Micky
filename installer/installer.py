"""Micky Kurulum — Kur.exe.

Extracts bundled resources, sets up Start Menu / Desktop shortcuts, registers
the uninstaller in Add/Remove Programs, optionally runs the VB-Cable driver
installer. Single-file GUI; no Python or other deps needed on the user side.
"""
from __future__ import annotations

import ctypes
import shutil
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import ttk

APP_NAME = "Micky"
APP_VERSION = "1.2"
PUBLISHER = "Micky Project"

INSTALL_ROOT = Path.home() / "AppData" / "Local" / "Programs" / APP_NAME
START_MENU = Path.home() / "AppData" / "Roaming" / "Microsoft" / "Windows" / "Start Menu" / "Programs" / APP_NAME
DESKTOP = Path.home() / "Desktop"

# --- Theme --------------------------------------------------------------
BG = "#0e1116"
PANEL = "#151a22"
PANEL_LIGHT = "#1d2430"
ACCENT = "#8affc1"
ACCENT_DIM = "#5cc98a"
DANGER = "#ff6b6b"
TEXT = "#e6edf3"
TEXT_DIM = "#8b96a7"
BORDER = "#242c3a"


def _bundled_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent / "bundle"


def _is_admin() -> bool:
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False


def _create_shortcut(target: Path, link: Path, icon: Path | None = None, description: str = "") -> None:
    """Create a .lnk via PowerShell's WScript.Shell."""
    link.parent.mkdir(parents=True, exist_ok=True)
    ps = (
        "$s = (New-Object -ComObject WScript.Shell).CreateShortcut('%s');"
        "$s.TargetPath = '%s';"
        "$s.WorkingDirectory = '%s';"
        "$s.Description = '%s';"
        "%s"
        "$s.Save();"
    ) % (
        str(link).replace("'", "''"),
        str(target).replace("'", "''"),
        str(target.parent).replace("'", "''"),
        description.replace("'", "''"),
        f"$s.IconLocation = '{icon},0';" if icon else "",
    )
    subprocess.run(
        ["powershell", "-NoProfile", "-Command", ps],
        capture_output=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def _register_uninstaller(install_dir: Path, uninstaller: Path, icon: Path | None) -> None:
    """Add an entry under HKCU Uninstall so the app appears in 'Apps & features'."""
    import winreg
    key_path = rf"Software\Microsoft\Windows\CurrentVersion\Uninstall\{APP_NAME}"
    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as k:
            winreg.SetValueEx(k, "DisplayName", 0, winreg.REG_SZ, APP_NAME)
            winreg.SetValueEx(k, "DisplayVersion", 0, winreg.REG_SZ, APP_VERSION)
            winreg.SetValueEx(k, "Publisher", 0, winreg.REG_SZ, PUBLISHER)
            winreg.SetValueEx(k, "InstallLocation", 0, winreg.REG_SZ, str(install_dir))
            winreg.SetValueEx(k, "UninstallString", 0, winreg.REG_SZ, f'"{uninstaller}"')
            winreg.SetValueEx(k, "QuietUninstallString", 0, winreg.REG_SZ, f'"{uninstaller}" /silent')
            if icon:
                winreg.SetValueEx(k, "DisplayIcon", 0, winreg.REG_SZ, str(icon))
            winreg.SetValueEx(k, "NoModify", 0, winreg.REG_DWORD, 1)
            winreg.SetValueEx(k, "NoRepair", 0, winreg.REG_DWORD, 1)
            winreg.SetValueEx(k, "EstimatedSize", 0, winreg.REG_DWORD, 45000)
    except OSError as e:
        raise RuntimeError(f"Uninstaller kaydı yazılamadı: {e}")


def do_install(log_cb, progress_cb, install_vbcable: bool) -> None:
    def say(msg: str) -> None:
        log_cb(msg)
    bundle = _bundled_dir()
    src_micky = bundle / "Micky.exe"
    src_uninst = bundle / "Kaldir.exe"
    src_vbcable = bundle / "vbcable"
    src_apk = bundle / "Micky.apk"
    src_icon = bundle / "micky.ico"

    progress_cb(5)
    INSTALL_ROOT.mkdir(parents=True, exist_ok=True)

    say(f"Dosyalar yükleniyor → {INSTALL_ROOT}")
    if not src_micky.exists():
        raise RuntimeError("Kurulum paketi bozuk: Micky.exe yok.")
    shutil.copy2(src_micky, INSTALL_ROOT / "Micky.exe")
    progress_cb(25)

    if src_uninst.exists():
        shutil.copy2(src_uninst, INSTALL_ROOT / "Kaldir.exe")
    progress_cb(35)

    if src_icon.exists():
        shutil.copy2(src_icon, INSTALL_ROOT / "micky.ico")
    progress_cb(40)

    if src_vbcable.exists() and src_vbcable.is_dir():
        dst = INSTALL_ROOT / "vbcable"
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src_vbcable, dst)
        say("Sanal mikrofon sürücüsü paketi yerleştirildi.")
    progress_cb(55)

    if src_apk.exists():
        shutil.copy2(src_apk, INSTALL_ROOT / "Micky.apk")
        say("Android APK, kurulum klasörüne kopyalandı.")
    progress_cb(65)

    # Shortcuts
    target = INSTALL_ROOT / "Micky.exe"
    icon_path = INSTALL_ROOT / "micky.ico" if (INSTALL_ROOT / "micky.ico").exists() else None
    _create_shortcut(target, START_MENU / "Micky.lnk", icon_path, "Telefonunu mikrofona çevir")
    _create_shortcut(target, DESKTOP / "Micky.lnk", icon_path, "Telefonunu mikrofona çevir")
    uninst = INSTALL_ROOT / "Kaldir.exe"
    if uninst.exists():
        _create_shortcut(uninst, START_MENU / "Micky Kaldır.lnk", icon_path, "Micky'yi kaldır")
    say("Kısayollar oluşturuldu.")
    progress_cb(75)

    _register_uninstaller(INSTALL_ROOT, uninst if uninst.exists() else INSTALL_ROOT / "Kaldir.exe", icon_path)
    say("Uygulamalar & özellikler listesine eklendi.")
    progress_cb(85)

    if install_vbcable:
        setup = INSTALL_ROOT / "vbcable" / "VBCABLE_Setup_x64.exe"
        if setup.is_file():
            say("Sanal mikrofon sürücü kurulumu başlatılıyor (UAC isteyecek)…")
            try:
                ctypes.windll.shell32.ShellExecuteW(
                    None, "runas", str(setup), None, str(setup.parent), 1
                )
            except Exception as e:
                say(f"Sürücü başlatılamadı: {e}")
    progress_cb(100)
    say("Kurulum tamamlandı.")


# --- GUI ---------------------------------------------------------------
def _enable_dpi_awareness() -> None:
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


class InstallerApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(f"{APP_NAME} Kurulum")
        self.minsize(620, 560)
        self.geometry("640x600")
        self.configure(bg=BG)
        # Icon
        ico = _bundled_dir() / "micky.ico"
        if ico.exists():
            try:
                self.iconbitmap(str(ico))
            except Exception:
                pass
        self._running = False
        self._build_ui()

    def _build_ui(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("Micky.Horizontal.TProgressbar",
                        background=ACCENT, troughcolor=PANEL_LIGHT, borderwidth=0)

        # Pack order matters: header at top, bottom button row reserved next,
        # then body fills the remaining space. Otherwise small/HighDPI windows
        # can clip the buttons off-screen.
        header = tk.Frame(self, bg=BG)
        header.pack(side="top", fill="x", padx=26, pady=(22, 6))
        tk.Label(header, text="◉ Micky", bg=BG, fg=ACCENT,
                 font=("Segoe UI Semibold", 24)).pack(side="left")
        tk.Label(header, text=f"Kurulum · v{APP_VERSION}",
                 bg=BG, fg=TEXT_DIM, font=("Segoe UI", 11)).pack(side="left", padx=(10, 0), pady=(10, 0))

        bottom = tk.Frame(self, bg=BG)
        bottom.pack(side="bottom", fill="x", padx=22, pady=(0, 18))
        self.cancel_btn = tk.Button(
            bottom, text="Kapat", command=self.destroy,
            bg=PANEL_LIGHT, fg=TEXT, bd=0, activebackground=BORDER, activeforeground=TEXT,
            font=("Segoe UI", 11), height=2, width=14, cursor="hand2",
        )
        self.cancel_btn.pack(side="right", padx=(8, 0))
        self.install_btn = tk.Button(
            bottom, text="Kur", command=self._on_install,
            bg=ACCENT, fg="#0a1a10", bd=0, activebackground=ACCENT_DIM, activeforeground="#0a1a10",
            font=("Segoe UI Semibold", 12), height=2, width=18, cursor="hand2",
        )
        self.install_btn.pack(side="right")

        body = tk.Frame(self, bg=PANEL, highlightthickness=1, highlightbackground=BORDER)
        body.pack(side="top", fill="both", expand=True, padx=22, pady=(10, 10))

        tk.Label(body, text=f"Kurulum yeri:",
                 bg=PANEL, fg=TEXT_DIM, font=("Segoe UI", 11)).pack(anchor="w", padx=18, pady=(16, 0))
        tk.Label(body, text=str(INSTALL_ROOT),
                 bg=PANEL, fg=TEXT, font=("Consolas", 10)).pack(anchor="w", padx=18)

        tk.Label(body, text="Yapılacaklar:", bg=PANEL, fg=TEXT_DIM,
                 font=("Segoe UI", 11)).pack(anchor="w", padx=18, pady=(12, 2))
        items = (
            "• Micky.exe ve kaynaklar %LOCALAPPDATA%\\Programs\\Micky altına kopyalanır",
            "• Başlat Menüsü ve Masaüstü kısayolları eklenir",
            "• Uygulamalar & özelliklere kayıt edilir (kaldırma için)",
            "• Android APK, kurulum klasörüne kopyalanır",
        )
        for it in items:
            tk.Label(body, text=it, bg=PANEL, fg=TEXT,
                     font=("Segoe UI", 10), anchor="w", justify="left").pack(anchor="w", padx=28)

        self.vb_var = tk.BooleanVar(value=True)
        opt_row = tk.Frame(body, bg=PANEL)
        opt_row.pack(fill="x", padx=18, pady=(12, 2))
        cb = tk.Checkbutton(opt_row,
                            text="Sanal mikrofon sürücüsünü (VB-Cable) hemen kur",
                            variable=self.vb_var,
                            bg=PANEL, fg=TEXT, selectcolor=PANEL_LIGHT,
                            activebackground=PANEL, activeforeground=TEXT,
                            font=("Segoe UI", 10))
        cb.pack(anchor="w")

        self.progress = ttk.Progressbar(
            body, style="Micky.Horizontal.TProgressbar", mode="determinate",
            maximum=100, length=540,
        )
        self.progress.pack(fill="x", padx=18, pady=(14, 6))

        log_frame = tk.Frame(body, bg=PANEL)
        log_frame.pack(fill="both", expand=True, padx=18, pady=(4, 16))
        self.log = tk.Text(
            log_frame, height=7, bg=PANEL_LIGHT, fg=TEXT, bd=0, insertbackground=TEXT,
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

    def _on_install(self) -> None:
        if self._running:
            return
        self._running = True
        self.install_btn.configure(state="disabled", text="Kuruluyor…")
        install_vb = bool(self.vb_var.get())

        def run():
            try:
                do_install(
                    log_cb=lambda m: self.after(0, self._log, m),
                    progress_cb=lambda v: self.after(0, self._progress, v),
                    install_vbcable=install_vb,
                )
                self.after(0, self._done)
            except Exception as e:
                self.after(0, lambda: self._log(f"HATA: {e}"))
                self.after(0, lambda: self.install_btn.configure(state="normal", text="Tekrar dene"))
                self._running = False

        threading.Thread(target=run, daemon=True).start()

    def _done(self) -> None:
        self.install_btn.configure(text="Micky'yi Aç", state="normal", command=self._launch_and_close)
        self.cancel_btn.configure(text="Kapat")
        self._running = False

    def _launch_and_close(self) -> None:
        try:
            subprocess.Popen([str(INSTALL_ROOT / "Micky.exe")], cwd=str(INSTALL_ROOT))
        except Exception as e:
            self._log(f"Başlatılamadı: {e}")
        self.destroy()


def main() -> None:
    _enable_dpi_awareness()
    app = InstallerApp()
    app.mainloop()


if __name__ == "__main__":
    main()
