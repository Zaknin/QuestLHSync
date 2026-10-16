"""Summarize optional PicoFrameReader PICO_FRAME_CLOCK_DIAG=1 stderr logs.

The BOOTTIME write-lock stamp is not the physical camera exposure time.
Pure Python 3, standard library only; no camera calibration data needed.
"""
import argparse
import json
import re
from collections import defaultdict
from pathlib import Path
from statistics import median

PATTERN = re.compile(
    r"PicoFrameClock\s+cam=(?P<cam>\d+)\s+seq=(?P<seq>\d+)\s+"
    r"producer_write_boot_ns=(?P<write>\d+)\s+"
    r"java_copy_mono_ns=(?P<mono>\d+)\s+"
    r"java_copy_boot_ns=(?P<boot>\d+)\s+"
    r"producer_to_copy_ms=(?P<age>[0-9.]+)"
)
CAMERAS = (0, 3, 4, 5)


def analyze(path):
    groups = defaultdict(list)
    for line in Path(path).read_text(encoding="utf-8-sig", errors="replace").splitlines():
        match = PATTERN.search(line)
        if match:
            d = {k: int(v) if k != "age" else float(v) for k, v in match.groupdict().items()}
            groups[d["cam"]].append(d)
    issues = []
    out = {"file": Path(path).name, "status": "PASS", "per_camera": {},
           "validated_exposure_time": False}
    if set(groups) != set(CAMERAS):
        issues.append(f"camera coverage: found {sorted(groups)}, expected {list(CAMERAS)}")
    offsets = []
    for cam in CAMERAS:
        rows = groups.get(cam, [])
        if len(rows) < 3:
            issues.append(f"C{cam}: fewer than 3 clock samples")
            continue
        ages = []
        for row in rows:
            expected = (row["boot"] - row["write"]) / 1e6
            if expected < 0 or abs(expected - row["age"]) > .001:
                issues.append(f"C{cam} seq={row['seq']}: invalid producer age")
            ages.append(expected)
            offsets.append((row["boot"] - row["mono"]) / 1e6)
        for left, right in zip(rows, rows[1:]):
            if right["seq"] <= left["seq"]:
                issues.append(f"C{cam}: nonmonotonic frame sequences")
            elif (right["seq"] - left["seq"]) % 2:
                issues.append(f"C{cam}: unexpected odd sequence gap")
        out["per_camera"][str(cam)] = {
            "samples": len(rows), "seq_first": rows[0]["seq"], "seq_last": rows[-1]["seq"],
            "producer_to_copy_ms_median": round(median(ages), 4),
            "producer_to_copy_ms_min": round(min(ages), 4),
            "producer_to_copy_ms_max": round(max(ages), 4),
        }
    if offsets:
        out["boot_minus_mono_ms_median"] = round(median(offsets), 4)
        out["boot_minus_mono_ms_span"] = round(max(offsets) - min(offsets), 5)
        if max(offsets) - min(offsets) > 1.0:
            issues.append("BOOTTIME-MONOTONIC offset shifted >1ms during scan")
    out["samples_total"] = sum(len(x) for x in groups.values())
    out["issues"] = issues
    if issues:
        out["status"] = "REVIEW"
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("log", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    data = analyze(args.log)
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print(f"PICO FRAME CLOCK: {data['status']} ({data['samples_total']} samples)")
        for cam, row in data["per_camera"].items():
            print(f"  C{cam}: median {row['producer_to_copy_ms_median']:.3f}ms "
                  f"[{row['producer_to_copy_ms_min']:.3f}, "
                  f"{row['producer_to_copy_ms_max']:.3f}], {row['samples']} samples")
        if "boot_minus_mono_ms_median" in data:
            print("  BOOTTIME-MONOTONIC: %.3fms (span %.5fms)" %
                  (data["boot_minus_mono_ms_median"], data["boot_minus_mono_ms_span"]))
        for issue in data["issues"]:
            print("  ISSUE: " + issue)
        print("Camera exposure time not measured by this diagnostic.")
    return 0 if data["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
