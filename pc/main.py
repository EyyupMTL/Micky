"""Micky — turn your phone into a PC microphone. PC server with modern UI."""
from __future__ import annotations

import ctypes
import json
import queue
import sys
import tempfile
import threading
import time
import tkinter as tk
from pathlib import Path
from typing import List, Optional

import customtkinter as ctk
import sounddevice as sd
from PIL import Image

import config
from network_utils import get_local_ips, make_qr
from server import AudioServer, StreamInfo
from transports import (
    MODE_BLUETOOTH,
    MODE_USB,
    MODE_WIFI,
    MODE_WIFI_DIRECT,
    MODES,
    describe_mode,
    open_usb_tunnel,
    close_usb_tunnel,
    usb_available,
)
from virtual_mic import (
    bundled_installer,
    find_virtual_cable,
    install_bundled,
    is_admin,
    list_current_names,
    open_download_page,
    rename_cable_to_micky,
    relaunch_as_admin,
)
from voice_fx import PRESETS as FX_PRESETS

APP_NAME = "Micky"
VERSION = "1.0"

# --- Theme ---------------------------------------------------------------
BG = "#0e1116"
PANEL = "#151a22"
PANEL_LIGHT = "#1d2430"
ACCENT = "#8affc1"
ACCENT_DIM = "#5cc98a"
DANGER = "#ff6b6b"
TEXT = "#e6edf3"
TEXT_DIM = "#8b96a7"
BORDER = "#242c3a"

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("green")


def list_output_devices() -> List[tuple[int, str]]:
    """Return (index, label) for every output-capable device. VB-Cable /
    Micky is promoted to the top so apps automatically work out of the box."""
    devices: List[tuple[int, str]] = []
    seen_names: set[str] = set()
    try:
        default_out = sd.default.device[1]
    except Exception:
        default_out = None
    for i, d in enumerate(sd.query_devices()):
        if d["max_output_channels"] <= 0:
            continue
        name = d["name"]
        key = f"{name}|{d['hostapi']}"
        if key in seen_names:
            continue
        seen_names.add(key)
        label = name
        if i == default_out:
            label = f"{name}  (varsayılan)"
        devices.append((i, label))

    # Promote VB-Cable / Micky to the top of the list as the recommended pick.
    try:
        from virtual_mic import find_virtual_cable
        cable = find_virtual_cable()
    except Exception:
        cable = None
    if cable is not None:
        for j, (idx, _label) in enumerate(devices):
            if idx == cable.render_index:
                devices.pop(j)
                devices.insert(0, (idx, "Micky  (önerilen — uygulamalara yönlendirir)"))
                break
    return devices


class LevelMeter(tk.Canvas):
    """Horizontal VU meter — green → yellow → red."""

    def __init__(self, master, width=420, height=28) -> None:
        tk.Canvas.__init__(
            self,
            master,
            width=width,
            height=height,
            bg=PANEL,
            highlightthickness=0,
            bd=0,
        )
        self._mw = width
        self._mh = height
        self._level = 0.0
        self._peak = 0.0
        self._peak_decay = 0
        self._draw()

    def set_level(self, level: float) -> None:
        self._level = max(0.0, min(1.0, level))
        if self._level > self._peak:
            self._peak = self._level
            self._peak_decay = 20
        else:
            self._peak_decay -= 1
            if self._peak_decay <= 0:
                self._peak = max(0.0, self._peak - 0.02)
        self._draw()

    def _draw(self) -> None:
        self.delete("all")
        self.create_rectangle(0, 0, self._mw, self._mh, fill=PANEL_LIGHT, outline="")
        segments = 36
        seg_w = (self._mw - 4) / segments
        lit = int(self._level * segments)
        for i in range(segments):
            x1 = 2 + i * seg_w
            x2 = x1 + seg_w - 2
            ratio = i / max(1, segments - 1)
            if ratio < 0.65:
                color = ACCENT
            elif ratio < 0.85:
                color = "#ffd166"
            else:
                color = DANGER
            if i < lit:
                self.create_rectangle(x1, 4, x2, self._mh - 4, fill=color, outline="")
            else:
                dim = "#2a3140"
                self.create_rectangle(x1, 4, x2, self._mh - 4, fill=dim, outline="")
        # peak line
        if self._peak > 0:
            px = 2 + self._peak * (self._mw - 4)
            self.create_rectangle(px - 1, 2, px + 1, self._mh - 2, fill="#ffffff", outline="")


class App(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self.title(f"{APP_NAME} — Phone as Microphone")
        self.geometry("960x620")
        self.minsize(860, 580)
        self.configure(fg_color=BG)

        self._event_q: queue.Queue = queue.Queue()
        self._devices = list_output_devices()
        self._qr_image_ref = None
        self._selected_ip_var = tk.StringVar()
        self._server: Optional[AudioServer] = None
        self._running = False
        self._last_level = 0.0
        self._cfg = config.load()
        self._mode: str = self._cfg.get("mode", MODE_WIFI)
        self._usb_tunnel_open = False
        self._mismatch_mode: Optional[str] = None
        self._save_scheduled = False

        self._build_ui()
        self._apply_config_to_ui()
        self._refresh_ips()
        self.after(30, self._drain_events)
        self.after(40, self._tick_level)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # --- UI construction ------------------------------------------------
    def _build_ui(self) -> None:
        self.grid_columnconfigure(0, weight=3)
        self.grid_columnconfigure(1, weight=2)
        self.grid_rowconfigure(0, weight=0)
        self.grid_rowconfigure(1, weight=1)
        self.grid_rowconfigure(2, weight=0)

        self._build_header()
        self._build_left_panel()
        self._build_right_panel()
        self._build_statusbar()

    def _build_header(self) -> None:
        header = ctk.CTkFrame(self, fg_color=BG, corner_radius=0, height=64)
        header.grid(row=0, column=0, columnspan=2, sticky="ew", padx=0, pady=0)
        header.grid_columnconfigure(1, weight=1)
        logo = ctk.CTkLabel(
            header,
            text="◉ Micky",
            font=("Segoe UI Semibold", 24),
            text_color=ACCENT,
        )
        logo.grid(row=0, column=0, padx=(22, 8), pady=16, sticky="w")
        sub = ctk.CTkLabel(
            header,
            text="telefonunu mikrofona çevir",
            font=("Segoe UI", 12),
            text_color=TEXT_DIM,
        )
        sub.grid(row=0, column=1, sticky="w", padx=(0, 0), pady=(24, 0))
        version = ctk.CTkLabel(
            header,
            text=f"v{VERSION}",
            font=("Segoe UI", 11),
            text_color=TEXT_DIM,
        )
        version.grid(row=0, column=2, sticky="e", padx=(0, 22))

    def _build_left_panel(self) -> None:
        left = ctk.CTkFrame(self, fg_color=PANEL, corner_radius=14, border_color=BORDER, border_width=1)
        left.grid(row=1, column=0, sticky="nsew", padx=(18, 9), pady=(4, 10))
        left.grid_columnconfigure(0, weight=1)

        # Section: Server
        self._section_label(left, "SUNUCU").grid(row=0, column=0, sticky="w", padx=22, pady=(22, 2))

        row1 = ctk.CTkFrame(left, fg_color="transparent")
        row1.grid(row=1, column=0, sticky="ew", padx=22, pady=(4, 10))
        row1.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(row1, text="Port", font=("Segoe UI", 12), text_color=TEXT_DIM).grid(
            row=0, column=0, sticky="w"
        )
        self.port_entry = ctk.CTkEntry(
            row1,
            width=90,
            fg_color=PANEL_LIGHT,
            border_color=BORDER,
            text_color=TEXT,
        )
        self.port_entry.insert(0, "8125")
        self.port_entry.grid(row=0, column=1, sticky="w", padx=(10, 0))
        self.port_entry.bind("<KeyRelease>", lambda _e: self._persist())

        self.start_btn = ctk.CTkButton(
            row1,
            text="▶  Başlat",
            command=self._toggle_server,
            fg_color=ACCENT,
            hover_color=ACCENT_DIM,
            text_color="#0a1a10",
            font=("Segoe UI Semibold", 13),
            height=38,
            width=130,
            corner_radius=10,
        )
        self.start_btn.grid(row=0, column=2, sticky="e", padx=(10, 0))

        # Section: Audio output
        self._section_label(left, "SES ÇIKIŞI").grid(row=2, column=0, sticky="w", padx=22, pady=(12, 2))

        row2 = ctk.CTkFrame(left, fg_color="transparent")
        row2.grid(row=3, column=0, sticky="ew", padx=22, pady=(4, 8))
        row2.grid_columnconfigure(0, weight=1)

        labels = [label for _, label in self._devices]
        default_label = labels[0] if labels else "—"
        self.device_combo = ctk.CTkOptionMenu(
            row2,
            values=labels or ["—"],
            command=lambda _v: self._persist(),
            fg_color=PANEL_LIGHT,
            button_color=PANEL_LIGHT,
            button_hover_color=BORDER,
            text_color=TEXT,
            dropdown_fg_color=PANEL_LIGHT,
            dropdown_text_color=TEXT,
            height=34,
            corner_radius=8,
        )
        self.device_combo.set(default_label)
        self.device_combo.grid(row=0, column=0, sticky="ew")
        refresh_btn = ctk.CTkButton(
            row2,
            text="⟳",
            width=34,
            height=34,
            corner_radius=8,
            command=self._refresh_devices,
            fg_color=PANEL_LIGHT,
            hover_color=BORDER,
            text_color=TEXT,
        )
        refresh_btn.grid(row=0, column=1, padx=(8, 0))

        hint = ctk.CTkLabel(
            left,
            text="İpucu: Discord/Zoom'da mikrofon olarak kullanmak için VB-Cable kur,\nburadan VB-Cable Input'u seç, o uygulamalarda mikrofonu VB-Cable Output yap.",
            font=("Segoe UI", 10),
            text_color=TEXT_DIM,
            justify="left",
            anchor="w",
        )
        hint.grid(row=4, column=0, sticky="w", padx=22, pady=(0, 12))

        # Section: Audio controls
        self._section_label(left, "SES").grid(row=5, column=0, sticky="w", padx=22, pady=(4, 2))

        controls = ctk.CTkFrame(left, fg_color="transparent")
        controls.grid(row=6, column=0, sticky="ew", padx=22, pady=(6, 10))
        controls.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(controls, text="Kazanç", text_color=TEXT_DIM, font=("Segoe UI", 12)).grid(
            row=0, column=0, sticky="w"
        )
        self.gain_slider = ctk.CTkSlider(
            controls,
            from_=0.0,
            to=3.0,
            number_of_steps=60,
            command=self._on_gain,
            button_color=ACCENT,
            progress_color=ACCENT_DIM,
            fg_color=PANEL_LIGHT,
        )
        self.gain_slider.set(1.0)
        self.gain_slider.grid(row=0, column=1, sticky="ew", padx=(10, 10))
        self.gain_value = ctk.CTkLabel(controls, text="1.00×", text_color=TEXT, font=("Segoe UI", 12), width=60)
        self.gain_value.grid(row=0, column=2, sticky="e")

        ctk.CTkLabel(controls, text="Gürültü kapısı", text_color=TEXT_DIM, font=("Segoe UI", 12)).grid(
            row=1, column=0, sticky="w", pady=(10, 0)
        )
        self.gate_slider = ctk.CTkSlider(
            controls,
            from_=-60.0,
            to=-10.0,
            number_of_steps=50,
            command=self._on_gate,
            button_color=ACCENT,
            progress_color=ACCENT_DIM,
            fg_color=PANEL_LIGHT,
        )
        self.gate_slider.set(-60.0)
        self.gate_slider.grid(row=1, column=1, sticky="ew", padx=(10, 10), pady=(10, 0))
        self.gate_value = ctk.CTkLabel(controls, text="kapalı", text_color=TEXT, font=("Segoe UI", 12), width=60)
        self.gate_value.grid(row=1, column=2, sticky="e", pady=(10, 0))

        switches_row = ctk.CTkFrame(left, fg_color="transparent")
        switches_row.grid(row=7, column=0, sticky="ew", padx=22, pady=(0, 12))
        switches_row.grid_columnconfigure(0, weight=1)
        switches_row.grid_columnconfigure(1, weight=1)

        self.mute_var = tk.BooleanVar(value=False)
        self.mute_btn = ctk.CTkSwitch(
            switches_row,
            text="Sessize al",
            variable=self.mute_var,
            command=self._on_mute,
            progress_color=DANGER,
            button_color=TEXT,
            font=("Segoe UI", 12),
            text_color=TEXT,
        )
        self.mute_btn.grid(row=0, column=0, sticky="w")

        self.monitor_var = tk.BooleanVar(value=False)
        self.monitor_btn = ctk.CTkSwitch(
            switches_row,
            text="Hoparlörden dinle",
            variable=self.monitor_var,
            command=self._on_monitor,
            progress_color=ACCENT,
            button_color=TEXT,
            font=("Segoe UI", 12),
            text_color=TEXT,
        )
        self.monitor_btn.grid(row=0, column=1, sticky="w")

        self.ns_var = tk.BooleanVar(value=False)
        self.ns_btn = ctk.CTkSwitch(
            switches_row,
            text="Konuşma filtresi",
            variable=self.ns_var,
            command=self._on_ns,
            progress_color=ACCENT,
            button_color=TEXT,
            font=("Segoe UI", 12),
            text_color=TEXT,
        )
        self.ns_btn.grid(row=1, column=0, sticky="w", pady=(8, 0))

        # Voice effect dropdown
        fx_label = ctk.CTkLabel(
            switches_row,
            text="Efekt",
            text_color=TEXT_DIM,
            font=("Segoe UI", 12),
        )
        fx_label.grid(row=1, column=1, sticky="w", pady=(8, 0), padx=(0, 4))
        self.fx_combo = ctk.CTkOptionMenu(
            switches_row,
            values=[label for _, label in FX_PRESETS],
            command=self._on_fx,
            fg_color=PANEL_LIGHT,
            button_color=PANEL_LIGHT,
            button_hover_color=BORDER,
            text_color=TEXT,
            dropdown_fg_color=PANEL_LIGHT,
            dropdown_text_color=TEXT,
            width=120,
            height=28,
            corner_radius=8,
        )
        self.fx_combo.set(FX_PRESETS[0][1])
        self.fx_combo.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(4, 0))

        # Section: Level
        self._section_label(left, "SEVİYE").grid(row=8, column=0, sticky="w", padx=22, pady=(0, 2))
        meter_wrap = ctk.CTkFrame(left, fg_color="transparent")
        meter_wrap.grid(row=9, column=0, sticky="ew", padx=22, pady=(4, 20))
        meter_wrap.grid_columnconfigure(0, weight=1)
        self.meter = LevelMeter(meter_wrap, width=440, height=26)
        self.meter.grid(row=0, column=0, sticky="ew")

    def _build_right_panel(self) -> None:
        right = ctk.CTkFrame(self, fg_color=PANEL, corner_radius=14, border_color=BORDER, border_width=1)
        right.grid(row=1, column=1, sticky="nsew", padx=(9, 18), pady=(4, 10))
        right.grid_columnconfigure(0, weight=1)

        self._section_label(right, "BAĞLANTI MODU").grid(
            row=0, column=0, sticky="w", padx=22, pady=(22, 4)
        )

        mode_row = ctk.CTkFrame(right, fg_color="transparent")
        mode_row.grid(row=1, column=0, sticky="ew", padx=22, pady=(4, 6))
        mode_row.grid_columnconfigure(0, weight=1)
        self.mode_combo = ctk.CTkOptionMenu(
            mode_row,
            values=[label for _, label in MODES],
            command=self._on_mode_change,
            fg_color=PANEL_LIGHT,
            button_color=PANEL_LIGHT,
            button_hover_color=BORDER,
            text_color=TEXT,
            dropdown_fg_color=PANEL_LIGHT,
            dropdown_text_color=TEXT,
            height=34,
            corner_radius=8,
        )
        self.mode_combo.set(MODES[0][1])
        self.mode_combo.grid(row=0, column=0, sticky="ew")

        self.usb_btn = ctk.CTkButton(
            right,
            text="USB tünelini aç",
            command=self._toggle_usb_tunnel,
            fg_color=PANEL_LIGHT,
            hover_color=BORDER,
            text_color=TEXT,
            height=32,
            corner_radius=8,
        )
        self.usb_btn.grid(row=2, column=0, sticky="ew", padx=22, pady=(2, 2))
        self.usb_btn.grid_remove()

        self.mode_hint = ctk.CTkLabel(
            right,
            text="",
            text_color=TEXT_DIM,
            font=("Segoe UI", 11),
            justify="left",
            anchor="w",
            wraplength=280,
        )
        self.mode_hint.grid(row=3, column=0, sticky="w", padx=22, pady=(4, 10))

        self._section_label(right, "TELEFONU EŞLEŞTİR").grid(
            row=4, column=0, sticky="w", padx=22, pady=(10, 4)
        )

        ctk.CTkLabel(
            right,
            text="Micky uygulamasıyla aşağıdaki karekodu tara\nveya IP + portu elle gir.",
            text_color=TEXT_DIM,
            font=("Segoe UI", 11),
            justify="left",
            anchor="w",
        ).grid(row=5, column=0, sticky="w", padx=22)

        self.qr_label = ctk.CTkLabel(right, text="", fg_color=PANEL_LIGHT, corner_radius=10, width=240, height=240)
        self.qr_label.grid(row=6, column=0, pady=(12, 8))

        ctk.CTkLabel(right, text="IP adresi", text_color=TEXT_DIM, font=("Segoe UI", 11)).grid(
            row=7, column=0, sticky="w", padx=22, pady=(6, 0)
        )
        self.ip_combo = ctk.CTkOptionMenu(
            right,
            values=["—"],
            variable=self._selected_ip_var,
            command=lambda _v: self._rebuild_qr(),
            fg_color=PANEL_LIGHT,
            button_color=PANEL_LIGHT,
            button_hover_color=BORDER,
            text_color=TEXT,
            dropdown_fg_color=PANEL_LIGHT,
            dropdown_text_color=TEXT,
            height=34,
            corner_radius=8,
        )
        self.ip_combo.grid(row=8, column=0, sticky="ew", padx=22, pady=(2, 14))

        self._section_label(right, "BAĞLANTI").grid(row=9, column=0, sticky="w", padx=22)
        self.conn_label = ctk.CTkLabel(
            right,
            text="Bekleniyor…",
            text_color=TEXT_DIM,
            font=("Segoe UI", 12),
            anchor="w",
        )
        self.conn_label.grid(row=10, column=0, sticky="ew", padx=22, pady=(4, 10))

        self._section_label(right, "MICKY SANAL MİKROFON").grid(
            row=11, column=0, sticky="w", padx=22, pady=(4, 2)
        )
        self.vmic_label = ctk.CTkLabel(
            right,
            text="",
            text_color=TEXT_DIM,
            font=("Segoe UI", 11),
            justify="left",
            anchor="w",
            wraplength=280,
        )
        self.vmic_label.grid(row=12, column=0, sticky="ew", padx=22, pady=(2, 4))
        vmic_btns = ctk.CTkFrame(right, fg_color="transparent")
        vmic_btns.grid(row=13, column=0, sticky="ew", padx=22, pady=(2, 20))
        vmic_btns.grid_columnconfigure(0, weight=1)
        vmic_btns.grid_columnconfigure(1, weight=1)
        self.vmic_primary_btn = ctk.CTkButton(
            vmic_btns,
            text="Micky olarak kullan",
            command=self._use_as_micky,
            fg_color=ACCENT,
            hover_color=ACCENT_DIM,
            text_color="#0a1a10",
            height=32,
            corner_radius=8,
        )
        self.vmic_primary_btn.grid(row=0, column=0, columnspan=2, sticky="ew")
        install_label = "Sanal mikrofonu kur" if bundled_installer() else "Sanal mikrofonu indir"
        self.vmic_install_btn = ctk.CTkButton(
            vmic_btns,
            text=install_label,
            command=self._install_or_download,
            fg_color=PANEL_LIGHT,
            hover_color=BORDER,
            text_color=TEXT,
            height=30,
            corner_radius=8,
        )
        self.vmic_install_btn.grid(row=1, column=0, sticky="ew", padx=(0, 4), pady=(6, 0))
        self.vmic_rename_btn = ctk.CTkButton(
            vmic_btns,
            text="'Micky' olarak adlandır",
            command=self._rename_to_micky,
            fg_color=PANEL_LIGHT,
            hover_color=BORDER,
            text_color=TEXT,
            height=30,
            corner_radius=8,
        )
        self.vmic_rename_btn.grid(row=1, column=1, sticky="ew", padx=(4, 0), pady=(6, 0))

    def _build_statusbar(self) -> None:
        container = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        container.grid(row=2, column=0, columnspan=2, sticky="ew")
        container.grid_columnconfigure(0, weight=1)

        self.mismatch_banner = ctk.CTkLabel(
            container,
            text="",
            fg_color="#3a2127",
            text_color="#ffb3b3",
            corner_radius=0,
            font=("Segoe UI Semibold", 11),
            anchor="w",
            justify="left",
            height=28,
        )
        self.mismatch_banner.grid(row=0, column=0, sticky="ew", ipady=2, ipadx=18)
        self.mismatch_banner.grid_remove()

        bar = ctk.CTkFrame(container, fg_color=PANEL_LIGHT, height=32, corner_radius=0)
        bar.grid(row=1, column=0, sticky="ew")
        bar.grid_columnconfigure(1, weight=1)

        self.status_dot = ctk.CTkLabel(bar, text="●", text_color=TEXT_DIM, font=("Segoe UI", 14))
        self.status_dot.grid(row=0, column=0, padx=(18, 6))
        self.status_label = ctk.CTkLabel(
            bar,
            text="Kapalı",
            text_color=TEXT_DIM,
            font=("Segoe UI", 11),
            anchor="w",
        )
        self.status_label.grid(row=0, column=1, sticky="w")

    def _section_label(self, parent, text: str) -> ctk.CTkLabel:
        return ctk.CTkLabel(
            parent,
            text=text,
            font=("Segoe UI Semibold", 10),
            text_color=ACCENT_DIM,
        )

    # --- Actions --------------------------------------------------------
    def _refresh_ips(self) -> None:
        ips = get_local_ips()
        self.ip_combo.configure(values=ips)
        if self._selected_ip_var.get() not in ips:
            self._selected_ip_var.set(ips[0])
        self._update_mode_ui()
        self._refresh_vmic_status()

    def _refresh_vmic_status(self) -> None:
        cable = find_virtual_cable()
        if cable is None:
            hint = (
                "Bulunamadı. 'Sanal mikrofonu kur' butonuna bas (dahili VB-Cable 4.5),\n"
                "kurulum sonrası PC'yi yeniden başlat, sonra 'Micky olarak adlandır' de."
                if bundled_installer() is not None
                else "Bulunamadı. 'Sanal mikrofonu indir' ile VB-Cable'ı kur,\n"
                     "sonra 'Micky olarak adlandır' ile sistemdeki adını değiştir."
            )
            self.vmic_label.configure(text=hint)
            self.vmic_primary_btn.configure(state="disabled")
        else:
            cap = cable.capture_name or "mikrofon tarafı"
            current = list_current_names()
            is_renamed = current and all(n.lower() == "micky" for _, n in current)
            badge = "✓ Micky olarak adlandırıldı" if is_renamed else "✓ Algılandı"
            device_lines = "\n".join(f"  • {d}: {n}" for d, n in current) if current else ""
            rename_hint = (
                "" if is_renamed
                else "\nSanal mikrofonun ismi hâlâ kablo ismiyle gözüküyor.\n"
                     "'Micky olarak adlandır' butonuna bas."
            )
            self.vmic_label.configure(
                text=f"{badge}\n{device_lines}{rename_hint}",
            )
            self.vmic_primary_btn.configure(state="normal")

    def _install_or_download(self) -> None:
        if bundled_installer() is not None:
            ok, msg = install_bundled()
            self._push_status(msg)
        else:
            open_download_page()
            self._push_status("İndirme sayfası açıldı")

    def _use_as_micky(self) -> None:
        cable = find_virtual_cable()
        if cable is None:
            return
        target_label = None
        for idx, label in self._devices:
            if idx == cable.render_index:
                target_label = label
                break
        if target_label:
            self.device_combo.set(target_label)
        self._push_status(
            f"Çıkış '{cable.render_name}' yapıldı — uygulamalarda Micky görünür olacak."
        )

    def _rename_to_micky(self) -> None:
        """Launch the rename worker elevated — Micky itself never restarts."""
        if is_admin():
            # Already elevated — run directly
            ok, msg, log = rename_cable_to_micky()
            self._push_status(msg)
            self._show_rename_report(ok, msg, log)
            if ok:
                self._refresh_devices()
                self._refresh_vmic_status()
            return

        self.vmic_rename_btn.configure(state="disabled", text="Yönetici onayı bekleniyor…")
        self._push_status("Yönetici onayı bekleniyor (UAC)…")

        result_file = Path(tempfile.gettempdir()) / f"micky_rename_{int(time.time()*1000)}.json"

        if getattr(sys, "frozen", False):
            # Frozen .exe — invoke ourselves with --rename-worker
            exe = sys.executable
            params = f'--rename-worker "{result_file}"'
            workdir = str(Path(exe).parent)
        else:
            # Dev mode — launch rename_worker.py with pythonw
            worker = Path(__file__).resolve().parent / "rename_worker.py"
            py_dir = Path(sys.executable).parent
            pyw = py_dir / "pythonw.exe"
            exe = str(pyw if pyw.is_file() else Path(sys.executable))
            params = f'"{worker}" "{result_file}"'
            workdir = str(worker.parent)

        try:
            rc = ctypes.windll.shell32.ShellExecuteW(
                None, "runas", exe, params, workdir, 0
            )
        except Exception as e:
            self._push_status(f"Başlatılamadı: {e}")
            self.vmic_rename_btn.configure(state="normal", text="'Micky' olarak adlandır")
            return

        if rc <= 32:
            # User likely declined UAC (ShellExecuteW returns code in SE_ERR_*)
            self._push_status("Yönetici izni reddedildi.")
            self.vmic_rename_btn.configure(state="normal", text="'Micky' olarak adlandır")
            return

        self._poll_rename_result(result_file, tries=180)

    def _poll_rename_result(self, result_file: Path, tries: int) -> None:
        if result_file.exists() and result_file.stat().st_size > 0:
            try:
                data = json.loads(result_file.read_text(encoding="utf-8"))
            except Exception:
                data = {"ok": False, "msg": "Sonuç dosyası okunamadı", "log": []}
            try:
                result_file.unlink()
            except Exception:
                pass
            self._push_status(data.get("msg", "Tamamlandı"))
            self.vmic_rename_btn.configure(state="normal", text="'Micky' olarak adlandır")
            self._show_rename_report(
                bool(data.get("ok")),
                data.get("msg", ""),
                data.get("log", []) or [],
            )
            if data.get("ok"):
                self._refresh_devices()
                self._refresh_vmic_status()
            return
        if tries <= 0:
            self._push_status("Yeniden adlandırma zaman aşımı")
            self.vmic_rename_btn.configure(state="normal", text="'Micky' olarak adlandır")
            return
        self.after(500, lambda: self._poll_rename_result(result_file, tries - 1))

    def _show_rename_report(self, ok: bool, msg: str, log: list) -> None:
        win = ctk.CTkToplevel(self)
        win.title("Micky — Yeniden adlandırma sonucu")
        win.geometry("560x420")
        win.configure(fg_color=BG)
        try:
            win.attributes("-topmost", True)
        except Exception:
            pass
        ctk.CTkLabel(
            win,
            text=("✓ Başarılı" if ok else "⚠ Başarısız"),
            font=("Segoe UI Semibold", 18),
            text_color=(ACCENT if ok else DANGER),
        ).pack(pady=(18, 2), padx=20, anchor="w")
        ctk.CTkLabel(
            win,
            text=msg,
            font=("Segoe UI", 12),
            text_color=TEXT,
            wraplength=520,
            justify="left",
            anchor="w",
        ).pack(padx=20, anchor="w")
        sep = ctk.CTkFrame(win, fg_color=BORDER, height=1)
        sep.pack(fill="x", padx=20, pady=10)
        ctk.CTkLabel(
            win, text="DETAY", text_color=ACCENT_DIM, font=("Segoe UI Semibold", 11),
            anchor="w",
        ).pack(padx=20, anchor="w")
        box = ctk.CTkTextbox(
            win,
            fg_color=PANEL,
            text_color=TEXT,
            border_color=BORDER,
            border_width=1,
            corner_radius=8,
            font=("Consolas", 11),
        )
        box.pack(fill="both", expand=True, padx=20, pady=(4, 12))
        box.insert("end", "\n".join(log) if log else "(değişiklik yok)")
        box.configure(state="disabled")
        ctk.CTkLabel(
            win,
            text="Değişikliği görmek için Discord/Zoom gibi uygulamaları kapatıp tekrar aç.",
            text_color=TEXT_DIM,
            font=("Segoe UI", 11),
            wraplength=520,
            justify="left",
        ).pack(padx=20, anchor="w", pady=(0, 12))
        ctk.CTkButton(
            win, text="Tamam", command=win.destroy,
            fg_color=ACCENT, hover_color=ACCENT_DIM, text_color="#0a1a10",
            height=32, corner_radius=8,
        ).pack(pady=(0, 16))

    def _on_mode_change(self, label: str) -> None:
        for mid, lbl in MODES:
            if lbl == label:
                self._mode = mid
                break
        if self._server is not None:
            self._server.server_mode = self._mode
            self._server.send_mode()
        self._update_mode_ui()
        self._persist()

    def _update_mode_ui(self) -> None:
        ip = self._effective_ip()
        try:
            port = int(self.port_entry.get())
        except (ValueError, AttributeError):
            port = 8125
        info = describe_mode(self._mode, ip, port)
        self.mode_hint.configure(text=info.hint_text)
        if self._mode == MODE_USB:
            self.usb_btn.grid()
            if not usb_available():
                self.usb_btn.configure(text="adb yok — Platform Tools gerekli", state="disabled")
            else:
                # Auto-open the tunnel as soon as the user picks USB mode.
                if not self._usb_tunnel_open:
                    try:
                        msg = open_usb_tunnel(port)
                        self._usb_tunnel_open = True
                        self._push_status(msg)
                    except RuntimeError as e:
                        self._push_status(str(e))
                self.usb_btn.configure(
                    text="USB tünelini kapat" if self._usb_tunnel_open else "USB tünelini yeniden dene",
                    state="normal",
                )
        else:
            self.usb_btn.grid_remove()
            if self._usb_tunnel_open:
                try:
                    port = int(self.port_entry.get())
                except ValueError:
                    port = 8125
                close_usb_tunnel(port)
                self._usb_tunnel_open = False
        self._rebuild_qr()

    def _effective_ip(self) -> str:
        if self._mode == MODE_USB:
            return "127.0.0.1"
        return self._selected_ip_var.get() or "127.0.0.1"

    def _toggle_usb_tunnel(self) -> None:
        try:
            port = int(self.port_entry.get())
        except ValueError:
            port = 8125
        if self._usb_tunnel_open:
            close_usb_tunnel(port)
            self._usb_tunnel_open = False
            self._push_status("USB tüneli kapatıldı")
        else:
            try:
                msg = open_usb_tunnel(port)
                self._usb_tunnel_open = True
                self._push_status(msg)
            except RuntimeError as e:
                self._push_status(str(e))
        self._update_mode_ui()

    def _refresh_devices(self) -> None:
        self._devices = list_output_devices()
        labels = [label for _, label in self._devices]
        current = self.device_combo.get()
        self.device_combo.configure(values=labels or ["—"])
        if current not in labels:
            self.device_combo.set(labels[0] if labels else "—")

    def _rebuild_qr(self) -> None:
        ip = self._effective_ip()
        try:
            port = int(self.port_entry.get())
        except ValueError:
            port = 8125
        img = make_qr(ip, port, fg=ACCENT, bg=PANEL_LIGHT, mode=self._mode)
        img = img.resize((220, 220), Image.NEAREST)
        self._qr_image_ref = ctk.CTkImage(light_image=img, dark_image=img, size=(220, 220))
        self.qr_label.configure(image=self._qr_image_ref, text="")

    def _on_gain(self, v: float) -> None:
        self.gain_value.configure(text=f"{float(v):.2f}×")
        if self._server is not None:
            self._server.send_gain(float(v))
        self._persist()

    def _on_gate(self, v: float) -> None:
        v = float(v)
        label = "kapalı" if v <= -59.5 else f"{v:.0f} dB"
        self.gate_value.configure(text=label)
        if self._server is not None:
            self._server.noise_gate_db = v
        self._persist()

    def _on_mute(self) -> None:
        m = bool(self.mute_var.get())
        if self._server is not None:
            self._server.send_mute(m)
        self._persist()

    def _on_monitor(self) -> None:
        enabled = bool(self.monitor_var.get())
        if self._server is not None:
            info = self._server._info
            self._server.set_monitor_enabled(enabled, info)
        self._persist()

    def _on_ns(self) -> None:
        enabled = bool(self.ns_var.get())
        if self._server is not None:
            self._server.voice_gate.enabled = enabled
        self._persist()

    def _on_fx(self, label: str) -> None:
        preset_id = "normal"
        for pid, lbl in FX_PRESETS:
            if lbl == label:
                preset_id = pid
                break
        if self._server is not None:
            self._server.send_fx(preset_id)
        self._persist()

    def _toggle_server(self) -> None:
        if not self._running:
            try:
                port = int(self.port_entry.get())
            except ValueError:
                self._push_status("Geçersiz port")
                return
            device_idx = self._current_device_index()
            self._server = AudioServer(
                on_status=self._push_status,
                on_level=self._push_level,
                on_connect=self._push_connect,
                on_remote_mute=self._push_remote_mute,
                on_mode_mismatch=self._push_mode_mismatch,
                on_remote_fx=self._push_remote_fx,
                on_remote_gain=self._push_remote_gain,
            )
            self._server.gain = float(self.gain_slider.get())
            self._server.noise_gate_db = float(self.gate_slider.get())
            self._server.muted = bool(self.mute_var.get())
            self._server.monitor_enabled = bool(self.monitor_var.get())
            self._server.monitor_device = None
            self._server.voice_gate.enabled = bool(self.ns_var.get())
            fx_label = self.fx_combo.get()
            for pid, lbl in FX_PRESETS:
                if lbl == fx_label:
                    self._server.voice_fx.preset = pid
                    break
            self._server.server_mode = self._mode
            try:
                self._server.start(port, device_idx)
            except OSError as e:
                self._push_status(f"Başlatılamadı: {e}")
                self._server = None
                return
            self._running = True
            self.start_btn.configure(text="■  Durdur", fg_color=DANGER, hover_color="#d45353", text_color="#ffffff")
            self.status_dot.configure(text_color=ACCENT)
            self._rebuild_qr()
        else:
            if self._server is not None:
                self._server.stop()
                self._server = None
            self._running = False
            self.start_btn.configure(
                text="▶  Başlat",
                fg_color=ACCENT,
                hover_color=ACCENT_DIM,
                text_color="#0a1a10",
            )
            self.status_dot.configure(text_color=TEXT_DIM)

    def _current_device_index(self) -> Optional[int]:
        current_label = self.device_combo.get()
        for idx, label in self._devices:
            if label == current_label:
                return idx
        return None

    # --- Event bridge from server thread --------------------------------
    def _push_status(self, msg: str) -> None:
        self._event_q.put(("status", msg))

    def _push_level(self, lvl: float) -> None:
        self._last_level = lvl

    def _push_connect(self, info: Optional[StreamInfo]) -> None:
        self._event_q.put(("connect", info))

    def _push_remote_mute(self, muted: bool) -> None:
        self._event_q.put(("remote_mute", muted))

    def _push_mode_mismatch(self, client_mode: Optional[str]) -> None:
        self._event_q.put(("mismatch", client_mode))

    def _push_remote_fx(self, preset: str) -> None:
        self._event_q.put(("remote_fx", preset))

    def _push_remote_gain(self, gain: float) -> None:
        self._event_q.put(("remote_gain", gain))

    def _drain_events(self) -> None:
        try:
            while True:
                kind, payload = self._event_q.get_nowait()
                if kind == "status":
                    self.status_label.configure(text=payload, text_color=TEXT)
                elif kind == "connect":
                    if payload is None:
                        self.conn_label.configure(text="Bekleniyor…", text_color=TEXT_DIM)
                    else:
                        self.conn_label.configure(
                            text=f"{payload.client_addr}  •  {payload.sample_rate} Hz  •  {payload.channels} kanal",
                            text_color=ACCENT,
                        )
                elif kind == "remote_mute":
                    # Only update the UI; don't re-send to phone (avoid loop)
                    self.mute_var.set(bool(payload))
                elif kind == "mismatch":
                    self._mismatch_mode = payload
                    self._refresh_mismatch_ui()
                elif kind == "remote_fx":
                    for pid, lbl in FX_PRESETS:
                        if pid == payload:
                            self.fx_combo.set(lbl)
                            break
                elif kind == "remote_gain":
                    # Reflect the phone's gain on PC without echoing back
                    self.gain_slider.set(float(payload))
                    self.gain_value.configure(text=f"{float(payload):.2f}×")
        except queue.Empty:
            pass
        self.after(30, self._drain_events)

    def _refresh_mismatch_ui(self) -> None:
        if self._mismatch_mode is None:
            self.mismatch_banner.grid_remove()
        else:
            pretty = {
                "wifi": "Wi-Fi", "usb": "USB",
                "wifi_direct": "Wi-Fi Direct", "bluetooth": "Bluetooth",
            }
            cm = pretty.get(self._mismatch_mode, self._mismatch_mode)
            sm = pretty.get(self._mode, self._mode)
            self.mismatch_banner.configure(
                text=f"⚠  Mod uyuşmuyor — PC: {sm} · Telefon: {cm}",
            )
            self.mismatch_banner.grid()

    def _tick_level(self) -> None:
        self.meter.set_level(self._last_level)
        # Slight decay so meter doesn't stick if stream pauses
        self._last_level *= 0.88
        self.after(40, self._tick_level)

    def _apply_config_to_ui(self) -> None:
        """Push loaded config values into widgets."""
        cfg = self._cfg
        self.port_entry.delete(0, "end")
        self.port_entry.insert(0, str(cfg.get("port", 8125)))
        # Mode
        for mid, lbl in MODES:
            if mid == cfg.get("mode", MODE_WIFI):
                self.mode_combo.set(lbl)
                self._mode = mid
                break
        # Output device — match by label (falls back to first if not found)
        saved_label = cfg.get("output_device_label")
        if saved_label:
            labels = [lbl for _, lbl in self._devices]
            if saved_label in labels:
                self.device_combo.set(saved_label)
        # Switches + sliders
        self.monitor_var.set(bool(cfg.get("monitor", False)))
        self.ns_var.set(bool(cfg.get("voice_gate", False)))
        self.mute_var.set(bool(cfg.get("mute", False)))
        self.gain_slider.set(float(cfg.get("gain", 1.0)))
        self._on_gain(self.gain_slider.get())
        self.gate_slider.set(float(cfg.get("noise_gate_db", -60.0)))
        self._on_gate(self.gate_slider.get())
        # Fx preset
        fx_id = cfg.get("fx", "normal")
        for pid, lbl in FX_PRESETS:
            if pid == fx_id:
                self.fx_combo.set(lbl)
                break
        self._update_mode_ui()

    def _collect_config(self) -> dict:
        return {
            "port": int(self.port_entry.get() or 8125) if self.port_entry.get().isdigit() else 8125,
            "mode": self._mode,
            "output_device_label": self.device_combo.get(),
            "monitor": bool(self.monitor_var.get()),
            "voice_gate": bool(self.ns_var.get()),
            "gain": float(self.gain_slider.get()),
            "noise_gate_db": float(self.gate_slider.get()),
            "fx": next((pid for pid, lbl in FX_PRESETS if lbl == self.fx_combo.get()), "normal"),
            "mute": bool(self.mute_var.get()),
        }

    def _persist(self) -> None:
        """Debounced save — coalesces rapid slider changes into one write."""
        if self._save_scheduled:
            return
        self._save_scheduled = True

        def flush():
            self._save_scheduled = False
            try:
                config.save(self._collect_config())
            except Exception:
                pass

        self.after(400, flush)

    def _on_close(self) -> None:
        try:
            config.save(self._collect_config())
        except Exception:
            pass
        if self._server is not None:
            self._server.stop()
        if self._usb_tunnel_open:
            try:
                close_usb_tunnel(int(self.port_entry.get()))
            except Exception:
                pass
        self.destroy()


def main() -> None:
    # Subcommand: elevated rename helper baked into the same executable.
    if len(sys.argv) >= 3 and sys.argv[1] == "--rename-worker":
        import json as _json
        from pathlib import Path as _P
        out_path = _P(sys.argv[2])
        try:
            from virtual_mic import rename_cable_to_micky as _rn
            ok, msg, log = _rn()
            payload = {"ok": bool(ok), "msg": msg, "log": log or []}
        except Exception as e:
            payload = {"ok": False, "msg": f"Hata: {e}", "log": []}
        try:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(_json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass
        sys.exit(0 if payload["ok"] else 1)

    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
