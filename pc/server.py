"""Micky audio TCP server. Bidirectional framed protocol + effects chain."""
from __future__ import annotations

import socket
import struct
import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional

import numpy as np
import sounddevice as sd

from dsp import VoiceGate
from voice_fx import VoiceFx


class RingBuffer:
    """Jitter-tolerant PCM ring buffer for audio output.

    Two goals at once:
      - **Anti-drift**: if the buffer grows past max, drop oldest bytes so
        latency never unboundedly climbs.
      - **Anti-choppy (priming)**: when the buffer drains to empty we mark
        it "un-primed" and emit silence on subsequent reads until it fills
        to target again. This absorbs Wi-Fi jitter without repeated micro
        underruns — one small silence gap instead of "kesik kesik".

    Producer writes from the network thread; consumer reads from the
    PortAudio callback thread. Access is guarded by a lock.
    """

    def __init__(self, sample_rate: int, channels: int,
                 target_ms: int = 100, max_ms: int = 400) -> None:
        self._bpf = channels * 2
        self._target = int(sample_rate * self._bpf * target_ms / 1000)
        self._max = int(sample_rate * self._bpf * max_ms / 1000)
        self._channels = channels
        self._buf = bytearray()
        self._lock = threading.Lock()
        self._primed = False
        self.dropped_bytes = 0
        self.underruns = 0

    def write(self, data: bytes) -> None:
        with self._lock:
            self._buf.extend(data)
            if not self._primed and len(self._buf) >= self._target:
                self._primed = True
            if len(self._buf) > self._max:
                extra = len(self._buf) - self._target
                del self._buf[:extra]
                self.dropped_bytes += extra

    def read_into(self, out: np.ndarray) -> None:
        n_frames = out.shape[0]
        want = n_frames * self._bpf
        with self._lock:
            if not self._primed:
                # Initial pre-fill ONLY. Once primed we never re-prime, even
                # on transient underruns — a short silence patch beats the
                # "e v v e e t t" stutter that re-priming causes on USB /
                # very low-jitter links.
                out[:] = 0
                return
            avail = len(self._buf)
            if avail >= want:
                data = bytes(self._buf[:want])
                del self._buf[:want]
                frames_have = n_frames
            else:
                # Soft underrun: consume what's there, pad rest with silence,
                # keep draining at the normal rate so short gaps are short.
                data = bytes(self._buf)
                self._buf.clear()
                frames_have = avail // self._bpf
                self.underruns += 1
        if frames_have:
            arr = np.frombuffer(data, dtype=np.int16)
            if self._channels == 1:
                out[:frames_have, 0] = arr
            else:
                out[:frames_have] = arr.reshape(-1, self._channels)
        if frames_have < n_frames:
            out[frames_have:] = 0

    def reset(self) -> None:
        with self._lock:
            self._buf.clear()
            self._primed = False
            self.dropped_bytes = 0
            self.underruns = 0

MAGIC = b"MIKY"
HEADER_FMT = "<4sIHH"
HEADER_SIZE = struct.calcsize(HEADER_FMT)
OK = b"OK"

# Frame types (after handshake, same 5-byte header in both directions)
FRAME_AUDIO = 1     # payload: raw PCM
FRAME_MUTE = 2      # payload: 1 byte (0 or 1)
FRAME_PING = 3      # payload: empty
FRAME_MODE = 4      # payload: UTF-8 mode string
FRAME_NOTE = 5      # payload: UTF-8 free text
FRAME_FX = 6        # payload: UTF-8 voice-fx preset id (normal|robot|eko|derin|uzay|yuksek)
FRAME_GAIN = 7      # payload: 4 bytes LE float — 0.0..3.0 multiplier


@dataclass
class StreamInfo:
    sample_rate: int
    channels: int
    bits: int
    client_addr: str
    client_mode: Optional[str] = None


class AudioServer:
    """Single-client TCP audio server. Bidirectional framed protocol."""

    def __init__(
        self,
        on_status: Callable[[str], None],
        on_level: Callable[[float], None],
        on_connect: Callable[[Optional[StreamInfo]], None],
        on_remote_mute: Optional[Callable[[bool], None]] = None,
        on_mode_mismatch: Optional[Callable[[Optional[str]], None]] = None,
        on_remote_fx: Optional[Callable[[str], None]] = None,
        on_remote_gain: Optional[Callable[[float], None]] = None,
    ) -> None:
        self.on_status = on_status
        self.on_level = on_level
        self.on_connect = on_connect
        self.on_remote_mute = on_remote_mute or (lambda _m: None)
        self.on_mode_mismatch = on_mode_mismatch or (lambda _m: None)
        self.on_remote_fx = on_remote_fx or (lambda _fx: None)
        self.on_remote_gain = on_remote_gain or (lambda _g: None)

        self.port: int = 8125
        self.output_device: Optional[int] = None
        self.monitor_device: Optional[int] = None
        self.monitor_enabled: bool = False
        self.gain: float = 1.0
        self.noise_gate_db: float = -60.0
        self.muted: bool = False
        self.server_mode: str = "wifi"  # updated by UI
        self.voice_fx = VoiceFx()
        self.voice_gate = VoiceGate()

        self._sock: Optional[socket.socket] = None
        self._accept_thread: Optional[threading.Thread] = None
        self._client_thread: Optional[threading.Thread] = None
        self._stream: Optional[sd.OutputStream] = None
        self._monitor_stream: Optional[sd.OutputStream] = None
        self._ring: Optional[RingBuffer] = None
        self._mon_ring: Optional[RingBuffer] = None
        self._running = False
        self._client_sock: Optional[socket.socket] = None
        self._send_lock = threading.Lock()
        self._info: Optional[StreamInfo] = None

    # ---- Lifecycle ----------------------------------------------------
    def start(self, port: int, output_device: Optional[int]) -> None:
        if self._running:
            return
        self.port = port
        self.output_device = output_device
        self._running = True
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("0.0.0.0", self.port))
        self._sock.listen(1)
        self._sock.settimeout(0.5)
        self._accept_thread = threading.Thread(target=self._accept_loop, daemon=True)
        self._accept_thread.start()
        self.on_status(f"Dinleniyor — 0.0.0.0:{self.port}")

    def stop(self) -> None:
        self._running = False
        try:
            if self._client_sock:
                self._client_sock.shutdown(socket.SHUT_RDWR)
                self._client_sock.close()
        except OSError:
            pass
        try:
            if self._sock:
                self._sock.close()
        except OSError:
            pass
        self._stop_stream()
        self.on_connect(None)
        self.on_status("Kapalı")

    # ---- Public control ----------------------------------------------
    def send_mute(self, muted: bool) -> None:
        """Push local mute state to the phone (user toggled on PC side)."""
        self.muted = muted
        self._send_frame(FRAME_MUTE, bytes([1 if muted else 0]))

    def send_mode(self) -> None:
        self._send_frame(FRAME_MODE, self.server_mode.encode("utf-8"))

    def send_fx(self, preset: str) -> None:
        """Push current FX preset to the phone (user changed it on PC side)."""
        self.voice_fx.preset = preset
        self._send_frame(FRAME_FX, preset.encode("utf-8"))

    def send_gain(self, gain: float) -> None:
        """Push gain value to phone (user moved PC slider)."""
        self.gain = max(0.0, min(3.0, float(gain)))
        self._send_frame(FRAME_GAIN, struct.pack("<f", self.gain))

    def set_monitor_enabled(self, enabled: bool, info: Optional[StreamInfo] = None) -> None:
        self.monitor_enabled = enabled
        if not enabled:
            self._close_monitor()
        elif self._stream is not None and info is not None:
            self._open_monitor(info)

    # ---- Internal: accept / client loop -------------------------------
    def _accept_loop(self) -> None:
        while self._running:
            try:
                assert self._sock is not None
                client, addr = self._sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            if self._client_sock is not None:
                try:
                    client.sendall(b"BUSY")
                    client.close()
                except OSError:
                    pass
                continue
            # Disable Nagle so our small control frames (MUTE/MODE/FX/PING)
            # are sent immediately — prevents 40–200 ms delay on Windows.
            try:
                client.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            except OSError:
                pass
            # Smaller OS receive buffer to reduce ingress queueing latency.
            try:
                client.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 64 * 1024)
            except OSError:
                pass
            self._client_sock = client
            self.on_status(f"Bağlandı: {addr[0]}:{addr[1]}")
            self._client_thread = threading.Thread(
                target=self._client_loop, args=(client, addr), daemon=True
            )
            self._client_thread.start()

    def _client_loop(self, client: socket.socket, addr) -> None:
        try:
            client.settimeout(5.0)
            header = self._recv_exact(client, HEADER_SIZE)
            if header is None:
                return
            magic, sample_rate, channels, bits = struct.unpack(HEADER_FMT, header)
            if magic != MAGIC or bits != 16 or channels not in (1, 2):
                client.sendall(b"ERR!")
                return
            client.sendall(OK)
            info = StreamInfo(sample_rate, channels, bits, f"{addr[0]}:{addr[1]}")
            self._info = info
            self.voice_fx.set_sample_rate(sample_rate)
            self.voice_gate.set_sample_rate(sample_rate)
            self.on_connect(info)
            self._start_stream(info)

            # Exchange mode, mute, fx, gain
            self.send_mode()
            self._send_frame(FRAME_MUTE, bytes([1 if self.muted else 0]))
            self._send_frame(FRAME_FX, self.voice_fx.preset.encode("utf-8"))
            self._send_frame(FRAME_GAIN, struct.pack("<f", float(self.gain)))

            client.settimeout(5.0)
            frame_bytes = 2 * channels
            audio_acc = bytearray()

            while self._running:
                hdr = self._recv_exact(client, 5)
                if hdr is None:
                    break
                type_ = hdr[0]
                length = struct.unpack("<I", hdr[1:5])[0]
                if length > 0:
                    payload = self._recv_exact(client, length)
                    if payload is None:
                        break
                else:
                    payload = b""

                if type_ == FRAME_AUDIO:
                    if len(payload) >= frame_bytes:
                        usable = (len(payload) // frame_bytes) * frame_bytes
                        audio_acc.extend(payload[:usable])
                        # Flush accumulated audio
                        raw = bytes(audio_acc)
                        audio_acc.clear()
                        self._play_chunk(raw, channels)
                elif type_ == FRAME_MUTE:
                    remote_muted = bool(payload and payload[0])
                    self.muted = remote_muted
                    self.on_remote_mute(remote_muted)
                elif type_ == FRAME_MODE:
                    client_mode = payload.decode("utf-8", errors="ignore").strip() or None
                    info.client_mode = client_mode
                    if client_mode and client_mode != self.server_mode:
                        self.on_mode_mismatch(client_mode)
                    else:
                        self.on_mode_mismatch(None)
                elif type_ == FRAME_PING:
                    self._send_frame(FRAME_PING, b"")
                elif type_ == FRAME_FX:
                    preset = payload.decode("utf-8", errors="ignore").strip()
                    if preset:
                        self.voice_fx.preset = preset
                        self.on_remote_fx(preset)
                elif type_ == FRAME_GAIN:
                    if len(payload) >= 4:
                        g = struct.unpack("<f", payload[:4])[0]
                        g = max(0.0, min(3.0, float(g)))
                        self.gain = g
                        self.on_remote_gain(g)
                # ignore unknown types
        finally:
            self._stop_stream()
            try:
                client.close()
            except OSError:
                pass
            self._client_sock = None
            self._info = None
            self.on_connect(None)
            self.on_mode_mismatch(None)
            if self._running:
                self.on_status(f"Dinleniyor — 0.0.0.0:{self.port}")

    # ---- Frame I/O ----------------------------------------------------
    def _recv_exact(self, sock: socket.socket, n: int) -> Optional[bytes]:
        buf = bytearray()
        while len(buf) < n:
            try:
                chunk = sock.recv(n - len(buf))
            except OSError:
                return None
            if not chunk:
                return None
            buf.extend(chunk)
        return bytes(buf)

    def _send_frame(self, type_: int, payload: bytes) -> None:
        sock = self._client_sock
        if sock is None:
            return
        header = bytes([type_]) + struct.pack("<I", len(payload))
        with self._send_lock:
            try:
                sock.sendall(header + payload)
            except OSError:
                pass

    # ---- Audio output -------------------------------------------------
    # Target output latency (seconds). Keeps total lip-sync under ~150 ms on
    # a well-behaved LAN; "low" alone on WASAPI shared mode can be 200–500 ms.
    TARGET_LATENCY = 0.04
    # Ring buffer sizing. The buffer stays around TARGET_MS while idle;
    # jitter up to (MAX_MS - TARGET_MS) is absorbed without drops. Target
    # must be small enough that USB feels immediate, large enough that
    # Wi-Fi bursts don't cause ~30 ms silence patches each time.
    RING_TARGET_MS = 60
    RING_MAX_MS = 280

    def _start_stream(self, info: StreamInfo) -> None:
        self._stop_stream()
        self._ring = RingBuffer(
            info.sample_rate, info.channels,
            target_ms=self.RING_TARGET_MS, max_ms=self.RING_MAX_MS,
        )
        ring = self._ring
        channels = info.channels

        def callback(outdata: np.ndarray, frames: int, time_info, status) -> None:
            ring.read_into(outdata)

        self._stream = sd.OutputStream(
            samplerate=info.sample_rate,
            channels=info.channels,
            dtype="int16",
            device=self.output_device,
            blocksize=0,  # let PortAudio choose the driver-native block size
            latency=self.TARGET_LATENCY,
            callback=callback,
        )
        self._stream.start()
        self._open_monitor(info)

    def _open_monitor(self, info: StreamInfo) -> None:
        if (
            not self.monitor_enabled
            or self.monitor_device == self.output_device
        ):
            return
        try:
            self._mon_ring = RingBuffer(
                info.sample_rate, info.channels,
                target_ms=self.RING_TARGET_MS, max_ms=self.RING_MAX_MS,
            )
            mon_ring = self._mon_ring

            def mon_callback(outdata: np.ndarray, frames: int, time_info, status) -> None:
                mon_ring.read_into(outdata)

            self._monitor_stream = sd.OutputStream(
                samplerate=info.sample_rate,
                channels=info.channels,
                dtype="int16",
                device=self.monitor_device,
                blocksize=int(info.sample_rate * 0.01),
                latency=self.TARGET_LATENCY,
                callback=mon_callback,
            )
            self._monitor_stream.start()
        except Exception as e:
            self.on_status(f"Monitor açılamadı: {e}")
            self._monitor_stream = None
            self._mon_ring = None

    def _close_monitor(self) -> None:
        if self._monitor_stream is not None:
            try:
                self._monitor_stream.stop()
                self._monitor_stream.close()
            except Exception:
                pass
            self._monitor_stream = None
        self._mon_ring = None

    def _stop_stream(self) -> None:
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        self._ring = None
        self._close_monitor()

    def _play_chunk(self, raw: bytes, channels: int) -> None:
        ring = self._ring
        if ring is None:
            return

        # Fast path: no processing needed — stream bytes straight to the ring.
        # Avoids float conversion and numpy work on every 20 ms chunk, which
        # matters on slower PCs and prevents spurious underruns.
        if (
            not self.voice_gate.enabled
            and self.noise_gate_db <= -59.0
            and abs(self.gain - 1.0) < 1e-3
            and not self.muted
            and self.voice_fx.preset == "normal"
        ):
            # Cheap level meter directly from int16
            arr_i = np.frombuffer(raw, dtype=np.int16)
            if arr_i.size:
                rms = float(np.sqrt(np.mean((arr_i.astype(np.float32) / 32768.0) ** 2) + 1e-12))
                self.on_level(min(1.0, rms * 3.0))
            ring.write(raw)
            if self._mon_ring is not None:
                self._mon_ring.write(raw)
            return

        samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
        if channels == 2:
            samples = samples.reshape(-1, 2).mean(axis=1)
            mono = samples
        else:
            mono = samples

        mono = self.voice_gate.process(mono)

        if self.noise_gate_db > -59.0:
            threshold = 10 ** (self.noise_gate_db / 20.0)
            if np.abs(mono).mean() < threshold:
                mono = mono * 0.0

        mono = mono * self.gain
        mono = self.voice_fx.process(mono)

        if self.muted:
            mono = mono * 0.0

        if mono.size:
            rms = float(np.sqrt(np.mean(mono * mono)))
            self.on_level(min(1.0, rms * 3.0))

        if channels == 2:
            out_float = np.stack([mono, mono], axis=1)
        else:
            out_float = mono

        np.clip(out_float, -1.0, 1.0, out=out_float)
        # Non-blocking write into the ring — overflow drops oldest so drift
        # can never accumulate into gradually-rising delay.
        out_bytes = (out_float * 32767.0).astype(np.int16).tobytes()
        ring.write(out_bytes)
        if self._mon_ring is not None:
            self._mon_ring.write(out_bytes)
