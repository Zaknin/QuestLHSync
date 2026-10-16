"""Synthetic regression tests for private P2 train/holdout audit (numpy)."""
import tempfile
import unittest
from pathlib import Path
import numpy as np
from pico.tools.audit_solver_holdout import analyze


class HoldoutAuditTests(unittest.TestCase):
    def fixture(self, train, test):
        folder = Path(tempfile.mkdtemp(prefix="pico_split_"))
        self.addCleanup(folder.rmdir)
        self.addCleanup(lambda: [p.unlink() for p in folder.iterdir()])
        observations = folder / "correspondences.npz"
        solver = folder / "solver_internal.npz"
        np.savez(observations, session=np.array(["A", "A", "B", "B"]),
                 ch=np.array([1, 1, 7, 7]), t=np.array([10., 12., 30., 45.]))
        np.savez(solver, train=np.array(train), test=np.array(test))
        return observations, solver

    def test_blocked_same_session_validation(self):
        result = analyze(*self.fixture([0, 2], [1, 3]))
        self.assertFalse(result["train_test_sessions_independent"])
        self.assertEqual(result["shared_ten_second_blocks"], 1)
        self.assertFalse(result["constraints"]["live_correction_allowed"])

    def test_cross_session_does_not_prove_geometry(self):
        result = analyze(*self.fixture([0, 1], [2, 3]))
        self.assertTrue(result["train_test_sessions_independent"])
        self.assertFalse(result["constraints"]["whole_session_heldout_geometry_validated"])

    def test_duplicate_index_rejected(self):
        with self.assertRaisesRegex(ValueError, "Duplicate observation"):
            analyze(*self.fixture([0, 0, 2], [1, 3]))

    def test_overlap_rejected(self):
        with self.assertRaisesRegex(ValueError, "Exact train/test"):
            analyze(*self.fixture([0, 2], [2, 3]))


if __name__ == "__main__":
    unittest.main()
