"""Helpers for IP detection and QR code generation."""
from __future__ import annotations

import io
import socket
from typing import List

import qrcode
from PIL import Image


def get_local_ips() -> List[str]:
    """Return list of non-loopback IPv4 addresses for this machine."""
    ips: List[str] = []
    hostname = socket.gethostname()
    try:
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            ip = info[4][0]
            if ip and not ip.startswith("127.") and ip not in ips:
                ips.append(ip)
    except socket.gaierror:
        pass
    # fallback: connect trick
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        if ip and ip not in ips and not ip.startswith("127."):
            ips.insert(0, ip)
    except OSError:
        pass
    return ips or ["127.0.0.1"]


def make_qr(ip: str, port: int, fg: str = "#8affc1", bg: str = "#151a22", mode: str = "wifi") -> Image.Image:
    """Create a QR code image encoding a micky:// URI for phone pairing."""
    uri = f"micky://{ip}:{port}?mode={mode}"
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=8,
        border=2,
    )
    qr.add_data(uri)
    qr.make(fit=True)
    img = qr.make_image(fill_color=fg, back_color=bg).convert("RGB")
    return img
