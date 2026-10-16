"""Analyze *variation* in Pico K0 slot+130 adjustment, offline and read-only.

Source-level equation:
  slot130 = slot122 - 52000 - A[camera] - ((B[camera] * E[frame]) ASR 1)
No claim is made about the physical meaning of A, B, or E.
"""
import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path
from statistics import median

CAMS = (0, 3, 4, 5)
REQUIRED = ("cam", "sample", "seq", "vendor_ns",
            "image_ts114_ns", "ring_ts130_ns")


def analyze(csv_path):
    by_cam = defaultdict(list)
    with Path(csv_path).open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames or not set(REQUIRED).issubset(reader.fieldnames):
            raise ValueError("Expected K0 --clock-scan CSV with +114/+122/+130")
        for line, raw in enumerate(reader, 2):
            try:
                v = {key: int(raw[key]) for key in REQUIRED}
            except (KeyError, ValueError, TypeError) as exc:
                raise ValueError(f"Bad timing CSV line {line}: {exc}") from exc
            if v["cam"] not in CAMS or v["seq"] <= 0 or not v["seq"] & 1:
                raise ValueError(f"Invalid camera or sequence at CSV line {line}")
            if v["vendor_ns"] != v["image_ts114_ns"]:
                raise ValueError(f"Mismatch at +114/+122 on line {line}")
            if v["ring_ts130_ns"] <= 0 or v["vendor_ns"] <= 0:
                raise ValueError(f"Missing raw or computed timestamp on line {line}")
            if by_cam[v["cam"]] and v["seq"] <= by_cam[v["cam"]][-1][0]:
                raise ValueError(f"C{v['cam']}: non-increasing K0 sequence")
            by_cam[v["cam"]].append((
                v["seq"],
                v["vendor_ns"] - v["ring_ts130_ns"],
            ))
    if set(by_cam) != set(CAMS):
        raise ValueError("All four K0 camera channels required")

    summary = {}
    for cam in CAMS:
        entries = by_cam[cam]
        if len(entries) < 30:
            raise ValueError(f"C{cam}: insufficient frames")
        deltas = [delta for seq, delta in entries]
        counts = Counter(deltas)
        transitions = sum(a != b for a, b in zip(deltas, deltas[1:]))
        summary[str(cam)] = {
            "samples": len(deltas),
            "raw_minus_adjusted_min_ns": min(deltas),
            "raw_minus_adjusted_median_ns": median(deltas),
            "raw_minus_adjusted_max_ns": max(deltas),
            "unique_adjustments": len(counts),
            "adjacent_adjustment_changes": transitions,
            "top_adjustments_ns": [
                {"delta_ns": delta, "frames": n}
                for delta, n in counts.most_common(6)
            ],
            "remaining_after_fixed_52000ns_median_ns": median(deltas) - 52000,
        }
    return {
        "status": "K0_SLOT130_DISTRIBUTION_OBSERVED_NO_EXPOSURE_PROOF",
        "total_frames": sum(d["samples"] for d in summary.values()),
        "per_camera": summary,
        "gates": {
            "slot130_exposure_center_verified": False,
            "camera_producer_provenance_verified": False,
            "live_lighthouse_correction_allowed": False,
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = analyze(args.csv)
    content = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        args.output.write_text(content, encoding="utf-8")
    print("status=" + result["status"] + " frames=" + str(result["total_frames"]))
    for cam in CAMS:
        row = result["per_camera"][str(cam)]
        print(
            f"C{cam} count={row['samples']}, "
            f"delta_ns_min/median/max="
            f"{row['raw_minus_adjusted_min_ns']}/"
            f"{row['raw_minus_adjusted_median_ns']}/"
            f"{row['raw_minus_adjusted_max_ns']}, "
            f"unique={row['unique_adjustments']}, "
            f"transitions={row['adjacent_adjustment_changes']}, "
            f"top={row['top_adjustments_ns'][:3]}"
        )
    print("Unverified: adjustment semantics, physical exposure and live corrections.")


if __name__ == "__main__":
    main()
