"""Fail-closed, synthetic QTIMER->MONOTONIC shadow tests; no device access."""
import csv
import tempfile
import unittest
from pathlib import Path

from pico.tools.audit_shadow_k0_time import interpolate, shadow
from pico.tools.audit_qtimer_bridge import parse_pvr_snapshot

FIELDS = ("sample", "cam", "seq", "newest_seq", "slot", "ring_index",
          "ring_ts84_ns", "image_ts114_ns", "vendor_ns",
          "ring_ts130_ns", "mono_ns", "boot_ns", "boot_minus_mono_ns")


class ShadowTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        p = Path(tmp.name)
        self.before, self.csv, self.after = p / "before.txt", p / "k0.csv", p / "after.txt"
        self.epoch = 30_000_000_000_000
        self.qoffset = 4_746_503_000
        self.bmono = 18_618_216_260_000

    def snapshots(self, qdrift=0, snap_shift=0):
        for path, boot, drift in [
            (self.before, self.epoch + snap_shift, 0),
            (self.after, self.epoch + snap_shift + 10_000_000_000, qdrift),
        ]:
            path.write_text(
                "PvrTrackingService\n"
                f"time boottime {boot}, monotime {boot - self.bmono}, "
                f"qtimer {boot + self.qoffset + drift}\n",
                encoding="utf-8",
            )

    def frames(self, lag_ns=10_000_000, copy_after_ns=45_000_000,
               mismatched_114=False, outside=False):
        with self.csv.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, FIELDS)
            w.writeheader()
            for seq in range(50):
                for cam in (0, 3, 4, 5):
                    producer = self.epoch + (12_000_000_000 if outside else
                                            2_000_000_000) + seq * 40_000_000
                    image = producer + self.qoffset - lag_ns
                    w.writerow({
                        "sample": seq, "cam": cam, "seq": seq * 2 + 1,
                        "newest_seq": seq * 2 + 3,
                        "slot": 0, "ring_index": 0,
                        "ring_ts84_ns": producer,
                        "image_ts114_ns": image + int(mismatched_114),
                        "vendor_ns": image,
                        "ring_ts130_ns": image,
                        "mono_ns": producer - self.bmono + copy_after_ns,
                        "boot_ns": producer + copy_after_ns,
                        "boot_minus_mono_ns": self.bmono,
                    })

    def test_pvr_clock_parser_contract_is_monotime_ns(self):
        self.snapshots()
        before = parse_pvr_snapshot(self.before)
        self.assertEqual(before["monotime_ns"], before["boottime_ns"] - self.bmono)
        self.assertEqual(
            before["qtimer_ns"] - before["monotime_ns"],
            self.qoffset + self.bmono,
        )

    def test_clean_shadow_never_unblocks_live_correction(self):
        self.snapshots()
        self.frames()
        result = shadow(self.before, self.csv, self.after)
        self.assertEqual(result["status"], "QTIMER_SHADOW_PLAUSIBLE_UNVERIFIED")
        self.assertEqual(result["input_frames"], 200)
        self.assertEqual(result["pvr_clock_bracketed_frames"], 200)
        for stats in result["per_camera"].values():
            self.assertAlmostEqual(
                stats["qtimer_model_producer_lag"]["median_ms"], 10)
            self.assertAlmostEqual(
                stats["qtimer_model_reader_age"]["median_ms"], 55)
        self.assertFalse(result["gates"]["live_lighthouse_correction_allowed"])
        self.assertEqual(result["gates"]["sensor_exposure_timestamp"], "UNVERIFIED")

    def test_qtimer_drift_rejected(self):
        self.snapshots(qdrift=5_000_000)
        self.frames()
        result = shadow(self.before, self.csv, self.after)
        self.assertEqual(result["status"], "QTIMER_SHADOW_REJECTED_OR_INCOMPLETE")

    def test_bad_producer_latency_rejected(self):
        self.snapshots()
        self.frames(lag_ns=150_000_000)
        result = shadow(self.before, self.csv, self.after)
        self.assertEqual(result["status"], "QTIMER_SHADOW_REJECTED_OR_INCOMPLETE")

    def test_outside_bracket_rejected(self):
        self.snapshots()
        self.frames(outside=True)
        result = shadow(self.before, self.csv, self.after)
        self.assertEqual(result["status"], "QTIMER_SHADOW_REJECTED_OR_INCOMPLETE")
        self.assertEqual(result["pvr_clock_bracketed_frames"], 0)

    def test_camera_slot_114_must_match_122(self):
        self.snapshots()
        self.frames(mismatched_114=True)
        with self.assertRaisesRegex(ValueError, "114"):
            shadow(self.before, self.csv, self.after)

    def test_implausible_reader_age_rejected(self):
        self.snapshots()
        self.frames(copy_after_ns=3_000_000_000)
        result = shadow(self.before, self.csv, self.after)
        self.assertEqual(result["status"], "QTIMER_SHADOW_REJECTED_OR_INCOMPLETE")

    def test_integer_interpolation_with_negative_drift(self):
        self.assertEqual(interpolate(100, 98, 1, 0, 3), 99)
        self.assertEqual(interpolate(100, 98, 2, 0, 3), 99)
        with self.assertRaises(ValueError):
            interpolate(1, 2, 4, 0, 3)


if __name__ == "__main__":
    unittest.main()
