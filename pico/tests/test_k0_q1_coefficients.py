"""Synthetic ARM64 integer/constructor provenance checks, no firmware required."""
import struct
import unittest

from pico.tools.audit_k0_q1_coefficients import (
    CAMERA_COUNT, CAMERA_STRIDE, correction_ns, decode_q1,
    field_offsets, signed_64,
)


class K0Q1CoefficientTests(unittest.TestCase):
    def test_exact_128_bit_initializer_order_B_then_A(self):
        data = struct.pack("<qq", 87000, -3)
        got = decode_q1(data)
        self.assertEqual(got["B_int64"], 87000)
        self.assertEqual(got["A_int64"], -3)

    def test_known_1204_frame_constraint(self):
        # Distinct A and B values with exact measured A+2B=173997
        self.assertEqual(correction_ns(a=997, b=86500, exposure_code=4), 225997)

    def test_zero_coefficients_preserve_fixed_subtraction(self):
        self.assertEqual(correction_ns(0, 0), 52000)

    def test_negative_B_uses_arithmetic_shift(self):
        self.assertEqual(correction_ns(a=0, b=-1, exposure_code=3), 51998)

    def test_arm64_64_bit_integer_wrap(self):
        self.assertEqual(signed_64(1 << 63), -(1 << 63))
        self.assertEqual(signed_64((1 << 64) + 4), 4)
        self.assertEqual(correction_ns(0, (1 << 63) - 1, 4), 51998)

    def test_seven_camera_initializer_offsets_match_callback(self):
        for i in range(CAMERA_COUNT):
            layout = field_offsets(i)
            self.assertEqual(layout["ctor_q1_write_B_this_relative"],
                             layout["callback_B_this_relative"])
            self.assertEqual(layout["ctor_q1_write_A_this_relative"],
                             layout["callback_A_this_relative"])
            self.assertEqual(layout["callback_B_this_relative"],
                             0x330 + i * CAMERA_STRIDE)

    def test_other_camera_index_rejected(self):
        for index in (-1, CAMERA_COUNT):
            with self.assertRaisesRegex(ValueError, "Invalid native camera"):
                field_offsets(index)

    def test_bad_q1_literal_rejected(self):
        with self.assertRaisesRegex(ValueError, "128-bit"):
            decode_q1(b"\x00" * 8)

    def test_bad_exposure_range_rejected(self):
        with self.assertRaisesRegex(ValueError, "signed int32"):
            correction_ns(0, 0, 1 << 31)


if __name__ == "__main__":
    unittest.main()
