"""Read-only train/holdout split audit for provisional QuestLHSync P2 observations.

Inputs: PRIVATE correspondences.npz, solver_internal.npz. Outputs counts only,
not headset calibration, poses, raw pixels or base-station coordinates.
Requires numpy. It audits a split, NOT source identity or metric accuracy.
"""
import argparse
import json
from collections import Counter
from pathlib import Path
import numpy as np


def analyze(correspondences, solver):
    with np.load(correspondences, allow_pickle=False) as data, np.load(solver, allow_pickle=False) as fit:
        sessions, channel, times = data["session"], data["ch"], data["t"]
        train, test = fit["train"].astype(np.int64), fit["test"].astype(np.int64)
        n = len(sessions)
        if min(len(train), len(test)) == 0 or np.any(train < 0) or np.any(test < 0) or np.any(train >= n) or np.any(test >= n):
            raise ValueError("Invalid or empty train/test selection")
        if len(np.unique(train)) != len(train) or len(np.unique(test)) != len(test):
            raise ValueError("Duplicate observation indices")
        if np.intersect1d(train, test).size:
            raise ValueError("Exact train/test observation leakage")
        train_sessions, test_sessions = set(sessions[train]), set(sessions[test])
        train_blocks = set(zip(sessions[train], (times[train] // 10).astype(int)))
        test_blocks = set(zip(sessions[test], (times[test] // 10).astype(int)))
        training_counts = Counter(map(int, channel[train]))
        testing_counts = Counter(map(int, channel[test]))
        channel_counts = {str(ch): {"train": training_counts[ch], "test": testing_counts[ch]}
                          for ch in sorted(training_counts.keys() | testing_counts.keys())}
        session_counts = {str(name): {"train": int(np.sum(sessions[train] == name)),
                                      "test": int(np.sum(sessions[test] == name))}
                          for name in sorted(train_sessions | test_sessions)}
        return {"status": "SPLIT_AUDIT_ONLY", "train_count":len(train), "test_count":len(test),
                "train_test_exact_overlap":0,
                "shared_ten_second_blocks":len(train_blocks & test_blocks),
                "train_test_sessions_independent":not bool(train_sessions & test_sessions),
                "channel_counts":channel_counts, "session_counts":session_counts,
                "constraints":{"blobs_were_prefiltered_near_provisional_3d_seed_points":True,
                               "observations_are_not_blind_optical_matches":True,
                               "whole_session_heldout_geometry_validated":False,
                               "live_correction_allowed":False},
                "note":"Ten-second block isolation does not remove seed-selection bias. Validate without using a source to label itself, and hold out entire captures."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("correspondences_npz", type=Path)
    parser.add_argument("solver_internal_npz", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = json.dumps(analyze(args.correspondences_npz, args.solver_internal_npz),
                        indent=2, ensure_ascii=False)
    if args.output:
        args.output.write_text(report + "\n", encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()
