"""Offline PicoFrameReader --clock-scan CSV diagnostic.

slot+84 is a firmware-verified BOOTTIME buffer-write-lock stamp, NOT the
physical exposure time. slot+114 originates in AImage_getTimestamp and agrees with slot+122
in archived K0 rings, but their clock epoch versus Android BOOTTIME
and actual sensor exposure time are not independently calibrated.
Standard Python library only. No headset calibration values are required.
"""
import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path
from statistics import median

CAMERAS = (0, 3, 4, 5)
REQUIRED = {"sample", "cam", "seq", "newest_seq", "slot", "ring_index",
            "ring_ts84_ns", "image_ts114_ns", "vendor_ns", "ring_ts130_ns",
            "mono_ns", "boot_ns", "boot_minus_mono_ns"}


def percentile(items, pct):
    values = sorted(items)
    if not values:
        return None
    index = (len(values) - 1) * pct
    lo = int(index)
    return values[lo] + (values[min(lo + 1, len(values) - 1)] - values[lo]) * (index - lo)


def slope_ppm(rows):
    """Vendor rate vs MONOTONIC, centered to preserve nanosecond precision."""
    origin_m, origin_v = rows[0]["mono_ns"], rows[0]["vendor_ns"]
    x = [(r["mono_ns"] - origin_m) / 1e9 for r in rows]
    y = [(r["vendor_ns"] - origin_v) / 1e9 for r in rows]
    mx, my = sum(x) / len(x), sum(y) / len(y)
    denom = sum((v - mx) ** 2 for v in x)
    if not denom:
        return None
    return 1e6 * (sum((a - mx) * (b - my) for a, b in zip(x, y)) / denom - 1)


def analyze(path):
    frames = defaultdict(list)
    errors = []
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames or not REQUIRED.issubset(reader.fieldnames):
            raise ValueError("Not PicoFrameReader --clock-scan CSV (wrong column names)")
        for line_no, row in enumerate(reader, 2):
            try:
                item = {key: int(row[key]) for key in REQUIRED}
            except (TypeError, ValueError, KeyError):
                errors.append(f"noninteger data at line {line_no}")
                continue
            cam = item["cam"]
            if cam not in CAMERAS:
                errors.append(f"unknown camera at line {line_no}")
                continue
            if item["newest_seq"] <= item["seq"] or item["seq"] % 2 != 1:
                errors.append(f"unfinished ring sequence at line {line_no}")
                continue
            frames[cam].append(item)
    result = {"file": Path(path).name, "status": "DIAGNOSTIC_ONLY", "per_camera": {},
              "actual_exposure_time_verified": False}
    for cam in CAMERAS:
        rows = frames[cam]
        if len(rows) < 2:
            errors.append(f"C{cam}: insufficient samples")
            continue
        seq_diff = [b["seq"] - a["seq"] for a, b in zip(rows, rows[1:])]
        mono_diff = [b["mono_ns"] - a["mono_ns"] for a, b in zip(rows, rows[1:])]
        vendor_diff = [b["vendor_ns"] - a["vendor_ns"] for a, b in zip(rows, rows[1:])]
        ts84_diff = [b["ring_ts84_ns"] - a["ring_ts84_ns"] for a, b in zip(rows, rows[1:])]
        image_diff = [b["image_ts114_ns"] - a["image_ts114_ns"] for a, b in zip(rows, rows[1:])]
        if min(seq_diff) <= 0 or min(mono_diff) <= 0 or min(vendor_diff) <= 0 or min(ts84_diff) <= 0 or min(image_diff) <= 0:
            errors.append(f"C{cam}: nonmonotonic clock or sequence")
        contiguous = [delta / 1e6 for delta, ds in zip(vendor_diff, seq_diff) if ds == 2]
        if not contiguous:
            errors.append(f"C{cam}: no adjacent 40ms K0 frame steps")
        # A completed penultimate slot is deliberately one 25Hz frame behind
        # newest. Only the observed producer→probe age is measured directly.
        period = median(contiguous) if contiguous else None
        ages = [(row["boot_ns"] - row["ring_ts84_ns"]) / 1e6 for row in rows]
        selected_lags = [row["newest_seq"] - row["seq"] for row in rows]
        ring_steps = [((row["ring_index"] - row["slot"]) % 5) for row in rows]
        boot_mono = [(row["boot_ns"] - row["mono_ns"]) / 1e6 for row in rows]
        span = (rows[-1]["mono_ns"] - rows[0]["mono_ns"]) / 1e9
        result["per_camera"][str(cam)] = {
            "samples": len(rows), "span_s": round(span, 3),
            "samples_per_s": round((len(rows) - 1) / span, 2) if span > 0 else None,
            "vendor_frame_delta_ms_median": median(contiguous) if contiguous else None,
            "ts84_frame_delta_ms_median": median([d / 1e6 for d, ds in zip(ts84_diff, seq_diff) if ds == 2]) if contiguous else None,
            "producer_write_to_probe_ms_median": median(ages),
            "producer_write_to_probe_ms_p10": percentile(ages, .1),
            "producer_write_to_probe_ms_p90": percentile(ages, .9),
            "selected_exactly_one_frame_behind_fraction": sum(q == 2 for q in selected_lags) / len(rows),
            "ring_pointer_one_slot_ahead_fraction": sum(q == 1 for q in ring_steps) / len(rows),
            # Heuristic decomposition, not observed latest-frame age or exposure.
            "age_after_subtracting_one_period_ms": (median(ages) - period) if period else None,
            "boot_minus_mono_span_ms": max(boot_mono) - min(boot_mono),
            "ts84_minus_boot_ms_median": median((r["ring_ts84_ns"] - r["boot_ns"]) / 1e6 for r in rows),
            "ts84_minus_boot_ms_p10": percentile([(r["ring_ts84_ns"] - r["boot_ns"]) / 1e6 for r in rows], .1),
            "ts84_minus_boot_ms_p90": percentile([(r["ring_ts84_ns"] - r["boot_ns"]) / 1e6 for r in rows], .9),
            "image_ts114_equals_ts122_fraction": sum(r["image_ts114_ns"] == r["vendor_ns"] for r in rows) / len(rows),
            "ts122_minus_ts84_ms_median": median((r["vendor_ns"] - r["ring_ts84_ns"]) / 1e6 for r in rows),
            "ts122_minus_ts130_ms_median": median((r["vendor_ns"] - r["ring_ts130_ns"]) / 1e6 for r in rows),
            "vendor_minus_mono_ms_median": median((r["vendor_ns"] - r["mono_ns"]) / 1e6 for r in rows),
            "vendor_minus_boot_ms_median": median((r["vendor_ns"] - r["boot_ns"]) / 1e6 for r in rows),
            "vendor_minus_boot_ms_p10": percentile([(r["vendor_ns"] - r["boot_ns"]) / 1e6 for r in rows], .1),
            "vendor_minus_boot_ms_p90": percentile([(r["vendor_ns"] - r["boot_ns"]) / 1e6 for r in rows], .9),
            "boot_minus_mono_ms_median": median((r["boot_ns"] - r["mono_ns"]) / 1e6 for r in rows),
            "newest_minus_chosen_seq_median": median(r["newest_seq"] - r["seq"] for r in rows),
            "vendor_vs_mono_rate_difference_ppm": slope_ppm(rows),
        }
    if errors:
        result["status"] = "INVALID_OR_INCOMPLETE"
    result["errors"] = errors[:20]
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report = analyze(args.csv)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"PICO K0 CLOCK SCAN: {report['status']} ({report['file']})")
        for cam, row in report["per_camera"].items():
            print(f"  C{cam}: {row['samples']} frames / {row['span_s']:.1f}s, "
                  f"rate {row['samples_per_s']:.1f}/s, "
                  f"vendor step {row['vendor_frame_delta_ms_median']} ms")
            print(f"      producer write-lock -> probe: {row['producer_write_to_probe_ms_median']:.2f}ms "
                  f"(BOOTTIME-verified, not exposure age)")
            print(f"      one-frame-old selection: {row['selected_exactly_one_frame_behind_fraction']:.1%}; "
                  f"ring pointer one slot ahead: {row['ring_pointer_one_slot_ahead_fraction']:.1%}; "
                  f"age minus 40ms frame: {row['age_after_subtracting_one_period_ms']:.2f}ms")
            print(f"      producer-age p10..p90: {row['producer_write_to_probe_ms_p10']:.2f}.."
                  f"{row['producer_write_to_probe_ms_p90']:.2f}ms; "
                  f"BOOTTIME-MONO offset stability: {row['boot_minus_mono_span_ms']:.3f}ms")
            print(f"      slot+84 - BOOTTIME: {row['ts84_minus_boot_ms_median']:+.2f}ms, "
                  f"p10..p90 {row['ts84_minus_boot_ms_p10']:+.2f}.."
                  f"{row['ts84_minus_boot_ms_p90']:+.2f}ms")
            print(f"      image (+114) equals vendor (+122): {row['image_ts114_equals_ts122_fraction']:.1%}")
            print(f"      slot+122 - slot+84: {row['ts122_minus_ts84_ms_median']:+.3f}ms; "
                  f"slot+122 - slot+130: {row['ts122_minus_ts130_ms_median']:+.3f}ms")
            print(f"      vendor-BOOTTIME: median {row['vendor_minus_boot_ms_median']:+.2f}ms, "
                  f"p10..p90 {row['vendor_minus_boot_ms_p10']:+.2f}.."
                  f"{row['vendor_minus_boot_ms_p90']:+.2f}ms")
            print(f"      BOOTTIME-MONOTONIC: {row['boot_minus_mono_ms_median']:+.2f}ms; "
                  f"vendor/MONO rate diff: {row['vendor_vs_mono_rate_difference_ppm']:+.0f}ppm")
        for error in report["errors"]:
            print("  ISSUE: " + error)
        print("Physical exposure remains unknown; slot+84 is producer write-lock time, NOT sensor capture time.")
    return 1 if report["status"] != "DIAGNOSTIC_ONLY" else 0


if __name__ == "__main__":
    raise SystemExit(main())
