"""Real-time voice effect presets for 16-bit PCM streams.

Each effect runs on small chunks (~1024 samples) and keeps its own state between
calls, so the output is continuous. Effects operate on float32 in range [-1, 1]
and return the same shape.
"""
from __future__ import annotations

from typing import Optional

import numpy as np

PRESETS = [
    ("normal", "Normal"),
    ("robot", "Robot"),
    ("eko", "Eko"),
    ("derin", "Derin"),
    ("uzay", "Uzay"),
    ("yuksek", "Yüksek"),
]


class VoiceFx:
    """Per-connection voice effect state machine."""

    def __init__(self) -> None:
        self.preset: str = "normal"
        self._sr: int = 48000
        # Echo buffer (max ~1s)
        self._echo_buf = np.zeros(48000, dtype=np.float32)
        self._echo_pos = 0
        # Ring-mod phase
        self._rm_phase = 0.0
        # LP filter state for 'derin'
        self._lp_state = 0.0
        # Flanger buffer for 'uzay'
        self._fl_buf = np.zeros(2400, dtype=np.float32)  # 50 ms @ 48k
        self._fl_pos = 0
        self._fl_phase = 0.0
        # Simple pitch shift (OLA)
        self._ps_buf = np.zeros(0, dtype=np.float32)

    def set_sample_rate(self, sr: int) -> None:
        if sr != self._sr:
            self._sr = sr
            self._echo_buf = np.zeros(int(sr * 1.0), dtype=np.float32)
            self._echo_pos = 0
            self._fl_buf = np.zeros(int(sr * 0.05), dtype=np.float32)
            self._fl_pos = 0
            self._rm_phase = 0.0

    def process(self, x: np.ndarray) -> np.ndarray:
        """Apply current preset to float32 mono samples. Shape: (N,)"""
        if self.preset == "normal" or x.size == 0:
            return x
        if self.preset == "robot":
            return self._robot(x)
        if self.preset == "eko":
            return self._echo(x)
        if self.preset == "derin":
            return self._derin(x)
        if self.preset == "uzay":
            return self._flanger(x)
        if self.preset == "yuksek":
            return self._pitch_up(x)
        return x

    # ---- Effects -------------------------------------------------------
    def _robot(self, x: np.ndarray) -> np.ndarray:
        sr = self._sr
        n = x.size
        t = (np.arange(n) + self._rm_phase) / sr
        carrier = np.sin(2.0 * np.pi * 60.0 * t)
        self._rm_phase += n
        y = x * carrier * 1.2
        return y

    def _echo(self, x: np.ndarray) -> np.ndarray:
        buf = self._echo_buf
        L = buf.size
        delay = int(self._sr * 0.22)
        fb = 0.45
        y = np.empty_like(x)
        pos = self._echo_pos
        for i in range(x.size):
            read_idx = (pos - delay) % L
            delayed = buf[read_idx]
            s = x[i] + 0.55 * delayed
            buf[pos] = x[i] + fb * delayed
            y[i] = s
            pos += 1
            if pos >= L:
                pos = 0
        self._echo_pos = pos
        return y

    def _derin(self, x: np.ndarray) -> np.ndarray:
        # Single-pole LP at ~700 Hz + subtle ring mod at 25 Hz + gain
        alpha = 1.0 - np.exp(-2.0 * np.pi * 700.0 / self._sr)
        y = np.empty_like(x)
        s = self._lp_state
        for i in range(x.size):
            s += alpha * (x[i] - s)
            y[i] = s
        self._lp_state = s
        t = (np.arange(x.size) + self._rm_phase) / self._sr
        mod = 0.6 + 0.4 * np.sin(2.0 * np.pi * 25.0 * t)
        self._rm_phase += x.size
        return y * mod * 1.4

    def _flanger(self, x: np.ndarray) -> np.ndarray:
        # Modulated short delay (3–8 ms) mixed with dry signal
        buf = self._fl_buf
        L = buf.size
        y = np.empty_like(x)
        pos = self._fl_pos
        phase = self._fl_phase
        rate = 0.6  # Hz sweep
        min_d = int(self._sr * 0.003)
        max_d = int(self._sr * 0.008)
        depth = max_d - min_d
        for i in range(x.size):
            lfo = (np.sin(2.0 * np.pi * phase) + 1.0) * 0.5
            d = min_d + int(depth * lfo)
            read_idx = (pos - d) % L
            y[i] = 0.55 * x[i] + 0.6 * buf[read_idx]
            buf[pos] = x[i] + 0.3 * buf[read_idx]
            pos = (pos + 1) % L
            phase += rate / self._sr
            if phase > 1.0:
                phase -= 1.0
        self._fl_pos = pos
        self._fl_phase = phase
        return y

    def _pitch_up(self, x: np.ndarray) -> np.ndarray:
        # Cheap chipmunk effect: resample up by factor 1.5 then pad/truncate to input length.
        # Adds aliasing but is low-latency.
        ratio = 1.5
        idx = np.arange(0, x.size, ratio)
        idx_i = idx.astype(np.int64)
        idx_i = np.clip(idx_i, 0, x.size - 1)
        y_short = x[idx_i]
        y = np.zeros_like(x)
        n = min(x.size, y_short.size)
        y[:n] = y_short[:n]
        # Slight formant shift via LP to reduce harshness
        alpha = 1.0 - np.exp(-2.0 * np.pi * 3500.0 / self._sr)
        s = 0.0
        for i in range(y.size):
            s += alpha * (y[i] - s)
            y[i] = s
        return y * 1.1
