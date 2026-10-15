"""Check a focused Pico QuestLHSync session and its power-toggle CSV.

Only Python standard library; no factory calibration read or modification.
"""
import argparse
import csv
import math
from pathlib import Path
from collections import Counter


def representative_pose(rows):
    return rows[len(rows) // 2][1] if rows else None


def pose_delta(a, b):
    xyz = (3, 7, 11)
    translation = math.sqrt(sum((a[i] - b[i]) ** 2 for i in xyz))
    trace = sum(a[i] * b[i] for i in (0, 1, 2, 4, 5, 6, 8, 9, 10))
    angle = math.degrees(math.acos(max(-1, min(1, (trace - 1) / 2))))
    return translation, angle


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("recording", type=Path)
    ap.add_argument("markers", type=Path)
    args = ap.parse_args()
    with args.markers.open(encoding="utf-8-sig", newline="") as file:
        markers = list(csv.DictReader(file))
    runs = {}
    for row in markers:
        view = row.get("View", "")
        if not view:
            continue
        run = runs.setdefault(view, {"channel": int(row["Channel"]), "events": {}})
        action = row["Action"]
        if action in run["events"]:
            raise ValueError(f"duplicate action {action} for {view}")
        run["events"][action] = int(row["QpcNs"]) / 1e9
    if not runs:
        raise ValueError("no targeted viewpoints in marker CSV")
    ordered = ["BASELINE_READY", "OFF", "OFF_READY", "ON", "ON_READY", "PASS_DONE"]
    windows = []
    for view, run in runs.items():
        e = run["events"]
        missing = set(ordered) - set(e)
        if missing:
            raise ValueError(f"missing {sorted(missing)} in {view}")
        if any(e[b] <= e[a] for a, b in zip(ordered, ordered[1:])):
            raise ValueError(f"nonmonotonic actions in {view}")
        windows.extend([
            (view, "BASELINE", e["BASELINE_READY"] + 2, e["OFF"] - 1),
            (view, "OFF", e["OFF_READY"] + 2, e["ON"] - 1),
            (view, "RESTORED", max(e["ON_READY"] + 2, e["PASS_DONE"] - 12), e["PASS_DONE"] - 1),
        ])
    phases = ("BASELINE", "OFF", "RESTORED")
    poses = {view: {phase: [] for phase in phases} for view in runs}
    counts = {view: {phase: Counter() for phase in phases} for view in runs}
    with args.recording.open(encoding="utf-8", errors="replace") as file:
        for line in file:
            row = line.split()
            if len(row) < 3:
                continue
            try:
                t = int(row[0]) / 1e9
            except ValueError:
                continue
            relevant = [(view, phase) for view, phase, begin, end in windows if begin < t < end]
            if not relevant:
                continue
            if row[1:3] == ["P", "0"] and len(row) >= 15:
                pose = tuple(map(float, row[3:15]))
                for view, phase in relevant:
                    poses[view][phase].append((t, pose))
            elif row[1:3] == ["U", "F"] and len(row) >= 8:
                camera = int(row[3])
                blobs = int(row[7])
                for view, phase in relevant:
                    counts[view][phase][f"C{camera}"] += 1
                    counts[view][phase]["spots"] += blobs
    passed = True
    for view, run in runs.items():
        print(f"\nChannel {run['channel']}: {view}")
        center = {phase: representative_pose(poses[view][phase]) for phase in phases}
        for phase in phases:
            data = counts[view][phase]
            frames = sum(data[f"C{c}"] for c in (0, 3, 4, 5))
            print(f"  {phase}: HMD={len(poses[view][phase])} frames={frames} spots={data['spots']}")
            if len(poses[view][phase]) < 100 or any(data[f"C{c}"] < 100 for c in (0, 3, 4, 5)):
                print("    INCOMPLETE: insufficient tracked HMD poses or camera frames")
                passed = False
        if all(center.values()):
            for phase in ("OFF", "RESTORED"):
                meters, degrees = pose_delta(center["BASELINE"], center[phase])
                print(f"  BASELINE -> {phase}: {meters * 100:.1f} cm, {degrees:.1f} deg")
                if meters > 0.2 or degrees > 15:
                    print("    REVIEW: head pose did not return close to baseline")
                    passed = False
    print("\n" + ("CAPTURE QUALITY PASS (not proof of optical identity)" if passed
                   else "CAPTURE REVIEW NEEDED (check the details)"))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
