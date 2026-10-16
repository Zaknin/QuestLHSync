"""Synthetic, fail-closed tests of frame-level K0 +130 correction variation."""
import csv
import tempfile
import unittest
from pathlib import Path

from pico.tools.audit_k0_slot130_variation import analyze

FIELDS = ["cam", "sample", "seq", "vendor_ns", "image_ts114_ns", "ring_ts130_ns"]


class Slot130VariationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.csv = Path(self.tmp.name) / "k0.csv"

    def make_csv(self, delta=None, bad114=False, missing_camera=False):
        with self.csv.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDS)
            writer.writeheader()
            for i in range(40):
                for cam in (0, 3, 4, 5):
                    if missing_camera and cam == 5:
                        continue
                    vendor = 20_000_000_000 + i * 40_000_000
                    offset = (226000 if delta is None else delta(i, cam))
                    writer.writerow({
                        "cam": cam, "sample": i, "seq": 2 * i + 1,
                        "vendor_ns": vendor, "image_ts114_ns": vendor + int(bad114),
                        "ring_ts130_ns": vendor - offset,
                    })

    def test_constant_correction_does_not_claim_exposure(self):
        self.make_csv()
        result = analyze(self.csv)
        self.assertEqual(result["total_frames"], 160)
        self.assertEqual(result["per_camera"]["0"]["unique_adjustments"], 1)
        self.assertEqual(result["per_camera"]["0"]["raw_minus_adjusted_median_ns"], 226000)
        self.assertEqual(result["per_camera"]["0"]["remaining_after_fixed_52000ns_median_ns"], 174000)
        self.assertFalse(result["gates"]["slot130_exposure_center_verified"])
        self.assertFalse(result["gates"]["live_lighthouse_correction_allowed"])

    def test_per_frame_changes_are_counted(self):
        self.make_csv(delta=lambda i, cam: 226000 + (i % 2) * 1000)
        result = analyze(self.csv)
        self.assertEqual(result["per_camera"]["3"]["unique_adjustments"], 2)
        self.assertEqual(result["per_camera"]["3"]["adjacent_adjustment_changes"], 39)

    def test_bad_114_blocks(self):
        self.make_csv(bad114=True)
        with self.assertRaisesRegex(ValueError, "Mismatch"):
            analyze(self.csv)

    def test_missing_camera_blocks(self):
        self.make_csv(missing_camera=True)
        with self.assertRaisesRegex(ValueError, "four"):
            analyze(self.csv)

    def test_missing_column_blocks(self):
        self.csv.write_text("cam,seq\n0,1\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Expected"):
            analyze(self.csv)


if __name__ == "__main__":
    unittest.main()
