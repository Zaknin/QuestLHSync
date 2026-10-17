"""Static unit checks for 7-slot CameraManager layout and rodata word decoding."""
import math
import struct
import unittest

from pico.tools.audit_k0_constructor_literal import (
    decode_literal, offset_layout, NUM_SLOTS, STRIDE,
)


class ConstructorLiteralTests(unittest.TestCase):
    def test_constructor_first_camera_offsets(self):
        v = offset_layout()
        self.assertEqual(len(v), NUM_SLOTS)
        self.assertEqual(v[0]["ctor_store_x20_this_relative_B"], "0x70")
        self.assertEqual(v[0]["ctor_store_x20_this_relative_A"], "0x78")
        self.assertEqual(v[0]["reader_x19_relative_B"], "0x330")
        self.assertEqual(v[0]["base_delta_required_for_same_fields"], -0x2C0)

    def test_seven_slots_are_spaced_0x320(self):
        v = offset_layout()
        first = int(v[0]["ctor_store_x20_this_relative_B"], 16)
        last = int(v[-1]["ctor_store_x20_this_relative_B"], 16)
        self.assertEqual(last-first, 6*STRIDE)

    def test_bitwise_unsigned_and_signed_literal(self):
        v = decode_literal((173997).to_bytes(8, "little", signed=False))
        self.assertEqual(v["i64_bits"], 173997)
        self.assertEqual(v["u64_bits"], 173997)

    def test_double_bits_are_labelled_not_assumed_to_be_time(self):
        v = decode_literal(struct.pack("<d", 1.0))
        self.assertEqual(v["f64_interpretation"], "1.0")
        self.assertNotEqual(v["i64_bits"], 1)

    def test_reject_non_eight_byte_literal(self):
        with self.assertRaisesRegex(ValueError, "exact 8 bytes"):
            decode_literal(b"\x00" * 7)

    def test_negative_64_bit_value(self):
        v = decode_literal((-200).to_bytes(8, "little", signed=True))
        self.assertEqual(v["i64_bits"], -200)


if __name__ == "__main__":
    unittest.main()
