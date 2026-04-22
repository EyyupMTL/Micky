"""Persisted settings for the PC app.

Stored as JSON at ~/.micky/config.json. Loaded at startup, written on change.
Values are matched by label where possible (device names survive PortAudio
reshuffles better than indices do).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

CONFIG_DIR = Path.home() / ".micky"
CONFIG_PATH = CONFIG_DIR / "config.json"

DEFAULTS: Dict[str, Any] = {
    "port": 8125,
    "mode": "wifi",                   # wifi | usb | wifi_direct | bluetooth
    "output_device_label": None,      # resolved to index at start-up
    "monitor": False,
    "voice_gate": False,
    "gain": 1.0,
    "noise_gate_db": -60.0,
    "fx": "normal",                   # matches voice_fx.PRESETS
    "mute": False,
}


def load() -> Dict[str, Any]:
    cfg = dict(DEFAULTS)
    try:
        if CONFIG_PATH.is_file():
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                for k, v in data.items():
                    if k in DEFAULTS:
                        cfg[k] = v
    except Exception:
        # Corrupt/missing file — just use defaults.
        pass
    return cfg


def save(cfg: Dict[str, Any]) -> None:
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        tmp = CONFIG_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(CONFIG_PATH)
    except Exception:
        pass
