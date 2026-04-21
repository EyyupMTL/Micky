"""Detect / install / rename a Windows virtual audio cable so we can appear as 'Micky'.

Windows sadece imzalı kernel sürücülerinin mikrofon cihazı kaydetmesine izin verir.
Bu yüzden gerçek 'Micky' isimli bir sanal mikrofon sürücüsü tek seferde mümkün değil.
Pratik çözüm:
 1) Kullanıcıda VB-Cable (ücretsiz) zaten kuruluysa algıla ve Micky yerine onu kullan.
 2) Kurulu değilse VB-Audio indirme sayfasını aç.
 3) Opsiyonel: Windows kayıt defterindeki MMDevices altında görünen adı 'Micky'
    olarak değiştir (yönetici gerekir) — böylece diğer uygulamalar mikrofon listesinde
    'Micky' görsün.
"""
from __future__ import annotations

import ctypes
import os
import platform
import subprocess
import sys
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

import sounddevice as sd

VB_CABLE_HINTS_OUT = ("cable input", "voicemeeter input", "virtual audio cable")
VB_CABLE_HINTS_IN = ("cable output", "voicemeeter output", "virtual audio cable")
# Broader matches — hit device descriptions, INF entries, PnP root names.
VB_CABLE_HINTS_GENERIC = (
    "virtual cable", "vb-audio", "vb audio", "vbaudio",
    "cable input", "cable output", "voicemeeter",
)
# These match AFTER we've already renamed (so find_virtual_cable still works)
MICKY_HINT = ("micky",)
VB_DOWNLOAD_URL = "https://vb-audio.com/Cable/"


def _app_dir() -> Path:
    """Return the directory where bundled data lives (works both frozen and not)."""
    if getattr(sys, "frozen", False):
        # PyInstaller --onefile extracts data to sys._MEIPASS; --onedir uses the exe folder.
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass)
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


BUNDLED_DIR = _app_dir() / "vbcable"


def bundled_installer() -> Optional[Path]:
    """Return path to the bundled VB-Cable installer, if present."""
    is_64 = platform.machine().endswith("64")
    name = "VBCABLE_Setup_x64.exe" if is_64 else "VBCABLE_Setup.exe"
    exe = BUNDLED_DIR / name
    return exe if exe.is_file() else None


@dataclass
class VirtualCable:
    render_index: int   # Output-capable device we send audio INTO
    render_name: str
    capture_name: Optional[str]  # The corresponding mic-side name (what other apps see)


def find_virtual_cable() -> Optional[VirtualCable]:
    devices = sd.query_devices()
    render_idx: Optional[int] = None
    render_name: Optional[str] = None
    capture_name: Optional[str] = None
    hints = VB_CABLE_HINTS_GENERIC + MICKY_HINT
    for i, d in enumerate(devices):
        name_lc = d["name"].lower()
        if d["max_output_channels"] > 0 and render_idx is None:
            if any(h in name_lc for h in hints):
                render_idx = i
                render_name = d["name"]
        if d["max_input_channels"] > 0 and capture_name is None:
            if any(h in name_lc for h in hints):
                capture_name = d["name"]
    if render_idx is None:
        return None
    return VirtualCable(render_idx, render_name or "Virtual Cable", capture_name)


def open_download_page() -> None:
    webbrowser.open(VB_DOWNLOAD_URL)


def install_bundled() -> Tuple[bool, str]:
    """Launch the bundled VB-Cable installer via UAC elevation."""
    exe = bundled_installer()
    if exe is None:
        return False, "Dahili kurulum dosyası bulunamadı — vbcable klasörü eksik."
    try:
        ret = ctypes.windll.shell32.ShellExecuteW(
            None, "runas", str(exe), None, str(exe.parent), 1
        )
    except Exception as e:
        return False, f"Başlatılamadı: {e}"
    if ret <= 32:
        return False, f"Başlatma reddedildi (kod {ret})"
    return True, "Kurulum başlatıldı — pencerede 'Install Driver' butonuna bas, sonra PC'yi yeniden başlat."


# ---- Registry rename --------------------------------------------------------
# Windows shows "FriendlyName (InterfaceName)" for audio endpoints. To fully
# cover what various apps display we rewrite several locations.
#
# 1) MMDevices — what Sound Control Panel shows:
#      HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\MMDevices\Audio\{Render|Capture}\{GUID}\Properties
#      Value "{a45c254e-df1c-4efd-8020-67d146a850e0},2" = FriendlyName  (REG_SZ)
#      Value "{a45c254e-df1c-4efd-8020-67d146a850e0},0" = DeviceDesc    (REG_SZ)
#      Value "{b3f8fa53-0004-438e-9003-51a46e139bfc},6" = EndpointName  (REG_SZ)
# 2) PnP endpoint enumeration — used by DirectSound/WASAPI name lookups:
#      HKLM\SYSTEM\CurrentControlSet\Enum\SWD\MMDEVAPI\{endpoint}\FriendlyName
# 3) Legacy PnP — some apps still read this:
#      HKLM\SYSTEM\CurrentControlSet\Enum\ROOT\MEDIA\{inst}\FriendlyName + DeviceDesc
FRIENDLY_NAME_KEY = "{a45c254e-df1c-4efd-8020-67d146a850e0},2"
DEVICE_DESC_KEY_ALT = "{a45c254e-df1c-4efd-8020-67d146a850e0},0"
DEVICE_DESC_KEY = "{b3f8fa53-0004-438e-9003-51a46e139bfc},6"


def is_admin() -> bool:
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False


def _enum_subkeys(hive, path: str) -> List[str]:
    import winreg
    names: List[str] = []
    try:
        key = winreg.OpenKey(hive, path)
    except OSError:
        return names
    idx = 0
    while True:
        try:
            names.append(winreg.EnumKey(key, idx))
            idx += 1
        except OSError:
            break
    winreg.CloseKey(key)
    return names


def _matches_cable(name: str) -> bool:
    lc = name.lower()
    return any(h in lc for h in VB_CABLE_HINTS_GENERIC)


def _write_str(hive, path: str, value_name: str, new: str) -> bool:
    """Set a REG_SZ value. Returns True on success."""
    import winreg
    try:
        k = winreg.OpenKey(hive, path, 0, winreg.KEY_READ | winreg.KEY_WRITE)
    except OSError:
        return False
    try:
        try:
            _, vt = winreg.QueryValueEx(k, value_name)
        except OSError:
            vt = winreg.REG_SZ
        try:
            winreg.SetValueEx(k, value_name, 0, vt if vt in (1, 2) else winreg.REG_SZ, new)
            # Verify
            back, _ = winreg.QueryValueEx(k, value_name)
            return back == new
        except OSError:
            return False
    finally:
        winreg.CloseKey(k)


def _rename_mmdevices(target: str, log: List[str]) -> int:
    """Rename friendly names under MMDevices (Sound Control Panel display)."""
    import winreg
    count = 0
    for direction in ("Render", "Capture"):
        base = rf"SOFTWARE\Microsoft\Windows\CurrentVersion\MMDevices\Audio\{direction}"
        for guid in _enum_subkeys(winreg.HKEY_LOCAL_MACHINE, base):
            props = f"{base}\\{guid}\\Properties"
            # Read current friendly name to decide if it's VB-Cable
            try:
                k = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, props, 0, winreg.KEY_READ)
            except OSError:
                continue
            try:
                current, _ = winreg.QueryValueEx(k, FRIENDLY_NAME_KEY)
            except OSError:
                current = ""
            winreg.CloseKey(k)
            if not _matches_cable(current) or current == target:
                continue
            ok1 = _write_str(winreg.HKEY_LOCAL_MACHINE, props, FRIENDLY_NAME_KEY, target)
            _write_str(winreg.HKEY_LOCAL_MACHINE, props, DEVICE_DESC_KEY_ALT, target)
            _write_str(winreg.HKEY_LOCAL_MACHINE, props, DEVICE_DESC_KEY, target)
            if ok1:
                count += 1
                log.append(f"MMDevices/{direction}: '{current}' → '{target}'")
            else:
                log.append(f"HATA MMDevices/{direction} '{current}' — yazılamadı")
    return count


def _rename_swd_mmdevapi(target: str, log: List[str]) -> int:
    """Rename PnP endpoint FriendlyName under SWD\\MMDEVAPI."""
    import winreg
    base = r"SYSTEM\CurrentControlSet\Enum\SWD\MMDEVAPI"
    count = 0
    for endpoint in _enum_subkeys(winreg.HKEY_LOCAL_MACHINE, base):
        path = f"{base}\\{endpoint}"
        try:
            k = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path, 0, winreg.KEY_READ)
        except OSError:
            continue
        try:
            try:
                current, _ = winreg.QueryValueEx(k, "FriendlyName")
            except OSError:
                current = ""
        finally:
            winreg.CloseKey(k)
        if not _matches_cable(current) or current == target:
            continue
        if _write_str(winreg.HKEY_LOCAL_MACHINE, path, "FriendlyName", target):
            count += 1
            log.append(f"SWD\\MMDEVAPI: '{current}' → '{target}'")
    return count


def _rename_root_media(target: str, log: List[str]) -> int:
    """Rename legacy PnP entries under Enum\\ROOT\\MEDIA."""
    import winreg
    base = r"SYSTEM\CurrentControlSet\Enum\ROOT\MEDIA"
    count = 0
    for inst in _enum_subkeys(winreg.HKEY_LOCAL_MACHINE, base):
        path = f"{base}\\{inst}"
        try:
            k = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path, 0, winreg.KEY_READ)
        except OSError:
            continue
        try:
            try:
                friendly, _ = winreg.QueryValueEx(k, "FriendlyName")
            except OSError:
                friendly = ""
            try:
                desc, _ = winreg.QueryValueEx(k, "DeviceDesc")
            except OSError:
                desc = ""
        finally:
            winreg.CloseKey(k)
        if not _matches_cable(friendly + " " + desc) or friendly == target:
            continue
        ok = False
        if friendly and friendly != target:
            ok |= _write_str(winreg.HKEY_LOCAL_MACHINE, path, "FriendlyName", target)
        if desc and _matches_cable(desc) and desc != target:
            # Keep the "@VB_driver,...;..." INF reference intact if present
            if ";" in desc:
                # Format is "@oem...inf,%vbcable%;CABLE Output (VB-Audio)" — replace after ';'
                head, _, _ = desc.partition(";")
                new_desc = f"{head};{target}"
                ok |= _write_str(winreg.HKEY_LOCAL_MACHINE, path, "DeviceDesc", new_desc)
            else:
                ok |= _write_str(winreg.HKEY_LOCAL_MACHINE, path, "DeviceDesc", target)
        if ok:
            count += 1
            log.append(f"ROOT\\MEDIA: '{friendly or desc}' → '{target}'")
    return count


def _registry_rename(target: str = "Micky") -> Tuple[int, List[str]]:
    """Rename across all three registry locations. Returns (count, log)."""
    log: List[str] = []
    c1 = _rename_mmdevices(target, log)
    c2 = _rename_swd_mmdevapi(target, log)
    c3 = _rename_root_media(target, log)
    return c1 + c2 + c3, log


def list_current_names() -> List[Tuple[str, str]]:
    """Return (location, current_friendly_name) pairs for VB-Cable / Micky devices."""
    import winreg
    out: List[Tuple[str, str]] = []
    for direction in ("Render", "Capture"):
        base = rf"SOFTWARE\Microsoft\Windows\CurrentVersion\MMDevices\Audio\{direction}"
        for guid in _enum_subkeys(winreg.HKEY_LOCAL_MACHINE, base):
            props = f"{base}\\{guid}\\Properties"
            try:
                k = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, props, 0, winreg.KEY_READ)
            except OSError:
                continue
            try:
                try:
                    name, _ = winreg.QueryValueEx(k, FRIENDLY_NAME_KEY)
                except OSError:
                    name = ""
            finally:
                winreg.CloseKey(k)
            if name and (_matches_cable(name) or "micky" in name.lower()):
                out.append((direction, name))
    # Also peek at ROOT\MEDIA for the full "VB-Audio Virtual Cable" description
    try:
        import winreg
        base = r"SYSTEM\CurrentControlSet\Enum\ROOT\MEDIA"
        for inst in _enum_subkeys(winreg.HKEY_LOCAL_MACHINE, base):
            path = f"{base}\\{inst}"
            try:
                k = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path, 0, winreg.KEY_READ)
            except OSError:
                continue
            try:
                try:
                    desc, _ = winreg.QueryValueEx(k, "DeviceDesc")
                except OSError:
                    desc = ""
                try:
                    fr, _ = winreg.QueryValueEx(k, "FriendlyName")
                except OSError:
                    fr = ""
            finally:
                winreg.CloseKey(k)
            text = (fr or desc).strip()
            # DeviceDesc is usually "@oem...inf,%vbcable%;CABLE ..." — strip prefix
            if ";" in text:
                text = text.split(";", 1)[1]
            if text and (_matches_cable(text) or "micky" in text.lower()):
                out.append(("ROOT\\MEDIA", text))
    except Exception:
        pass
    return out


def _restart_audio_services() -> None:
    """Restart both AudioEndpointBuilder and Audiosrv (Audiosrv depends on it)."""
    cmds = [
        ["cmd", "/c", "net", "stop", "Audiosrv", "/y"],
        ["cmd", "/c", "net", "stop", "AudioEndpointBuilder", "/y"],
        ["cmd", "/c", "net", "start", "AudioEndpointBuilder"],
        ["cmd", "/c", "net", "start", "Audiosrv"],
    ]
    for c in cmds:
        try:
            subprocess.run(
                c,
                capture_output=True,
                timeout=30,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except Exception:
            pass


def rename_cable_to_micky() -> Tuple[bool, str, List[str]]:
    """Rename VB-Cable's capture + render devices across all known registry
    locations to 'Micky'. Returns (success, message, detailed_log).
    """
    if not is_admin():
        return False, "Yönetici olarak çalıştırılmalı", []
    try:
        import winreg  # noqa: F401
    except ImportError:
        return False, "winreg yok", []

    count1, log = _registry_rename("Micky")
    _restart_audio_services()
    # Second pass, in case the first set only caught one side
    count2, log2 = _registry_rename("Micky")
    log.extend(log2)
    total = count1 + count2
    if total == 0:
        current = list_current_names()
        if not current:
            return False, "VB-Cable kaydı bulunamadı. Önce sanal mikrofonu kur.", []
        # Maybe already renamed
        if all(n.lower() == "micky" for _, n in current):
            return True, "Zaten 'Micky' — Discord/Zoom gibi açık uygulamaları yeniden başlat.", [
                f"{d}: {n}" for d, n in current
            ]
        return False, "Değişiklik yazılamadı (yetki/ACL sorunu).", [f"{d}: {n}" for d, n in current]
    return True, (
        f"Başarılı — {total} yer 'Micky' olarak güncellendi. "
        "Discord/Zoom/Voicemod gibi açık uygulamaları yeniden başlat."
    ), log


def relaunch_as_admin(script_path: str) -> None:
    """Re-launch current Python script with UAC elevation."""
    params = f'"{script_path}"'
    ctypes.windll.shell32.ShellExecuteW(
        None, "runas", "python.exe", params, None, 1
    )
