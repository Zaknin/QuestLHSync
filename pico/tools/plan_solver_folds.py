"""Plan PRIVATE P2 validation folds; no fitting or calibration is performed.

The inputs are provisional, seed-selected correspondences. Even a disjoint
session split does NOT turn these into blind optical source associations.
Requires numpy. Never prints calibration vectors, poses or timestamps.
"""
import argparse
import json
import os
from pathlib import Path

import numpy as np

STATIONS = (1, 7, 10, 13)


def plan(source, minimum=20):
    if minimum < 1:
        raise ValueError("minimum must be positive")
    with np.load(source, allow_pickle=False) as src:
        sessions = src["session"]
        channels = src["ch"]
        times = src["t"]
    if any(x.ndim != 1 for x in (sessions, channels, times)):
        raise ValueError("session, ch and t must be 1-D")
    n = len(sessions)
    if n == 0 or len(channels) != n or len(times) != n:
        raise ValueError("empty or mismatched observation arrays")
    if sessions.dtype.kind not in ("U", "S"):
        raise ValueError("session must be a non-object string array")
    if channels.dtype.kind not in ("i", "u") or times.dtype.kind not in ("f", "i", "u"):
        raise ValueError("channel/time types invalid")
    if not np.isfinite(times).all() or np.any(times < 0):
        raise ValueError("time must be finite and nonnegative")
    if not np.isin(channels, STATIONS).all():
        raise ValueError("unexpected station channel")
    unique_sessions = np.unique(sessions)
    if len(unique_sessions) < 2 or any(not s for s in unique_sessions):
        raise ValueError("at least two named sessions are needed")

    folds = {}
    report = []
    for index, name in enumerate(unique_sessions):
        test = np.flatnonzero(sessions == name).astype(np.int64)
        train = np.flatnonzero(sessions != name).astype(np.int64)
        key = f"session_{index}"
        folds[f"{key}_train"], folds[f"{key}_test"] = train, test
        train_counts = {str(ch): int(np.count_nonzero(channels[train] == ch)) for ch in STATIONS}
        test_counts = {str(ch): int(np.count_nonzero(channels[test] == ch)) for ch in STATIONS}
        report.append({"fold": key, "holdout_session": str(name),
                       "train": len(train), "test": len(test),
                       "train_per_channel": train_counts, "test_per_channel": test_counts,
                       "count_coverage_all_channels": all(
                           train_counts[str(ch)] >= minimum and test_counts[str(ch)] >= minimum
                           for ch in STATIONS),
                       "independent_session_selection": True})
    for ch in STATIONS:
        test = np.flatnonzero(channels == ch).astype(np.int64)
        train = np.flatnonzero(channels != ch).astype(np.int64)
        key = f"station_{ch}"
        folds[f"{key}_train"], folds[f"{key}_test"] = train, test
        report.append({"fold": key, "holdout_station": ch, "train": len(train), "test": len(test),
                       "test_sessions": int(len(np.unique(sessions[test]))),
                       "test_count_ge_minimum": len(test) >= minimum,
                       "independent_session_selection": not bool(
                           np.intersect1d(sessions[train], sessions[test]).size)})

    for fold in report:
        tr, te = folds[fold["fold"] + "_train"], folds[fold["fold"] + "_test"]
        if len(tr) + len(te) != n or np.intersect1d(tr, te).size:
            raise AssertionError("fold partition is not disjoint and exhaustive")
    return ({"status": "DIAGNOSTIC_ONLY", "total_correspondences": n,
             "session_count": len(unique_sessions), "minimum_count_threshold": minimum,
             "folds": report,
             "gates": {"blind_source_associations_verified": False,
                       "session_separated_geometric_fit_verified": False,
                       "station_withheld_geometric_fit_verified": False,
                       "physical_exposure_clock_verified": False,
                       "live_lighthouse_correction_allowed": False},
             "warning": "Correspondences were selected near fitted seed landmarks. "
                        "Folds enforce selection separation ONLY: refit on training captures, "
                        "re-detect sources blindly in heldout raw captures and test negative controls."}, folds)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("correspondences_npz", type=Path)
    p.add_argument("--min-count", type=int, default=20)
    p.add_argument("--report", type=Path, help="Write a PRIVATE count-only JSON report")
    p.add_argument("--folds", type=Path, help="Write PRIVATE index-only fold arrays as NPZ")
    args = p.parse_args()
    report, folds = plan(args.correspondences_npz, args.min_count)
    payload = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        temp = args.report.with_name(args.report.name + ".part")
        temp.write_text(payload, encoding="utf-8")
        os.replace(temp, args.report)
    if args.folds:
        args.folds.parent.mkdir(parents=True, exist_ok=True)
        temp = args.folds.with_name(args.folds.name + ".part")
        with temp.open("wb") as handle:
            np.savez_compressed(handle, **folds)
        os.replace(temp, args.folds)
    print(payload, end="")


if __name__ == "__main__":
    main()
