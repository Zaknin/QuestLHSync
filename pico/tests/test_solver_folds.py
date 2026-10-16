"""Synthetic tests: separation rules, coverage, and hard safety gates."""
import tempfile
import unittest
from pathlib import Path

import numpy as np
from pico.tools.plan_solver_folds import plan


class SolverFoldTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "input.npz"

    def fixture(self, session=None, channel=None, time=None):
        if session is None:
            session = ["A"] * 80 + ["B"] * 80
        if channel is None:
            channel = [1] * 20 + [7] * 20 + [10] * 20 + [13] * 20
            channel *= 2
        if time is None:
            time = np.arange(len(session), dtype=float)
        np.savez(self.path, session=np.asarray(session), ch=np.asarray(channel), t=np.asarray(time))
        return self.path

    def test_exhaustive_disjoint_partitions(self):
        report, folds = plan(self.fixture(), minimum=20)
        self.assertEqual(len(report["folds"]), 6)
        self.assertTrue(report["folds"][0]["count_coverage_all_channels"])
        for fold in report["folds"]:
            name = fold["fold"]
            train, test = folds[name + "_train"], folds[name + "_test"]
            self.assertEqual(len(np.intersect1d(train, test)), 0)
            self.assertEqual(len(train) + len(test), 160)
        self.assertFalse(report["gates"]["live_lighthouse_correction_allowed"])
        self.assertFalse(report["gates"]["blind_source_associations_verified"])

    def test_one_session_cannot_be_independently_heldout(self):
        with self.assertRaisesRegex(ValueError, "at least two"):
            plan(self.fixture(session=["A"] * 160))

    def test_missing_station_not_fake_coverage(self):
        channels = [1] * 40 + [10] * 40 + [1] * 40 + [10] * 40
        report, _ = plan(self.fixture(channel=channels))
        self.assertFalse(report["folds"][0]["count_coverage_all_channels"])
        self.assertEqual(report["folds"][-1]["holdout_station"], 13)
        self.assertEqual(report["folds"][-1]["test"], 0)

    def test_unknown_channel_rejected(self):
        with self.assertRaisesRegex(ValueError, "unexpected station"):
            plan(self.fixture(channel=[99] * 160))

    def test_object_array_without_pickle_rejected(self):
        np.savez(self.path, session=np.array(["A", "B"], dtype=object),
                 ch=np.array([1, 7]), t=np.array([0., 1.]))
        with self.assertRaises(ValueError):
            plan(self.path)

    def test_negative_or_nan_time_rejected(self):
        t = np.arange(160, dtype=float)
        t[25] = float("nan")
        with self.assertRaisesRegex(ValueError, "time must be finite"):
            plan(self.fixture(time=t))


if __name__ == "__main__":
    unittest.main()
