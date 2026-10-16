"""Pico P2: falsifiable, read-only, in-session QTIMER ↔ K0 clock comparison.

Inputs are PRIVATE text-only dumpsys pvrtracking snapshots and a four-camera
PicoFrameReader --clock-scan CSV recorded between them. Never applies offsets
to K0 frames or live SteamVR poses. Python 3.11+, stdlib only.
"""
import argparse
import csv
import json
import re
from collections import defaultdict
from pathlib import Path
from statistics import median

CAMERAS = (0, 3, 4, 5)
TIME_LINE = re.compile(
    r"^time boottime\s+(\d+),\s*monotime\s+(\d+),\s*qtimer\s+(\d+)\s*$",
    re.MULTILINE,
)


def parse_pvr_snapshot(path):
    text = Path(path).read_text(encoding="utf-8-sig", errors="replace")
    hits = TIME_LINE.findall(text)
    if len(hits) != 1:
        raise ValueError(f"{Path(path).name}: expected one PVR clock line; found {len(hits)}")
    boot, mono, qtimer = (int(v) for v in hits[0])
    if min(boot, mono, qtimer) <= 0:
        raise ValueError("PVR clock must be positive")
    return {"boottime_ns": boot, "monotime_ns": mono, "qtimer_ns": qtimer,
            "qtimer_minus_pvr_boot_ns": qtimer - boot,
            "pvr_boot_minus_mono_ns": boot - mono}


def parse_k0_csv(path):
    by_camera = defaultdict(list)
    required = {"cam", "seq", "ring_ts84_ns", "vendor_ns", "boot_ns"}
    with Path(path).open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            raise ValueError("Not a Pico --clock-scan CSV")
        has_114 = "image_ts114_ns" in reader.fieldnames
        for line, raw in enumerate(reader, 2):
            try:
                r = {key: int(raw[key]) for key in required}
                if has_114 and int(raw["image_ts114_ns"]) != r["vendor_ns"]:
                    raise ValueError(f"line {line}: +114/+122 disagree")
            except (TypeError, KeyError, ValueError) as exc:
                raise ValueError(f"line {line}: invalid K0 row: {exc}") from exc
            if r["cam"] not in CAMERAS or r["seq"] % 2 != 1:
                raise ValueError(f"line {line}: unexpected camera / incomplete slot")
            if r["ring_ts84_ns"] <= 0 or r["vendor_ns"] <= r["ring_ts84_ns"]:
                raise ValueError(f"line {line}: invalid clock relation")
            if r["boot_ns"] < r["ring_ts84_ns"]:
                raise ValueError(f"line {line}: producer write appears in future")
            by_camera[r["cam"]].append(r)
    if set(by_camera) != set(CAMERAS):
        raise ValueError("All four K0 cameras are required")
    for cam in CAMERAS:
        rows = by_camera[cam]
        if len(rows) < 30:
            raise ValueError(f"C{cam}: fewer than 30 samples")
        if any(b["seq"] <= a["seq"] for a, b in zip(rows, rows[1:])):
            raise ValueError(f"C{cam}: duplicate/nonmonotonic sequence")
    return by_camera


def analyze(before_path, csv_path, after_path):
    before = parse_pvr_snapshot(before_path)
    after = parse_pvr_snapshot(after_path)
    cam_rows = parse_k0_csv(csv_path)
    all_rows = [r for records in cam_rows.values() for r in records]
    start = min(r["ring_ts84_ns"] for r in all_rows)
    end = max(r["ring_ts84_ns"] for r in all_rows)
    # This compares the PVR clock to the *same* producer BOOTTIME clock;
    # if PVR dumpsys uses another epoch, reject before inferring delay.
    epoch_bracketed = (
        before["boottime_ns"] <= start + 1_000_000_000
        and after["boottime_ns"] >= end - 1_000_000_000
        and 0 <= start - before["boottime_ns"] <= 60_000_000_000
        and 0 <= after["boottime_ns"] - end <= 60_000_000_000
        and before["boottime_ns"] < after["boottime_ns"]
    )
    offsets = (before["qtimer_minus_pvr_boot_ns"],
               after["qtimer_minus_pvr_boot_ns"])
    median_offset = median(offsets)
    drift_ns = offsets[1] - offsets[0]
    per_camera = {}
    for cam in CAMERAS:
        gaps = [r["vendor_ns"] - r["ring_ts84_ns"] for r in cam_rows[cam]]
        # This is a hypothesis-derived apparent write-after-camera interval;
        # NOT validated physical exposure latency.
        lag = median_offset - median(gaps)
        per_camera[str(cam)] = {
            "frames": len(gaps),
            "image_minus_producer_median_ms": median(gaps) / 1e6,
            "qtimer_model_apparent_producer_lag_ms": lag / 1e6,
        }
    plausible = (
        epoch_bracketed
        and abs(drift_ns) <= 2_000_000
        and all(0 <= p["qtimer_model_apparent_producer_lag_ms"] <= 100
                for p in per_camera.values())
    )
    return {
        "status": ("QTIMER_CANDIDATE_REQUIRES_SOURCE_PROOF" if plausible
                   else "QTIMER_HYPOTHESIS_NOT_ESTABLISHED"),
        "source": "read-only PVR dumpsys plus K0 clock-scan",
        "pvr_boot_brackets_k0_write_epoch": epoch_bracketed,
        "before_qtimer_minus_pvr_boot_ms": offsets[0] / 1e6,
        "after_qtimer_minus_pvr_boot_ms": offsets[1] / 1e6,
        "qtimer_offset_drift_ms": drift_ns / 1e6,
        "before_pvr_boot_minus_mono_ms": before["pvr_boot_minus_mono_ns"] / 1e6,
        "after_pvr_boot_minus_mono_ms": after["pvr_boot_minus_mono_ns"] / 1e6,
        "per_camera": per_camera,
        "flags": {
            "qtimer_timestamp_source_verified": False,
            "sensor_exposure_time_verified": False,
            "camera2_to_k0_mapping_verified": False,
            "steamvr_pose_clock_verified": False,
            "live_lighthouse_correction_allowed": False,
        },
        "interpretation": (
            "A positive apparent lag in the QTIMER model is only a consistency "
            "check. Dumpsys clock naming, vendor callback timestamp source, "
            "real exposure time and SteamVR pose alignment remain unverified. "
            "No numeric offset may be deployed in the live driver."
        ),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before", required=True, type=Path)
    parser.add_argument("--csv", required=True, type=Path)
    parser.add_argument("--after", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = analyze(args.before, args.csv, args.after)
    output = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(output, encoding="utf-8")
    print(output, end="")


if __name__ == "__main__":
    main()
