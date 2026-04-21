"""DSP helpers: high-pass filter, noise suppressor.

Lightweight implementations that keep state between calls so chunked audio
can be filtered without seams.
"""
from __future__ import annotations

import numpy as np


class BiquadHP:
    """Biquad high-pass filter (RBJ cookbook)."""

    def __init__(self, cutoff_hz: float, sample_rate: int, q: float = 0.707) -> None:
        self._w1 = 0.0
        self._w2 = 0.0
        self.configure(cutoff_hz, sample_rate, q)

    def configure(self, cutoff_hz: float, sample_rate: int, q: float = 0.707) -> None:
        w0 = 2.0 * np.pi * cutoff_hz / sample_rate
        alpha = np.sin(w0) / (2.0 * q)
        cos_w = np.cos(w0)
        b0 = (1.0 + cos_w) / 2.0
        b1 = -(1.0 + cos_w)
        b2 = (1.0 + cos_w) / 2.0
        a0 = 1.0 + alpha
        a1 = -2.0 * cos_w
        a2 = 1.0 - alpha
        self.b0 = b0 / a0
        self.b1 = b1 / a0
        self.b2 = b2 / a0
        self.a1 = a1 / a0
        self.a2 = a2 / a0

    def process(self, x: np.ndarray) -> np.ndarray:
        y = np.empty_like(x)
        w1, w2 = self._w1, self._w2
        b0, b1, b2, a1, a2 = self.b0, self.b1, self.b2, self.a1, self.a2
        for i in range(x.size):
            w0 = x[i] - a1 * w1 - a2 * w2
            y[i] = b0 * w0 + b1 * w1 + b2 * w2
            w2 = w1
            w1 = w0
        self._w1, self._w2 = w1, w2
        return y


class BiquadLP:
    """Biquad low-pass filter (RBJ cookbook)."""

    def __init__(self, cutoff_hz: float, sample_rate: int, q: float = 0.707) -> None:
        self._w1 = 0.0
        self._w2 = 0.0
        self.configure(cutoff_hz, sample_rate, q)

    def configure(self, cutoff_hz: float, sample_rate: int, q: float = 0.707) -> None:
        w0 = 2.0 * np.pi * cutoff_hz / sample_rate
        alpha = np.sin(w0) / (2.0 * q)
        cos_w = np.cos(w0)
        b0 = (1.0 - cos_w) / 2.0
        b1 = 1.0 - cos_w
        b2 = (1.0 - cos_w) / 2.0
        a0 = 1.0 + alpha
        a1 = -2.0 * cos_w
        a2 = 1.0 - alpha
        self.b0 = b0 / a0
        self.b1 = b1 / a0
        self.b2 = b2 / a0
        self.a1 = a1 / a0
        self.a2 = a2 / a0

    def process(self, x: np.ndarray) -> np.ndarray:
        y = np.empty_like(x)
        w1, w2 = self._w1, self._w2
        b0, b1, b2, a1, a2 = self.b0, self.b1, self.b2, self.a1, self.a2
        for i in range(x.size):
            w0 = x[i] - a1 * w1 - a2 * w2
            y[i] = b0 * w0 + b1 * w1 + b2 * w2
            w2 = w1
            w1 = w0
        self._w1, self._w2 = w1, w2
        return y


class VoiceGate:
    """Voice-activity gate. Detection uses RMS + crest factor (lightweight,
    numpy-vectorised — no per-sample Python loops). Output is the ORIGINAL
    signal multiplied by a smooth gain envelope so audio quality is preserved
    whether the gate is open or closed.
    """

    def __init__(self, sample_rate: int = 48000) -> None:
        self.enabled = False  # default OFF — only turn on for noisy environments
        self._sr = sample_rate
        self._gain = 0.0
        self._target = 0.0
        self._hangover_left = 0
        self._noise_floor = 0.003
        self._voice_frames = 0
        self._hangover_samples = int(0.25 * sample_rate)

    def set_sample_rate(self, sr: int) -> None:
        if sr == self._sr:
            return
        self._sr = sr
        self._hangover_samples = int(0.25 * sr)
        self._gain = 0.0
        self._noise_floor = 0.003

    def process(self, x: np.ndarray) -> np.ndarray:
        if not self.enabled or x.size == 0:
            return x
        # Vectorised measurements — no Python loops
        rms = float(np.sqrt(np.mean(x * x) + 1e-12))
        peak = float(np.max(np.abs(x)))
        crest = peak / (rms + 1e-9)

        # Adaptive noise floor on quiet chunks
        if rms < self._noise_floor * 1.6:
            self._noise_floor = 0.96 * self._noise_floor + 0.04 * rms
        self._noise_floor = max(self._noise_floor, 1e-4)

        # Open when loud enough AND not a sharp transient (klavye tıkırtısı crest ~15+)
        is_voice = rms > self._noise_floor * 2.2 and crest < 8.0

        n = x.size
        if is_voice:
            self._voice_frames += 1
            if self._voice_frames >= 2:
                self._target = 1.0
                self._hangover_left = self._hangover_samples
        else:
            self._voice_frames = 0
            if self._hangover_left > 0:
                self._hangover_left = max(0, self._hangover_left - n)
                if self._hangover_left == 0:
                    self._target = 0.0

        # Smooth gain ramp within the chunk, applied to the ORIGINAL signal
        ramp = np.linspace(self._gain, self._target, n, dtype=np.float32)
        self._gain = float(ramp[-1])
        return x * ramp


# Back-compat alias — older code may import NoiseSuppressor; map to VoiceGate.
NoiseSuppressor = VoiceGate
