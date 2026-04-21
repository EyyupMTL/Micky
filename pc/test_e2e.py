"""Headless end-to-end test: start server + connect test client."""
import threading
import time
import socket
import struct
import numpy as np

from server import AudioServer

status_log = []
connects = []
levels = []


def main():
    srv = AudioServer(
        on_status=lambda s: (status_log.append(s), print(f"[status] {s}")),
        on_level=lambda v: levels.append(v),
        on_connect=lambda info: (connects.append(info), print(f"[connect] {info}")),
    )
    # Use device=None (default). This may fail on headless CI without an audio device,
    # but on this machine it should be fine.
    srv.start(8126, None)
    time.sleep(0.3)

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.connect(("127.0.0.1", 8126))
    SR, CH, BITS = 48000, 1, 16
    s.sendall(struct.pack("<4sIHH", b"MIKY", SR, CH, BITS))
    ack = s.recv(2)
    assert ack == b"OK", f"got {ack!r}"
    print("handshake OK")

    # Stream 0.8 s of silence (smaller, faster) — just verify the pipe works
    block = 512
    for _ in range(int(0.8 * SR / block)):
        s.sendall(np.zeros(block, dtype=np.int16).tobytes())
        time.sleep(block / SR)
    time.sleep(0.2)
    s.close()
    time.sleep(0.5)
    srv.stop()

    assert any("Bağlandı" in m for m in status_log), f"no connect status: {status_log}"
    assert connects and connects[0] is not None, f"no connect info: {connects}"
    assert levels, "no level callbacks"
    print(f"OK — {len(levels)} level updates, status log: {status_log}")


if __name__ == "__main__":
    main()
