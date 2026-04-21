"""Smoke test: send a 440 Hz sine wave to the Micky server for 2 seconds."""
import socket
import struct
import time
import numpy as np

MAGIC = b"MIKY"
SR = 48000
CH = 1
BITS = 16
DURATION = 2.0


def main(host="127.0.0.1", port=8125) -> None:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.connect((host, port))
    s.sendall(struct.pack("<4sIHH", MAGIC, SR, CH, BITS))
    ack = s.recv(2)
    assert ack == b"OK", f"unexpected ack: {ack!r}"
    print("handshake OK — streaming tone…")

    block = 1024
    t = np.arange(block) / SR
    phase = 0.0
    sent = 0
    start = time.time()
    while time.time() - start < DURATION:
        freq = 440.0
        samples = (np.sin(2 * np.pi * freq * t + phase) * 0.3 * 32767).astype(np.int16)
        phase += 2 * np.pi * freq * block / SR
        s.sendall(samples.tobytes())
        sent += samples.nbytes
        time.sleep(block / SR)
    print(f"sent {sent} bytes")
    s.close()


if __name__ == "__main__":
    main()
