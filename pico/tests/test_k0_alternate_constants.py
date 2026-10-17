"""Regression tests for offline readonly ELF constant-pair search."""
import struct
import unittest

from pico.tools.audit_k0_alternate_constants import (
    find_pairs, readonly_segments,
)


def fixture_elf(flags=4, pair=(20257, 133483)):
    blob = bytearray(0x180)
    blob[:16] = bytes.fromhex("7f454c46") + bytes([2, 1, 1]) + bytes(9)
    struct.pack_into("<H", blob, 16, 3)
    struct.pack_into("<H", blob, 18, 183)
    struct.pack_into("<I", blob, 20, 1)
    struct.pack_into("<Q", blob, 32, 64)
    struct.pack_into("<H", blob, 52, 64)
    struct.pack_into("<H", blob, 54, 56)
    struct.pack_into("<H", blob, 56, 1)
    struct.pack_into("<IIQQQQQQ", blob, 64,
                     1, flags, 0x100, 0x73170, 0x73170, 0x40, 0x40, 0x1000)
    struct.pack_into("<qq", blob, 0x100, *pair)
    return bytes(blob)


class AlternateConstantTests(unittest.TestCase):
    def test_alternate_pair_matches_exact_observed_delta(self):
        parts = readonly_segments(fixture_elf())
        self.assertEqual(len(parts), 1)
        matches = find_pairs(*parts[0])
        self.assertEqual(matches, [{"va": "0x73170", "B": 20257, "A": 133483}])

    def test_constructor_literal_is_not_an_alternate_match(self):
        parts = readonly_segments(fixture_elf(pair=(19069, 133483)))
        self.assertEqual(find_pairs(*parts[0]), [])

    def test_writable_segment_not_considered_rodata(self):
        self.assertEqual(readonly_segments(fixture_elf(flags=6)), [])

    def test_executable_segment_not_considered_rodata(self):
        self.assertEqual(readonly_segments(fixture_elf(flags=5)), [])

    def test_invalid_elf_rejected(self):
        with self.assertRaisesRegex(ValueError, "ELF64"):
            readonly_segments(b"invalid")

    def test_8_byte_alignment(self):
        data = bytearray(32)
        struct.pack_into("<qq", data, 8, 20257, 133483)
        self.assertEqual(find_pairs(0x1000, data)[0]["va"], "0x1008")


if __name__ == "__main__":
    unittest.main()
