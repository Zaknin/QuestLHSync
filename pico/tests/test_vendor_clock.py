"""Synthetic regression tests: no Pico headset or private calibration required."""
import csv
import tempfile
import unittest
from pathlib import Path

from pico.tools.analyze_vendor_clock import analyze

HEADER = ["sample", "cam", "seq", "newest_seq", "slot", "ring_index",
          "ring_ts84_ns", "image_ts114_ns", "vendor_ns", "ring_ts130_ns", "mono_ns", "boot_ns", "boot_minus_mono_ns"]


class VendorClockTest(unittest.TestCase):
    def save(self, data, header=HEADER):
        f = tempfile.NamedTemporaryFile(mode="w", suffix=".csv", newline="", delete=False)
        with f:
            writer = csv.DictWriter(f, header)
            writer.writeheader()
            writer.writerows(data)
        self.addCleanup(lambda: Path(f.name).unlink(missing_ok=True))
        return f.name

    def synthetic(self, corrupt=False):
        rows = []
        for i in range(450):
            for cam in (0, 3, 4, 5):
                mono = 1_000_000_000_000 + i * 40_000_000 + cam * 1_000
                boot = mono + 138_000_000_000
                # Fabricated epoch: vendor appears +4.66s from BOOTTIME.
                vendor = boot + 4_660_000_000
                ts84 = vendor - 4_736_000_000
                ts130 = vendor - 230_000
                if corrupt and i == 200 and cam == 3:
                    vendor -= 100_000_000
                rows.append(dict(sample=i, cam=cam, seq=1+2*i,
                                 newest_seq=3+2*i, slot=i%5, ring_index=(i+1)%5,
                                 ring_ts84_ns=ts84, image_ts114_ns=vendor, vendor_ns=vendor, ring_ts130_ns=ts130,
                                 mono_ns=mono, boot_ns=boot,
                                 boot_minus_mono_ns=boot-mono))
        return rows

    def test_vendor_epoch_must_not_be_interpreted_as_exposure(self):
        report = analyze(self.save(self.synthetic()))
        self.assertEqual(report["status"], "DIAGNOSTIC_ONLY")
        self.assertFalse(report["actual_exposure_time_verified"])
        for camera in report["per_camera"].values():
            self.assertEqual(camera["samples"], 450)
            self.assertAlmostEqual(camera["vendor_frame_delta_ms_median"], 40)
            self.assertAlmostEqual(camera["vendor_minus_boot_ms_median"], 4660)
            self.assertAlmostEqual(camera["ts84_minus_boot_ms_median"], -76)
            self.assertAlmostEqual(camera["ts122_minus_ts84_ms_median"], 4736)
            self.assertEqual(camera["image_ts114_equals_ts122_fraction"], 1)
            self.assertAlmostEqual(camera["ts122_minus_ts130_ms_median"], 0.230)
            self.assertAlmostEqual(camera["boot_minus_mono_ms_median"], 138000)
            self.assertAlmostEqual(camera["vendor_vs_mono_rate_difference_ppm"], 0, places=4)
            self.assertEqual(camera["selected_exactly_one_frame_behind_fraction"], 1.0)
            self.assertEqual(camera["ring_pointer_one_slot_ahead_fraction"], 1.0)
            self.assertAlmostEqual(camera["age_after_subtracting_one_period_ms"], 36, places=2)
            self.assertAlmostEqual(camera["boot_minus_mono_span_ms"], 0, places=4)

    def test_detects_nonmonotonic_vendor(self):
        report = analyze(self.save(self.synthetic(corrupt=True)))
        self.assertEqual(report["status"], "INVALID_OR_INCOMPLETE")
        self.assertTrue(any("nonmonotonic" in e for e in report["errors"]))

    def test_rejects_unrelated_csv(self):
        with self.assertRaises(ValueError):
            analyze(self.save([], header=["sample", "another_column"]))

    def test_rejects_invalid_ring(self):
        rows = self.synthetic()
        rows[0]["newest_seq"] = rows[0]["seq"]
        report = analyze(self.save(rows))
        self.assertEqual(report["status"], "INVALID_OR_INCOMPLETE")


if __name__ == "__main__":
    unittest.main()
