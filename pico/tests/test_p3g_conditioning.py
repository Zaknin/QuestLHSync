"""Native replay regression for replay-only solver conditioning diagnostics."""
import os
from pathlib import Path
import re
import subprocess
import unittest

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
REPLAY = Path(os.environ.get("QLHS_REPLAY_EXE", ROOT / "out" / "qlhs_replay.exe"))


class NativeConditioningDiagnosticsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not REPLAY.is_file():
            raise RuntimeError(f"build replay first: {REPLAY}")

    def run_self_test(self):
        return subprocess.run(
            [str(REPLAY), "--conditioning-self-test"],
            text=True,
            capture_output=True,
            check=False,
        )

    def test_native_synthetic_controls_and_eigen_reference(self):
        result = self.run_self_test()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("PICO_COND_SELFTEST status=PASS", result.stdout)
        positive = re.search(r"CONTROL name=positive .*?lambda_min=([0-9.eE+-]+).*?cond=(true|false)", result.stdout)
        negative = re.search(r"CONTROL name=negative .*?lambda_min=([0-9.eE+-]+).*?cond=(true|false)", result.stdout)
        self.assertIsNotNone(positive, result.stdout)
        self.assertIsNotNone(negative, result.stdout)
        self.assertGreaterEqual(float(positive.group(1)), 1.0, result.stdout)
        self.assertEqual(positive.group(2), "true", result.stdout)
        self.assertLess(float(negative.group(1)), 1.0, result.stdout)
        self.assertEqual(negative.group(2), "false", result.stdout)
        self.assertIn("EIGEN_REFERENCE status=PASS", result.stdout)
        self.assertIn("STEP_CAPTURE status=PASS samples=1", result.stdout)
        reference = re.search(r"EIGEN_REFERENCE status=PASS eigenvalues=([^ ]+) weakest=([^ ]+)", result.stdout)
        self.assertIsNotNone(reference, result.stdout)
        q = 0.5 * np.array([[1, 1, 1, 1], [1, -1, 1, -1],
                            [1, 1, -1, -1], [1, -1, -1, 1]], dtype=float)
        expected_matrix = q @ np.diag([0.5, 2.0, 5.0, 9.0]) @ q.T
        values, vectors = np.linalg.eigh(expected_matrix)
        actual_values = np.fromstring(reference.group(1), sep=",")
        actual_weakest = np.fromstring(reference.group(2), sep=",")
        np.testing.assert_allclose(actual_values, values, rtol=1e-9, atol=1e-10)
        np.testing.assert_allclose(np.abs(actual_weakest), np.abs(vectors[:, 0]), rtol=1e-8, atol=1e-9)
        positive_mass = re.search(r"CONTROL name=positive .*?eff_weight_mass=([0-9.eE+-]+)", result.stdout)
        negative_mass = re.search(r"CONTROL name=negative .*?eff_weight_mass=([0-9.eE+-]+)", result.stdout)
        self.assertIsNotNone(positive_mass, result.stdout)
        self.assertIsNotNone(negative_mass, result.stdout)
        self.assertGreater(float(positive_mass.group(1)), float(negative_mass.group(1)), result.stdout)


if __name__ == "__main__":
    unittest.main()
