"""Read-only QuestLHSync Pico P1 Wi-Fi smoke test, independent of SteamVR calibration.

Usage: python pico/test_stream.py 192.168.23.123 --seconds 12
Reads F and T diagnostics from upstream lhsyncd TCP 47280 and sends clock pings.
P1 intentionally returns a camera-calibration error; this test expects it.
"""
import argparse
from collections import Counter
import socket
import time


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ip", help="Pico Wi-Fi address")
    ap.add_argument("--seconds", type=int, default=12)
    args = ap.parse_args()
    if not 2 <= args.seconds <= 120:
        ap.error("seconds must be 2..120")
    frames, spots = Counter(), Counter()
    heartbeats = 0
    start = time.monotonic()
    with socket.create_connection((args.ip, 47280), timeout=5) as s:
        s.settimeout(0.5)
        data = bytearray()
        next_ping = 0
        seq = 0
        print(f"Connected to {args.ip}:47280, reading for {args.seconds}s", flush=True)
        while time.monotonic() - start < args.seconds:
            if time.monotonic() >= next_ping:
                seq += 1
                s.sendall(f"P {seq} {time.monotonic_ns()}\n".encode("ascii"))
                next_ping = time.monotonic() + 1
            try:
                part = s.recv(65536)
            except socket.timeout:
                continue
            if not part:
                print("Server closed connection")
                break
            data.extend(part)
            while b"\n" in data:
                record, _, data = data.partition(b"\n")
                line = record.decode("utf-8", errors="replace")
                fields = line.split()
                if not fields:
                    continue
                if fields[0] == "F" and len(fields) >= 6:
                    try:
                        cam = int(fields[1]); n = int(fields[5])
                    except ValueError:
                        continue
                    frames[cam] += 1
                    spots[cam] += max(0, n)
                elif fields[0] == "T":
                    heartbeats += 1
                elif fields[0] in ("H", "E", "W", "I"):
                    print(line[:240], flush=True)
    print("Camera  Frames  Spots")
    for c in (0, 3, 4, 5):
        print(f"C{c:<6} {frames[c]:<7} {spots[c]}")
    print(f"Total: {sum(frames.values())} frames, {sum(spots.values())} spots, {heartbeats} heartbeats")
    if not sum(frames.values()):
        raise SystemExit("FAIL: no F frames received; check root, tracking awake and Android logcat")
    print("PASS: Pico -> Wi-Fi -> original lhsyncd TCP F/T records")


if __name__ == "__main__":
    main()
