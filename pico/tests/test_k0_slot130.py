"""Synthetic regression tests of the K0 slot+130 offline-only interpretation."""
import csv
import tempfile
import unittest
from pathlib import Path

from pico.tools.audit_k0_slot130 import inspect_slot130

COLUMNS = (
    "sample", "cam", "seq", "newest_seq", "slot", "ring_index",
    "ring_ts84_ns", "image_ts114_ns", "vendor_ns", "ring_ts130_ns",
    "mono_ns", "boot_ns", "boot_minus_mono_ns"
)


class Slot130Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.before, self.csv, self.after = (
            root / "before.txt", root / "k0.csv", root / "after.txt")
        self.epoch = 30_000_000_000_000
        self.qoffset = 4_746_503_000
        self.bmono = 18_618_216_260_000

    def snapshots(self, drift=0):
        for path, boot, d in [
            (self.before, self.epoch, 0),
            (self.after, self.epoch + 10_000_000_000, drift),
        ]:
            path.write_text(
                f"time boottime {boot}, monotime {boot-self.bmono}, "
                f"qtimer {boot+self.qoffset+d}\n", encoding="utf-8",
            )

    def frames(self, mode="qtimer", corrupt114=False):
        with self.csv.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=COLUMNS)
            writer.writeheader()
            for sample in range(50):
                for cam in (0, 3, 4, 5):
                    producer = self.epoch + 2_000_000_000 + sample * 40_000_000
                    vendor = producer + self.qoffset - 10_000_000
                    if mode == "qtimer":
                        stamp130 = vendor - 5_000_000
                    elif mode == "boottime":
                        stamp130 = producer - 3_000_000
                    elif mode == "missing":
                        stamp130 = 0
                    else:
                        raise ValueError("bad fixture mode")
                    writer.writerow({
                        "sample": sample, "cam": cam, "seq": sample * 2 + 1,
                        "newest_seq": sample * 2 + 3, "slot": 0, "ring_index": 0,
                        "ring_ts84_ns": producer, "vendor_ns": vendor,
                        "image_ts114_ns": vendor + int(corrupt114),
                        "ring_ts130_ns": stamp130,
                        "mono_ns": producer - self.bmono + 45_000_000,
                        "boot_ns": producer + 45_000_000,
                        "boot_minus_mono_ns": self.bmono,
                    })

    def test_qtimer_like_slot130(self):
        self.snapshots()
        self.frames("qtimer")
        result = inspect_slot130(self.before, self.csv, self.after)
        self.assertEqual(result["status"], "SLOT130_OBSERVED_SOURCE_UNVERIFIED")
        self.assertEqual(result["input_frames"], 200)
        row = result["per_camera"]["0"]
        self.assertEqual(row["slot130_within_1s_of_vendor_qtimer_epoch"], 50)
        self.assertEqual(row["slot130_within_1s_of_producer_boottime_epoch"], 0)
        self.assertEqual(row["slot130_minus_vendor_if_ns"]["median_ms"], -5.0)
        self.assertEqual(row["write_lag_if_slot130_qtimer_ns"]["median_ms"], 15.0)
        self.assertFalse(result["gates"]["live_lighthouse_correction_allowed"])

    def test_boottime_like_slot130(self):
        self.snapshots()
        self.frames("boottime")
        result = inspect_slot130(self.before, self.csv, self.after)
        row = result["per_camera"]["5"]
        self.assertEqual(row["slot130_within_1s_of_vendor_qtimer_epoch"], 0)
        self.assertEqual(row["slot130_within_1s_of_producer_boottime_epoch"], 50)
        self.assertEqual(row["write_lag_if_slot130_boottime_ns"]["median_ms"], 3.0)

    def test_missing_slot130_never_approved(self):
        self.snapshots()
        self.frames("missing")
        result = inspect_slot130(self.before, self.csv, self.after)
        self.assertEqual(result["status"], "SLOT130_MISSING_OR_SPARSE")
        self.assertEqual(result["per_camera"]["0"]["slot130_nonzero"], 0)

    def test_corrupt_114_fails_closed(self):
        self.snapshots()
        self.frames("qtimer", corrupt114=True)
        with self.assertRaises(ValueError):
            inspect_slot130(self.before, self.csv, self.after)

    def test_bad_baseline_fails_closed(self):
        self.snapshots(drift=5_000_000)
        self.frames("qtimer")
        with self.assertRaisesRegex(ValueError, "baseline rejected"):
            inspect_slot130(self.before, self.csv, self.after)


if __name__ == "__main__":
    unittest.main()
