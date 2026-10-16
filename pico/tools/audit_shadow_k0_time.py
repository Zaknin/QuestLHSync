"""Pico P2: offline QTIMER -> MONOTONIC *shadow* projection (NEVER live).

Uses only owner-recorded, read-only four-camera K0 --clock-scan CSV plus
two in-session PVR clock snapshots. Every projected timestamp remains
diagnostic; no LHSync F records, SLAM, SteamVR pose, or factory profile
are changed. Integer nanoseconds throughout.
"""
import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path
from statistics import median

from pico.tools.audit_qtimer_bridge import CAMERAS, analyze, parse_pvr_snapshot

REQUIRED = {
    "cam", "seq", "newest_seq", "ring_ts84_ns", "vendor_ns",
    "mono_ns", "boot_ns", "boot_minus_mono_ns"
}


def interpolate(a, b, t, start, end):
    """Linear interpolation in exact integer nanoseconds, rounded to nearest."""
    if end <= start or not start <= t <= end:
        raise ValueError("timestamp outside bracket")
    delta = (b - a) * (t - start)
    span = end - start
    signed_round = (abs(delta) + span // 2) // span
    return a + (signed_round if delta >= 0 else -signed_round)


def percentile_ns(numbers, fraction):
    data = sorted(numbers)
    idx = (len(data) - 1) * fraction
    low = int(idx)
    upper = min(low + 1, len(data) - 1)
    return round(data[low] + (data[upper] - data[low]) * (idx - low))


def summary_ms(numbers):
    return {
        "min_ms": min(numbers) / 1e6,
        "p10_ms": percentile_ns(numbers, .1) / 1e6,
        "median_ms": median(numbers) / 1e6,
        "p90_ms": percentile_ns(numbers, .9) / 1e6,
        "max_ms": max(numbers) / 1e6,
    }


def parse_rows(path):
    rows = defaultdict(list)
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames or not REQUIRED.issubset(reader.fieldnames):
            raise ValueError("K0 scan CSV lacks required timing columns")
        with114 = "image_ts114_ns" in reader.fieldnames
        for line, record in enumerate(reader, 2):
            try:
                item = {field: int(record[field]) for field in REQUIRED}
                if with114 and int(record["image_ts114_ns"]) != item["vendor_ns"]:
                    raise ValueError("AImage slot+114 != vendor slot+122")
            except (TypeError, ValueError, KeyError) as error:
                raise ValueError(f"K0 scan line {line}: {error}") from error
            cam = item["cam"]
            if cam not in CAMERAS or item["seq"] <= 0 or item["seq"] % 2 == 0:
                raise ValueError(f"K0 scan line {line}: bad camera/slot")
            if item["newest_seq"] <= item["seq"]:
                raise ValueError(f"K0 scan line {line}: incomplete ring window")
            if any(item[field] <= 0 for field in (
                "ring_ts84_ns", "vendor_ns", "mono_ns", "boot_ns"
            )):
                raise ValueError(f"K0 scan line {line}: invalid clock")
            if rows[cam] and item["seq"] <= rows[cam][-1]["seq"]:
                raise ValueError(f"K0 scan line {line}: duplicate/regressive sequence")
            rows[cam].append(item)
    if set(rows) != set(CAMERAS):
        raise ValueError("Missing one or more K0 cameras")
    if any(len(rows[cam]) < 30 for cam in CAMERAS):
        raise ValueError("At least 30 frames per K0 camera required")
    return rows


def shadow(before_path, csv_path, after_path):
    baseline = analyze(before_path, csv_path, after_path)
    before = parse_pvr_snapshot(before_path)
    after = parse_pvr_snapshot(after_path)
    rows = parse_rows(csv_path)
    start, end = before["boottime_ns"], after["boottime_ns"]
    if end <= start:
        raise ValueError("PVR timestamps are out of order")

    q_mono0 = before["qtimer_ns"] - before["monotonic_ns"]
    q_mono1 = after["qtimer_ns"] - after["monotonic_ns"]
    b_mono0 = before["boottime_ns"] - before["monotonic_ns"]
    b_mono1 = after["boottime_ns"] - after["monotonic_ns"]
    offset_drift = q_mono1 - q_mono0
    per_camera = {}
    all_bounds = []
    for cam in CAMERAS:
        producer_lag, sampled_age, raw_gap, mono_bridge = [], [], [], []
        for row in rows[cam]:
            t = row["boot_ns"]  # same-query Android BOOTTIME clock sample
            if not start <= t <= end:
                all_bounds.append(False)
                continue
            all_bounds.append(True)
            q_mono = interpolate(q_mono0, q_mono1, t, start, end)
            b_mono = interpolate(b_mono0, b_mono1, t, start, end)
            # This is a *candidate* physical-event timestamp, never a verified one.
            shadow_mono = row["vendor_ns"] - q_mono
            producer_mono = row["ring_ts84_ns"] - b_mono
            lag = producer_mono - shadow_mono
            age = row["mono_ns"] - shadow_mono
            producer_lag.append(lag)
            sampled_age.append(age)
            raw_gap.append(row["vendor_ns"] - row["ring_ts84_ns"])
            mono_bridge.append(row["boot_minus_mono_ns"] - b_mono)
        if not producer_lag:
            per_camera[str(cam)] = {"frames": len(rows[cam]), "bracketed_frames": 0}
            continue
        per_camera[str(cam)] = {
            "frames": len(rows[cam]),
            "bracketed_frames": len(producer_lag),
            "qtimer_model_producer_lag": summary_ms(producer_lag),
            "qtimer_model_reader_age": summary_ms(sampled_age),
            "sampled_boot_mono_residual": summary_ms(mono_bridge),
            "raw_image_minus_producer": summary_ms(raw_gap),
        }
    total = sum(len(rows[cam]) for cam in CAMERAS)
    safe = bool(all_bounds) and all(all_bounds) and baseline[
        "status"] == "QTIMER_CANDIDATE_REQUIRES_SOURCE_PROOF"
    safe = safe and abs(offset_drift) <= 2_000_000
    for data in per_camera.values():
        if "qtimer_model_producer_lag" not in data:
            safe = False
            continue
        lag = data["qtimer_model_producer_lag"]
        age = data["qtimer_model_reader_age"]
        mono_residual = data["sampled_boot_mono_residual"]
        if (lag["min_ms"] < 0 or lag["max_ms"] > 100
                or age["min_ms"] < 0 or age["max_ms"] > 2000
                or max(abs(mono_residual["min_ms"]),
                       abs(mono_residual["max_ms"])) > 1):
            safe = False
    return {
        "status": ("QTIMER_SHADOW_PLAUSIBLE_UNVERIFIED" if safe else
                   "QTIMER_SHADOW_REJECTED_OR_INCOMPLETE"),
        "input_frames": total,
        "pvr_clock_bracketed_frames": sum(all_bounds),
        "pvr_qtimer_minus_monotonic_before_ms": q_mono0 / 1e6,
        "pvr_qtimer_minus_monotonic_after_ms": q_mono1 / 1e6,
        "qtimer_mono_drift_ms": offset_drift / 1e6,
        "per_camera": per_camera,
        "gates": {
            "qtimer_matches_arch_counter": "MEASURED_IN_SEPARATE_TEST",
            "k0_image_timestamp_is_qtimer": "UNVERIFIED",
            "sensor_exposure_timestamp": "UNVERIFIED",
            "k0_to_factory_camera_mapping": "UNVERIFIED",
            "steamvr_pose_clock": "UNVERIFIED",
            "live_lighthouse_correction_allowed": False,
        },
        "note": (
            "Shadow values are hypothetical and diagnostic only. This tool "
            "does NOT rewrite camera F timestamps, change exact_time, or "
            "prove actual exposure time. No live correction permitted."
        ),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before", type=Path, required=True)
    parser.add_argument("--csv", type=Path, required=True)
    parser.add_argument("--after", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = shadow(args.before, args.csv, args.after)
    output = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        args.output.write_text(output, encoding="utf-8")
    print(output, end="")


if __name__ == "__main__":
    main()
