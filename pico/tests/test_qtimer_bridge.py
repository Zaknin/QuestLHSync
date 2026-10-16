"""Synthetic regression checks for QTIMER-to-K0 read-only audit."""
import csv
import tempfile
import unittest
from pathlib import Path

from pico.tools.audit_qtimer_bridge import analyze, parse_pvr_snapshot

FIELDS = ("cam", "seq", "ring_ts84_ns", "image_ts114_ns", "vendor_ns", "boot_ns")


class QTimerBridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.before = root / "before.txt"
        self.after = root / "after.txt"
        self.csv = root / "k0.csv"
        self.base = 20_000_000_000_000
        self.qoffset = 4_746_402_784

    def snapshots(self, drift=0, boot_epoch_shift=0):
        early = self.base + boot_epoch_shift
        late = self.base + 12_000_000_000 + boot_epoch_shift
        self.before.write_text(
            f"PvrTrackingService\ntime boottime {early}, "
            f"monotime {early - 42}, qtimer {early + self.qoffset}\n",
            encoding="utf-8",
        )
        self.after.write_text(
            f"PvrTrackingService\ntime boottime {late}, "
            f"monotime {late - 42}, qtimer {late + self.qoffset + drift}\n",
            encoding="utf-8",
        )

    def frames(self, corrupt114=False, missing_camera=False):
        with self.csv.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=FIELDS)
            writer.writeheader()
            for frame in range(50):
                for cam in (0, 3, 4, 5):
                    if missing_camera and cam == 5:
                        continue
                    producer = self.base + 4_000_000_000 + frame * 40_000_000 + cam * 1000
                    vendor = producer + 4_736_000_000
                    writer.writerow({
                        "cam": cam, "seq": 2 * frame + 1,
                        "ring_ts84_ns": producer,
                        "image_ts114_ns": vendor + (1 if corrupt114 else 0),
                        "vendor_ns": vendor,
                        "boot_ns": producer + 40_000_000,
                    })

    def test_candidate_is_never_verified(self):
        self.snapshots()
        self.frames()
        result = analyze(self.before, self.csv, self.after)
        self.assertEqual(result["status"], "QTIMER_CANDIDATE_REQUIRES_SOURCE_PROOF")
        self.assertTrue(result["pvr_boot_brackets_k0_write_epoch"])
        for row in result["per_camera"].values():
            self.assertAlmostEqual(row["qtimer_model_apparent_producer_lag_ms"],
                                   10.402784, places=4)
        self.assertFalse(result["flags"]["qtimer_timestamp_source_verified"])
        self.assertFalse(result["flags"]["live_lighthouse_correction_allowed"])

    def test_wrong_boot_epoch_is_rejected(self):
        self.snapshots(boot_epoch_shift=100_000_000_000)
        self.frames()
        result = analyze(self.before, self.csv, self.after)
        self.assertEqual(result["status"], "QTIMER_HYPOTHESIS_NOT_ESTABLISHED")
        self.assertFalse(result["pvr_boot_brackets_k0_write_epoch"])

    def test_large_qtimer_drift_rejected(self):
        self.snapshots(drift=5_000_000)
        self.frames()
        result = analyze(self.before, self.csv, self.after)
        self.assertEqual(result["status"], "QTIMER_HYPOTHESIS_NOT_ESTABLISHED")
        self.assertEqual(result["qtimer_offset_drift_ms"], 5.0)

    def test_missing_pvr_time_line(self):
        self.before.write_text("no PVR time reported", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "expected one PVR clock line"):
            parse_pvr_snapshot(self.before)

    def test_mismatched_114_rejected(self):
        self.snapshots()
        self.frames(corrupt114=True)
        with self.assertRaisesRegex(ValueError, "114/\\+122 disagree"):
            analyze(self.before, self.csv, self.after)

    def test_missing_camera_rejected(self):
        self.snapshots()
        self.frames(missing_camera=True)
        with self.assertRaisesRegex(ValueError, "All four K0"):
            analyze(self.before, self.csv, self.after)


if __name__ == "__main__":
    unittest.main()
