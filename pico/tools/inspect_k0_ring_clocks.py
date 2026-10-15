"""Read-only analysis of Pico K0 ring clock candidates from raw .bin or .zip.

Does not decode pixels or export private camera data. These fields are NOT
validated physical exposure timestamps.
"""
import argparse
import json
import re
import struct
import zipfile
from collections import defaultdict
from pathlib import Path
from statistics import median

STRIDE, SLOTS, HEADER = 308026, 5, 20
EXPECTED = HEADER + STRIDE * SLOTS


def decode_ring(data):
    if len(data) != EXPECTED:
        raise ValueError("unexpected K0 ring size")
    version, stride, slots, ring_index, header = struct.unpack_from("<5I", data, 0)
    if (version, stride, slots, header) != (1, STRIDE, SLOTS, HEADER) or ring_index >= SLOTS:
        raise ValueError("unexpected shared-memory ring descriptor")
    frames = []
    for i in range(SLOTS):
        base = HEADER + STRIDE * i
        seq, = struct.unpack_from("<Q", data, base + 146)
        ts84, = struct.unpack_from("<Q", data, base + 84)
        ts122, = struct.unpack_from("<Q", data, base + 122)
        ts130, = struct.unpack_from("<Q", data, base + 130)
        exposure, = struct.unpack_from("<I", data, base + 110)
        if seq % 2 == 1 and ts84 and ts122 and ts130 and exposure == 4:
            frames.append((seq, ts84, ts122, ts130))
    return sorted(frames)


def analyze(path):
    source = Path(path)
    if source.suffix.lower() == ".zip":
        with zipfile.ZipFile(source) as archive:
            inputs = [(i.filename, archive.read(i)) for i in archive.infolist()
                      if i.filename.lower().endswith(".bin") and i.file_size == EXPECTED]
    else:
        inputs = [(source.name, source.read_bytes())]
    groups = defaultdict(lambda: {"gap": [], "late": [], "step84": [], "step122": [], "rings": 0})
    for name, data in inputs:
        match = re.search(r"C([0345]).*K0|c([0345]).*k0", name)
        cam = (match.group(1) or match.group(2)) if match else "unknown"
        frames = decode_ring(data)
        if len(frames) < 2:
            continue
        g = groups[cam]
        g["rings"] += 1
        for seq, a, b, c in frames:
            g["gap"].append((b-a) / 1e6)
            g["late"].append((b-c) / 1e6)
        for before, after in zip(frames, frames[1:]):
            if after[0] - before[0] == 2:
                g["step84"].append((after[1] - before[1]) / 1e6)
                g["step122"].append((after[2] - before[2]) / 1e6)
    if not groups:
        raise ValueError("No usable finished K0 camera rings")
    return {"source": source.name, "status": "CLOCK_CANDIDATES_ONLY", "per_camera": {
        cam: {"rings": g["rings"], "frames": len(g["gap"]),
              "slot122_minus_slot84_ms_median": median(g["gap"]),
              "slot122_minus_slot84_ms_min": min(g["gap"]),
              "slot122_minus_slot84_ms_max": max(g["gap"]),
              "slot122_minus_slot130_ms_median": median(g["late"]),
              "slot84_step_ms_median": median(g["step84"]) if g["step84"] else None,
              "slot122_step_ms_median": median(g["step122"]) if g["step122"] else None}
        for cam, g in sorted(groups.items())}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ring_or_zip", type=Path)
    args = parser.parse_args()
    print(json.dumps(analyze(args.ring_or_zip), indent=2))


if __name__ == "__main__":
    main()
