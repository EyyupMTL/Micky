"""Transport helpers: Wi-Fi, USB (ADB reverse tunnel), Wi-Fi Direct, Bluetooth.

Each mode ultimately hands a TCP socket to the AudioServer:
 - Wi-Fi      : server listens on 0.0.0.0:PORT, phone connects via router IP
 - USB        : server listens on 0.0.0.0:PORT, `adb reverse tcp:PORT tcp:PORT` makes
                the PC's port visible on the phone at 127.0.0.1:PORT
 - Wi-Fi Direct: same as Wi-Fi, but the phone/PC are on a P2P group IP (no router)
 - Bluetooth  : RFCOMM — Windows Python support is thin; we expose setup guidance
                and leave the socket plumbing as a follow-up.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from typing import Optional

MODE_WIFI = "wifi"
MODE_USB = "usb"
MODE_WIFI_DIRECT = "wifi_direct"
MODE_BLUETOOTH = "bluetooth"

MODES = [
    (MODE_WIFI, "Wi-Fi (aynı ağ)"),
    (MODE_USB, "USB (kablolu)"),
    (MODE_WIFI_DIRECT, "Wi-Fi Direct"),
    (MODE_BLUETOOTH, "Bluetooth"),
]


@dataclass
class ModeInfo:
    id: str
    hint_ip: Optional[str]
    hint_text: str


def _find_adb() -> Optional[str]:
    """Return path to adb.exe (user's Android SDK or PATH)."""
    candidate_env = os.environ.get("ANDROID_HOME") or os.environ.get("ANDROID_SDK_ROOT")
    candidates = []
    if candidate_env:
        candidates.append(os.path.join(candidate_env, "platform-tools", "adb.exe"))
    local_sdk = os.path.expandvars(r"%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe")
    candidates.append(local_sdk)
    path_adb = shutil.which("adb")
    if path_adb:
        candidates.append(path_adb)
    for c in candidates:
        if c and os.path.isfile(c):
            return c
    return None


def usb_available() -> bool:
    return _find_adb() is not None


def _run_adb(args: list[str]) -> subprocess.CompletedProcess:
    adb = _find_adb()
    if adb is None:
        raise RuntimeError("adb bulunamadı — Android Platform Tools kur.")
    return subprocess.run(
        [adb, *args],
        capture_output=True,
        text=True,
        timeout=10,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def open_usb_tunnel(port: int) -> str:
    """Set up `adb reverse tcp:PORT tcp:PORT` and return a status string."""
    devices = _run_adb(["devices"])
    if devices.returncode != 0:
        raise RuntimeError(f"adb devices başarısız: {devices.stderr.strip()}")
    lines = [l for l in devices.stdout.splitlines()[1:] if l.strip() and "device" in l]
    if not lines:
        raise RuntimeError("USB hata ayıklamayla bağlı cihaz yok. Telefonda USB Debugging aç.")
    res = _run_adb(["reverse", f"tcp:{port}", f"tcp:{port}"])
    if res.returncode != 0:
        raise RuntimeError(f"adb reverse başarısız: {res.stderr.strip()}")
    device_id = lines[0].split()[0]
    return f"USB tüneli aktif ({device_id})"


def close_usb_tunnel(port: int) -> None:
    try:
        _run_adb(["reverse", "--remove", f"tcp:{port}"])
    except Exception:
        pass


def describe_mode(mode: str, ip: str, port: int) -> ModeInfo:
    if mode == MODE_WIFI:
        return ModeInfo(
            mode,
            ip,
            f"Telefonla aynı Wi-Fi ağında olduğundan emin ol.\n"
            f"QR tara veya IP’yi elle gir: {ip}:{port}",
        )
    if mode == MODE_USB:
        return ModeInfo(
            mode,
            "127.0.0.1",
            "1) Telefonda USB Debugging aç\n"
            "2) Kabloyu tak → 'USB tünelini aç' butonuna bas\n"
            "3) Telefondaki Micky uygulamasında USB modunu seç",
        )
    if mode == MODE_WIFI_DIRECT:
        return ModeInfo(
            mode,
            ip,
            "1) Telefonda Kişisel Etkin Nokta'yı aç (veya Wi-Fi Direct)\n"
            "2) PC'yi aynı ağa/gruba bağla\n"
            "3) QR kodu tara — aynı IP mantığıyla bağlanacak",
        )
    if mode == MODE_BLUETOOTH:
        return ModeInfo(
            mode,
            None,
            "Bluetooth modu beta:\n"
            "• Telefonu PC ile eşleştir\n"
            "• 'Bluetooth üzerinden IP'yi test et' için şu an\n"
            "  Wi-Fi/USB modlarını tercih et — RFCOMM yakında.",
        )
    return ModeInfo(mode, ip, "")
