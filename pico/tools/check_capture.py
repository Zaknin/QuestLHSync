"""Quick validation of a *local* Pico calibration recording (no uploads/network).

Input: %LOCALAPPDATA%\\QuestLHSync\\recordings\\qlhs-*.txt
Requires only the standard Python library. Does not change the recording.
"""
import argparse
from collections import Counter
from pathlib import Path


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("recording", type=Path)
    a = p.parse_args()
    counts = Counter()
    spots = Counter()
    station_samples = Counter()
    channels = {}
    intervals = {}
    bounds = [[float("inf"), float("-inf")] for _ in range(3)]
    malformed = 0
    with a.recording.open("r", encoding="utf-8", errors="replace") as f:
        for raw in f:
            parts = raw.split()
            if len(parts) < 3:
                continue
            try:
                timestamp = int(parts[0])
            except ValueError:
                continue
            kind = parts[1]
            try:
                if kind == "U" and len(parts) >= 9 and parts[2] == "F":
                    cam = int(parts[3])
                    blob_count = int(parts[7])
                    if blob_count < 0:
                        continue
                    counts[f"C{cam}"] += 1
                    spots[f"C{cam}"] += blob_count
                    intervals.setdefault("frames", [timestamp, timestamp])[1] = timestamp
                elif kind == "P" and parts[2] == "0" and len(parts) >= 15:
                    counts["HMD poses"] += 1
                    x, y, z = float(parts[6]), float(parts[10]), float(parts[14])
                    for b, v in zip(bounds, (x, y, z)):
                        b[0] = min(b[0], v)
                        b[1] = max(b[1], v)
                    intervals.setdefault("poses", [timestamp, timestamp])[1] = timestamp
                elif kind == "S" and len(parts) >= 11:
                    station = parts[2]
                    station_samples[station] += 1
                    channels[station] = parts[3]
                    intervals.setdefault("stations", [timestamp, timestamp])[1] = timestamp
            except (ValueError, IndexError):
                malformed += 1
    print("Recording:", a.recording)
    for k in sorted(counts):
        print(f"  {k}: {counts[k]}"+ (f", {spots[k]} blobs" if k.startswith("C") else ""))
    print("  Base stations:", len(station_samples))
    for name in sorted(station_samples):
        print(f"    {name}: channel={channels[name]}, snapshots={station_samples[name]}")
    for key in ("frames", "poses", "stations"):
        if key in intervals:
            st, en = intervals[key]
            print(f"  {key} covered {(en-st)/1e9:.1f} sec")
    if counts["HMD poses"]:
        print("  HMD position spread:", ", ".join(f"{b[1]-b[0]:.2f} m" for b in bounds))
    if malformed:
        print("  Malformed relevant lines:", malformed)
    ok = all(counts[f"C{x}"] >= 200 for x in (0, 3, 4, 5))
    ok &= counts["HMD poses"] >= 200 and len(station_samples) >= 2
    ok &= all(station_samples[x] >= 10 for x in station_samples)
    if ok:
        print("CAPTURE HAS RAW CAMERA SIGHTINGS + HMD POSES + STATION POSES")
        print("Not proof of correct camera mapping or tracking alignment.")
    else:
        print("INCOMPLETE CAPTURE: need 4 cameras, moving HMD and >=2 visible stations")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
