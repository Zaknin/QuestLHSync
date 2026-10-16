"""Unit tests for static CameraImageListener branch table decoding."""
import struct
import tempfile
import unittest
from pathlib import Path

from pico.tools.audit_k0_listener_table import (
    decode_dispatch, read_elf_va, BRANCH_BASE, TABLE_VA,
)


class ListenerTableTests(unittest.TestCase):
    def test_four_static_ids(self):
        routes = decode_dispatch(bytes([0, 7, 10, 13]))
        self.assertEqual([r["camera_id"] for r in routes], [0, 3, 4, 5])
        self.assertEqual(routes[0]["target_va"], f"0x{BRANCH_BASE:x}")

    def test_fallback_cannot_be_called_a_fixed_camera(self):
        route = decode_dispatch(bytes([3, 0, 7, 10]))[0]
        self.assertEqual(route["kind"], "listener_member_camera_id")
        self.assertIsNone(route["camera_id"])

    def test_unrecognized_arm64_target_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unexpected indirect branch"):
            decode_dispatch(bytes([1, 0, 7, 10]))

    def test_four_entries_are_mandatory(self):
        with self.assertRaisesRegex(ValueError, "four table bytes"):
            decode_dispatch(bytes([0, 7, 10]))

    def test_mapped_binary_table(self):
        with tempfile.TemporaryDirectory() as tmp:
            file = Path(tmp) / "synthetic.so"
            blob = bytearray(0x200)
            blob[:16] = b"\x7fELF" + bytes([2, 1, 1]) + bytes(9)
            struct.pack_into("<H", blob, 16, 3)
            struct.pack_into("<H", blob, 18, 183)
            struct.pack_into("<I", blob, 20, 1)
            struct.pack_into("<Q", blob, 32, 64)
            struct.pack_into("<H", blob, 52, 64)
            struct.pack_into("<H", blob, 54, 56)
            struct.pack_into("<H", blob, 56, 1)
            struct.pack_into("<IIQQQQQQ", blob, 64,
                             1, 4, 0x100, TABLE_VA, TABLE_VA, 0x40, 0x40, 0x1000)
            blob[0x100:0x104] = bytes([0, 7, 10, 13])
            file.write_bytes(blob)
            self.assertEqual(read_elf_va(file, TABLE_VA, 4), bytes([0, 7, 10, 13]))
            with self.assertRaisesRegex(ValueError, "not covered"):
                read_elf_va(file, TABLE_VA + 0x3f, 4)

    def test_wrong_elf_cpu_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            file = Path(tmp) / "wrong-cpu.so"
            blob = bytearray(64)
            blob[:16] = b"\x7fELF" + bytes([2, 1, 1]) + bytes(9)
            struct.pack_into("<H", blob, 18, 62)
            file.write_bytes(blob)
            with self.assertRaisesRegex(ValueError, "EM_AARCH64"):
                read_elf_va(file, 0, 1)


if __name__ == "__main__":
    unittest.main()
