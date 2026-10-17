"""Mock tests for P3-A; do not connect to a Pico."""
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from pico.tools import p3a_quickcamera_inventory as m

class InventoryTest(unittest.TestCase):
    def test_parse_existing_paths(self):
        raw = '/vendor/lib64/libpvrtrackingcamera.so\n/vendor/lib64/vendor.pico.quickcamera@1.0.so\n/other/a.so\n/bad name/x.so\n'
        all_paths, selected = m.parse_inventory(raw)
        self.assertEqual(len(all_paths), 3)
        self.assertEqual(len(selected), 2)
        self.assertEqual(m.match_paths(['libpvrtrackingcamera.so'], all_paths)['libpvrtrackingcamera.so'], ['/vendor/lib64/libpvrtrackingcamera.so'])

    def test_no_guessed_missing_path(self):
        self.assertEqual(m.match_paths(['missing.so'], ['/vendor/lib64/present.so']), {'missing.so': []})

    def test_ambiguous_paths_explicit(self):
        matches = m.match_paths(['x.so'], ['/system/lib64/x.so', '/vendor/lib64/x.so'])
        self.assertEqual(len(matches['x.so']), 2)

    def test_needed(self):
        self.assertEqual(m.parse_needed('0x1 (NEEDED) Shared library: [vendor.quickcamera@1.0.so]'), ['vendor.quickcamera@1.0.so'])

    def test_malformed_hash(self):
        self.assertIsNone(m.digest_line('garbage'))
        self.assertEqual(m.digest_line('a'*64 + '  /vendor/lib64/test.so'), 'a'*64)

    def test_publish_even_blocked(self):
        with tempfile.TemporaryDirectory() as td:
            p = m.publish(dict(status='BLOCKED', errors=['mock']), td)
            self.assertEqual(hashlib.sha256(Path(p['evidence']).read_bytes()).hexdigest(), p['digest'])
            self.assertTrue(Path(p['sha256']).is_file())
            self.assertFalse(list(Path(td).glob('*.part')))

    def test_device_offline_no_fake_pass(self):
        with patch.object(m, 'adb', side_effect=RuntimeError('offline')):
            result = m.inventory('192.168.23.12:5555')
        self.assertEqual(result['status'], 'BLOCKED')
        self.assertFalse(result['producer_timestamp_proven'])

    def test_scan_only_existing_root_names(self):
        self.assertTrue(all(d.startswith('/') and not d.endswith('.so') for d in m.ROOTS))

if __name__ == '__main__':
    unittest.main()
