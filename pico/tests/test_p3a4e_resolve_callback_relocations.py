"""Pure synthetic ABI and integrity tests. No Pico, no vendor binary needed."""
import hashlib
import json
from pathlib import Path
import struct
import tempfile
import unittest
import zipfile

from pico.tools.p3a4e_resolve_callback_relocations import (
    Elf64Arm, check_owner_manifest, atomic_publish, PIN_PVR,
)


def make_elf(rela=True, target=0x40400, mach=183):
    # ELF64 with two PT_LOAD segments, one RW relocation target, one executable.
    raw = bytearray(0x3000)
    raw[:6] = b'\x7fELF\x02\x01'
    struct.pack_into('<16sHHIQQQIHHHHHH', raw, 0,
                     bytes(raw[:16]), 3, mach, 1, 0, 64, 0x500, 0, 64, 56, 2, 64, 2, 0)
    struct.pack_into('<IIQQQQQQ', raw, 64,
                     1, 5, 0x1000, 0x40000, 0, 0x1000, 0x1000, 0x1000)
    struct.pack_into('<IIQQQQQQ', raw, 64 + 56,
                     1, 6, 0x2000, 0x75000, 0, 0x1000, 0x1000, 0x1000)
    struct.pack_into('<IIQQQQIIQQ', raw, 0x500 + 64,
                     0, 4 if rela else 9, 0, 0, 0x300, 24 if rela else 16,
                     0, 0, 8, 24 if rela else 16)
    if rela:
        struct.pack_into('<QQq', raw, 0x300, 0x752d0, 1027, target)
    else:
        struct.pack_into('<QQ', raw, 0x300, 0x752d0, 1027)
        struct.pack_into('<Q', raw, 0x22d0, target)
    struct.pack_into('<II', raw, 0x1400, 0xd503201f, 0xd65f03c0)
    return bytes(raw)


class TestElfRelocations(unittest.TestCase):
    def test_explicit_rela_addend_even_if_raw_slot_zero(self):
        elf = Elf64Arm(make_elf())
        r = elf.relocated_slots()[0x752d0]
        self.assertEqual(r['addend_source'], 'explicit_rela')
        self.assertEqual(r['candidate_address'], 0x40400)
        self.assertEqual(r['raw_slot_hex'], '0x0')
        self.assertTrue(r['candidate_executable'])

    def test_implicit_rel_addend_from_slot_bytes(self):
        elf = Elf64Arm(make_elf(rela=False))
        r = elf.relocated_slots()[0x752d0]
        self.assertEqual(r['addend_source'], 'implicit_slot_contents')
        self.assertEqual(r['candidate_address'], 0x40400)

    def test_non_executable_target_rejected_as_candidate(self):
        elf = Elf64Arm(make_elf(target=0x752d0))
        r = elf.relocated_slots()[0x752d0]
        self.assertFalse(r['candidate_executable'])
        self.assertIsNone(r['candidate_address'])

    def test_wrong_machine_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Wrong ELF machine'):
            Elf64Arm(make_elf(mach=62))

    def test_no_executable_bytes_outside_segment(self):
        elf = Elf64Arm(make_elf(target=0x41400))
        self.assertIsNone(elf.relocated_slots()[0x752d0]['candidate_address'])

    def test_truncated_tables_rejected(self):
        with self.assertRaises(ValueError):
            Elf64Arm(make_elf()[:0x500])


class TestIntegrity(unittest.TestCase):
    def test_digest_and_sidecar(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            name = 'p3a4-bridge-20261018T093025Z-test'
            js = output / (name + '.json')
            archive = output / (name + '.zip')
            js.write_text(json.dumps({
                'schema': 'p3a4.offline.bridge.v3',
                'status': 'TRACE_CAPTURED_NOT_PROVEN',
                'input_sha256': {'pvr': PIN_PVR},
                'observe_only': True,
                'exact_time': False,
                'live_lighthouse_correction_allowed': False,
                'mapping_verified': False, 'pose_verified': False,
                'frame_meta_bridge_verified': False,
            }), encoding='utf8')
            with zipfile.ZipFile(archive, 'w') as z:
                z.writestr('sample.txt', 'private')
            marker = output / (name + '.sha256')
            marker.write_text('\n'.join(
                hashlib.sha256(p.read_bytes()).hexdigest() + '  ' + p.name
                for p in (archive, js)) + '\n', encoding='ascii')
            metadata, _ = check_owner_manifest(js)
            self.assertEqual(metadata['schema'], 'p3a4.offline.bridge.v3')
            archive.write_bytes(b'tampered')
            with self.assertRaisesRegex(ValueError, 'Integrity mismatch'):
                check_owner_manifest(js)

    def test_atomic_marker_last_and_local_sources_not_leaked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report = {'observe_only': True, 'live_lighthouse_correction_allowed': False}
            result = atomic_publish(root / 'stage', root / 'published', 'run', report, {'callback-00.txt': 'ret'})
            self.assertTrue(Path(result['marker']).exists())
            with zipfile.ZipFile(result['zip']) as z:
                self.assertEqual(sorted(z.namelist()), ['callback-00.txt', 'manifest.json'])
            self.assertEqual(Path(result['marker']).read_text().count('\n'), 2)


if __name__ == '__main__':
    unittest.main()
