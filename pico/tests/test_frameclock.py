"""Synthetic tests for optical frame-clock log validation."""
import tempfile
import unittest
from pathlib import Path

from pico.tools.analyze_frameclock import analyze


class FrameClockTest(unittest.TestCase):
    def write(self, lines):
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".txt", delete=False) as f:
            f.write("\n".join(lines) + "\n")
        self.addCleanup(lambda: Path(f.name).unlink(missing_ok=True))
        return Path(f.name)

    def rows(self, missing=None, clock_jump=False, corrupt_age=False):
        lines = []
        for i in range(4):
            for cam in (0, 3, 4, 5):
                if cam == missing:
                    continue
                mono = 1_000_000_000_000 + i * 5_000_000_000 + cam * 300_000
                boot = mono + 18_618_216_261_949
                if clock_jump and i == 3 and cam == 5:
                    boot += 2_000_000
                write = boot - 43_000_000
                age = 42 if corrupt_age and cam == 4 else 43
                lines.append(
                    f"PicoFrameClock cam={cam} seq={3251+i*250} "
                    f"producer_write_boot_ns={write} java_copy_mono_ns={mono} "
                    f"java_copy_boot_ns={boot} producer_to_copy_ms={age:.6f}"
                )
        return lines

    def test_pass(self):
        report = analyze(self.write(self.rows()))
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["samples_total"], 16)
        for cam in (0, 3, 4, 5):
            self.assertAlmostEqual(report["per_camera"][str(cam)]["producer_to_copy_ms_median"], 43)
        self.assertFalse(report["validated_exposure_time"])
        self.assertAlmostEqual(report["boot_minus_mono_ms_span"], 0)

    def test_missing_camera(self):
        report = analyze(self.write(self.rows(missing=3)))
        self.assertEqual(report["status"], "REVIEW")
        self.assertTrue(any("camera coverage" in s for s in report["issues"]))

    def test_clock_jump(self):
        report = analyze(self.write(self.rows(clock_jump=True)))
        self.assertEqual(report["status"], "REVIEW")
        self.assertTrue(any("offset shifted" in s for s in report["issues"]))

    def test_incorrect_age(self):
        report = analyze(self.write(self.rows(corrupt_age=True)))
        self.assertEqual(report["status"], "REVIEW")
        self.assertTrue(any("invalid producer age" in s for s in report["issues"]))


if __name__ == "__main__":
    unittest.main()
