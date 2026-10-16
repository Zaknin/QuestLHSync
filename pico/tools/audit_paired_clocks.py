"""Read-only, fail-closed Pico K0 paired-clock analysis (Python 3.11+).

Producer ring_ts84_ns is BOOTTIME buffer write-lock time; vendor_ns
(slot+122, duplicated in slot+114 on archived captures) is AImage's
camera timestamp with unverified epoch. Pairing by K0 sequence avoids
jitter from regressing a past frame against probe MONOTONIC time.
Do not use this program to enable live Lighthouse pose corrections.
"""
import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path
from statistics import median

CAMS = (0, 3, 4, 5)
REQUIRED = {"cam", "seq", "ring_ts84_ns", "vendor_ns", "mono_ns", "boot_ns", "newest_seq"}


def percentile(x, q):
    x = sorted(x)
    if not x:
        raise ValueError("empty sample")
    pos = (len(x) - 1) * q
    idx = int(pos)
    return x[idx] + (x[min(idx + 1, len(x) - 1)] - x[idx]) * (pos - idx)


def fit_rate(rows):
    """Fit image-minus-producer clock gap by BOOTTIME, binned to 1-second medians."""
    t0 = rows[0]["ring_ts84_ns"]
    bins = defaultdict(list)
    for row in rows:
        dt = row["ring_ts84_ns"] - t0
        bins[dt // 1_000_000_000].append((dt, row["vendor_ns"] - row["ring_ts84_ns"]))
    points = [(median(x for x, _ in batch) / 1e9,
               median(y for _, y in batch) / 1e9)
              for _, batch in sorted(bins.items()) if len(batch) >= 5]
    if len(points) < 8:
        raise ValueError("Need 8+ populated one-second clock bins")
    mx = sum(x for x, _ in points) / len(points)
    my = sum(y for _, y in points) / len(points)
    slope = sum((x - mx) * (y - my) for x, y in points) / sum((x - mx) ** 2 for x, _ in points)
    intercept = my - slope * mx
    residual_us = [(y - intercept - slope * x) * 1e6 for x, y in points]
    return dict(rate_difference_ppm=slope * 1e6,
                bins=len(points), binned_residual_median_abs_us=median(abs(z) for z in residual_us))


def analyze(path):
    camera_rows = defaultdict(list)
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames or not REQUIRED.issubset(reader.fieldnames):
            raise ValueError("Not Pico --clock-scan CSV")
        for lineno, text in enumerate(reader, 2):
            try:
                item = {field: int(text[field]) for field in REQUIRED}
            except (ValueError, TypeError, KeyError) as exc:
                raise ValueError(f"Line {lineno}: invalid integer") from exc
            if item["cam"] not in CAMS:
                raise ValueError(f"Line {lineno}: unknown camera")
            if item["seq"] % 2 != 1 or item["newest_seq"] <= item["seq"]:
                raise ValueError(f"Line {lineno}: invalid completed K0 slot")
            camera_rows[item["cam"]].append(item)
    if set(camera_rows) != set(CAMS):
        raise ValueError("Must include all four K0 cameras")
    stats, groups = {}, defaultdict(dict)
    for cam in CAMS:
        rows = sorted(camera_rows[cam], key=lambda x: x["ring_ts84_ns"])
        if len(rows) < 150:
            raise ValueError(f"C{cam}: need 150+ frame samples")
        if any(b["seq"] <= a["seq"] for a, b in zip(rows, rows[1:])):
            raise ValueError(f"C{cam}: nonmonotonic / duplicate sequence")
        if any(b["vendor_ns"] <= a["vendor_ns"] for a, b in zip(rows, rows[1:])):
            raise ValueError(f"C{cam}: nonmonotonic image timestamp")
        gaps = [(r["vendor_ns"] - r["ring_ts84_ns"]) / 1e6 for r in rows]
        ages = [(r["boot_ns"] - r["ring_ts84_ns"]) / 1e6 for r in rows]
        offsets = [(r["boot_ns"] - r["mono_ns"]) / 1e6 for r in rows]
        if min(ages) < 0:
            raise ValueError(f"C{cam}: producer write-lock is in the future")
        rate = fit_rate(rows)
        stats[str(cam)] = {
            "samples": len(rows),
            "producer_to_image_epoch_gap_median_ms": median(gaps),
            "gap_p10_p90_ms": [percentile(gaps, .1), percentile(gaps, .9)],
            "camera_vs_producer_boottime_rate_ppm": rate["rate_difference_ppm"],
            "binned_residual_median_abs_us": rate["binned_residual_median_abs_us"],
            "rate_fit_one_second_bins": rate["bins"],
            "producer_write_to_probe_median_ms": median(ages),
            "boot_minus_mono_offset_ms": median(offsets),
            "boot_minus_mono_span_ms": max(offsets) - min(offsets),
            "penultimate_slot_fraction": sum(r["newest_seq"] - r["seq"] == 2 for r in rows)/len(rows),
        }
        for r in rows:
            if cam in groups[r["seq"]]:
                raise ValueError("duplicate sequence/camera")
            groups[r["seq"]][cam] = r["vendor_ns"]
    aligned = [v for v in groups.values() if set(v) == set(CAMS)]
    if len(aligned) < 100:
        raise ValueError("Too few four-camera matched sequence groups")
    spreads = [max(v.values()) - min(v.values()) for v in aligned]
    return {
        "status": "RATE_ONLY_ABSOLUTE_EPOCH_UNRESOLVED",
        "source": Path(path).name,
        "shared_sequence_groups": len(aligned),
        "image_stamp_max_intercamera_ns": max(spreads),
        "image_stamp_exact_equal_groups": sum(s == 0 for s in spreads),
        "per_camera": stats,
        "flags": {"camera_relative_clock_rate_measured": True,
                  "camera_clock_epoch_verified": False,
                  "physical_exposure_time_verified": False,
                  "hmd_pose_timebase_verified": False,
                  "live_lighthouse_correction_allowed": False},
        "interpretation": "Rate fitted using same-frame producer BOOTTIME, NOT probe time. A 20s sample cannot establish long-run rate or absolute sensor epoch. No live correction is authorized."
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = json.dumps(analyze(args.csv), ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(report + "\n", encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()
