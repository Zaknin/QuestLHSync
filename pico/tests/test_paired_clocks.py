"""Synthetic, headset-independent tests for paired K0 clock audit."""
import csv
import tempfile
import unittest
from pathlib import Path
from pico.tools.audit_paired_clocks import analyze

FIELDS = ['cam', 'seq', 'newest_seq', 'ring_ts84_ns', 'vendor_ns', 'mono_ns', 'boot_ns']


class PairedClockTests(unittest.TestCase):
    def fixture(self, skew_ppm=0, duplicate=False, missing_camera=False, image_jump=False):
        data = []
        start = 123456789123456789
        for i in range(301):
            for cam in (0, 3, 4, 5):
                if missing_camera and cam == 5:
                    continue
                producer_boot = start + 40000000 * i + cam * 150000
                image = start + 4736000000 + round((1 + skew_ppm / 1e6) * 40000000 * i)
                image += cam * 4
                if image_jump and cam == 3 and i == 100:
                    image -= 1000000000
                data.append(dict(cam=cam, seq=2*i+1, newest_seq=2*i+3,
                                 ring_ts84_ns=producer_boot, vendor_ns=image,
                                 mono_ns=producer_boot + 42000000,
                                 boot_ns=producer_boot + 138000000000 + 42000000))
        if duplicate:
            data.append(data[2].copy())
        with tempfile.NamedTemporaryFile('w', suffix='.csv', newline='', delete=False) as out:
            writer = csv.DictWriter(out, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows(data)
            path = Path(out.name)
        self.addCleanup(lambda: path.unlink(missing_ok=True))
        return path

    def test_zero_skew_does_not_validate_epoch(self):
        result = analyze(self.fixture())
        self.assertEqual(result['shared_sequence_groups'], 301)
        self.assertLessEqual(result['image_stamp_max_intercamera_ns'], 20)
        for cam in ('0', '3', '4', '5'):
            self.assertAlmostEqual(result['per_camera'][cam]['camera_vs_producer_boottime_rate_ppm'], 0, delta=.001)
        self.assertFalse(result['flags']['camera_clock_epoch_verified'])
        self.assertFalse(result['flags']['live_lighthouse_correction_allowed'])

    def test_known_12ppm_skew(self):
        result = analyze(self.fixture(skew_ppm=12))
        for cam in ('0', '3', '4', '5'):
            self.assertAlmostEqual(result['per_camera'][cam]['camera_vs_producer_boottime_rate_ppm'], 12, delta=.01)

    def test_duplicate_sequence_rejected(self):
        with self.assertRaisesRegex(ValueError, 'nonmonotonic / duplicate'):
            analyze(self.fixture(duplicate=True))

    def test_missing_camera_rejected(self):
        with self.assertRaisesRegex(ValueError, 'four K0 cameras'):
            analyze(self.fixture(missing_camera=True))

    def test_image_timestamp_jump_rejected(self):
        with self.assertRaisesRegex(ValueError, 'image timestamp'):
            analyze(self.fixture(image_jump=True))


if __name__ == '__main__':
    unittest.main()
