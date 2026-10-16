"""Test the bounded offline ELF64 virtual-address string reader."""
import struct
import tempfile
import unittest
from pathlib import Path

from pico.tools.elf_cstring_at_va import elf_cstring


class ElfCStringTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.elf = Path(self.tmp.name) / "synthetic-aarch64.so"
        # Minimal ELF64 little-endian AArch64 with a single PT_LOAD.
        data = bytearray(0x300)
        data[:16] = b"\x7fELF" + bytes([2, 1, 1]) + bytes(9)
        struct.pack_into("<H", data, 16, 3)       # ET_DYN
        struct.pack_into("<H", data, 18, 183)     # EM_AARCH64
        struct.pack_into("<I", data, 20, 1)       # EV_CURRENT
        struct.pack_into("<Q", data, 32, 64)      # e_phoff
        struct.pack_into("<H", data, 52, 64)      # e_ehsize
        struct.pack_into("<H", data, 54, 56)      # e_phentsize
        struct.pack_into("<H", data, 56, 1)       # e_phnum
        # Map VA 0x2000..0x207f -> file offset 0x100..0x17f
        struct.pack_into("<IIQQQQQQ", data, 64,
                         1, 4, 0x100, 0x2000, 0x2000, 0x80, 0x80, 0x1000)
        data[0x120:0x120+12] = b"cam=%lld %d\x00"
        self.payload = data
        self.elf.write_bytes(data)

    def test_resolves_virtual_address_through_pt_load(self):
        self.assertEqual(elf_cstring(self.elf, 0x2020),
                         b"cam=%lld %d")

    def test_unknown_address_rejected(self):
        with self.assertRaisesRegex(ValueError, "not backed"):
            elf_cstring(self.elf, 0x3000)

    def test_nonterminated_string_rejected(self):
        data = bytearray(self.payload)
        data[0x120:0x120+5] = b"aaaaa"
        self.elf.write_bytes(data)
        with self.assertRaisesRegex(ValueError, "No NUL"):
            elf_cstring(self.elf, 0x2020, 4)

    def test_wrong_cpu_rejected(self):
        data = bytearray(self.payload)
        struct.pack_into("<H", data, 18, 62)
        self.elf.write_bytes(data)
        with self.assertRaisesRegex(ValueError, "AArch64"):
            elf_cstring(self.elf, 0x2020)

    def test_bounded_size_rejected(self):
        with self.assertRaisesRegex(ValueError, "max_bytes"):
            elf_cstring(self.elf, 0x2020, 5000)


if __name__ == "__main__":
    unittest.main()
