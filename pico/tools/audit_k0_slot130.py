"""Offline comparison of the third K0 frame timestamp, slot+130.

The PVR native onFrameAvailable function calculates pvr_frame_item_t+0x28
which becomes K0 slot+130. This tool compares its *recorded* values to
vendor slot+122 and producer BOOTTIME slot+84; it does not guess that +130
is a true exposure time or enable live clock conversion.
"""
import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path

from pico.tools.audit_qtimer_bridge import CAMERAS, parse_pvr_snapshot
from pico.tools.audit_shadow_k0_time import interpolate, shadow, summary_ms

NEEDED = ("cam", "seq", "ring_ts84_ns", "image_ts114_ns",
          "vendor_ns", "ring_ts130_ns", "boot_ns")


def inspect_slot130(before_path, csv_path, after_path):
    baseline = shadow(before_path, csv_path, after_path)
    if baseline["status"] != "QTIMER_SHADOW_PLAUSIBLE_UNVERIFIED":
        raise ValueError("Paired clock baseline rejected/incomplete; no slot130 interpretation")

    first = parse_pvr_snapshot(before_path)
    last = parse_pvr_snapshot(after_path)
    by_cam = defaultdict(list)
    with Path(csv_path).open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames or not set(NEEDED).issubset(reader.fieldnames):
            raise ValueError("K0 scan must have slot130 and paired image/clock columns")
        for line, record in enumerate(reader, 2):
            try:
                v = {key: int(record[key]) for key in NEEDED}
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(f"Bad CSV at line {line}: {exc}") from exc
            if v["cam"] not in CAMERAS or v["seq"] % 2 != 1 or v["seq"] <= 0:
                raise ValueError(f"Unexpected camera or incomplete sequence at {line}")
            if v["image_ts114_ns"] != v["vendor_ns"]:
                raise ValueError(f"114 and 122 differ at line {line}")
            if not first["boottime_ns"] <= v["boot_ns"] <= last["boottime_ns"]:
                raise ValueError(f"K0 sample not bracketed by PVR clocks at {line}")
            by_cam[v["cam"]].append(v)

    per_camera = {}
    for cam in CAMERAS:
        records = by_cam[cam]
        if len(records) < 30 or any(
            b["seq"] <= a["seq"] for a, b in zip(records, records[1:])
        ):
            raise ValueError(f"K0 C{cam}: sequence regression or insufficient frames")

        delta_vendor = []
        delta_producer = []
        lag_if_qtimer = []
        lag_if_boot = []
        nonzero = 0
        identical = 0
        q_near = 0
        boot_near = 0
        regressive = 0
        prev = None
        for rec in records:
            stamp = rec["ring_ts130_ns"]
            if stamp <= 0:
                continue
            nonzero += 1
            identical += int(stamp == rec["vendor_ns"])
            if prev is not None and stamp <= prev:
                regressive += 1
            prev = stamp

            dv = stamp - rec["vendor_ns"]
            db = stamp - rec["ring_ts84_ns"]
            delta_vendor.append(dv)
            delta_producer.append(db)
            q_near += int(abs(dv) <= 1_000_000_000)
            boot_near += int(abs(db) <= 1_000_000_000)

            qboot0 = first["qtimer_ns"] - first["boottime_ns"]
            qboot1 = last["qtimer_ns"] - last["boottime_ns"]
            qboot = interpolate(qboot0, qboot1, rec["boot_ns"],
                                first["boottime_ns"], last["boottime_ns"])
            # BOTH are ALTERNATIVE hypothetical interpretations, not exposures.
            lag_if_qtimer.append(rec["ring_ts84_ns"] + qboot - stamp)
            lag_if_boot.append(rec["ring_ts84_ns"] - stamp)

        per_camera[str(cam)] = {
            "frames": len(records),
            "slot130_nonzero": nonzero,
            "slot130_equal_vendor": identical,
            "slot130_regressive_or_duplicate_nonzero": regressive,
            "slot130_within_1s_of_vendor_qtimer_epoch": q_near,
            "slot130_within_1s_of_producer_boottime_epoch": boot_near,
            "slot130_minus_vendor_if_ns": summary_ms(delta_vendor) if nonzero else None,
            "slot130_minus_producer_if_ns": summary_ms(delta_producer) if nonzero else None,
            "write_lag_if_slot130_qtimer_ns": summary_ms(lag_if_qtimer) if nonzero else None,
            "write_lag_if_slot130_boottime_ns": summary_ms(lag_if_boot) if nonzero else None,
        }
    enough = all(per_camera[str(cam)]["slot130_nonzero"] >= 30 for cam in CAMERAS)
    return {
        "status": ("SLOT130_OBSERVED_SOURCE_UNVERIFIED" if enough
                   else "SLOT130_MISSING_OR_SPARSE"),
        "input_frames": sum(len(by_cam[c]) for c in CAMERAS),
        "per_camera": per_camera,
        "interpretation": (
            "All deltas treat slot+130 as ns FOR DIAGNOSTIC COMPARISON ONLY. "
            "Per-frame source and exposure/event meaning are unverified. "
            "A small difference from vendor favors the QTIMER-epoch hypothesis; "
            "a small difference from ring_ts84 favors BOOTTIME epoch, but "
            "neither establishes correctness, origin, or exposure center."
        ),
        "gates": {
            "slot130_source_verified": False,
            "slot130_physical_exposure_verified": False,
            "live_lighthouse_correction_allowed": False,
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before", type=Path, required=True)
    parser.add_argument("--csv", type=Path, required=True)
    parser.add_argument("--after", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = inspect_slot130(args.before, args.csv, args.after)
    output = json.dumps(result, indent=2) + "\n"
    if args.output:
        args.output.write_text(output, encoding="utf-8")
    print(output, end="")


if __name__ == "__main__":
    main()
