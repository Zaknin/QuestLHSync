"""Mock tests for P3-A; do not connect to a Pico."""
import hashlib
import shlex
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

    def test_root_shell_for_do_is_one_su_argument(self):
        script = 'for d in /vendor /system; do if [ -d "$d" ]; then find "$d" -name "*.so" -print; fi; done'
        with patch.object(m, 'adb', return_value='ok') as send:
            self.assertEqual(m.root_shell('test:5555', script, timeout=180), 'ok')
        self.assertEqual(send.call_args.args, ('test:5555', 'shell', 'su', '-c', shlex.quote(script)))
        self.assertEqual(send.call_args.kwargs, {'timeout': 180})
        # adb's reconstructed remote shell string must retain a single
        # full script as the sole argument after su -c.
        self.assertEqual(shlex.split('su -c ' + send.call_args.args[-1]), ['su', '-c', script])

    def test_root_shell_quotes_hash_and_id_too(self):
        for script in ('id', 'sha256sum /vendor/lib64/libpvrtrackingcamera.so',
                       'printf "%s" "abc def"'):
            with self.subTest(script=script), patch.object(m, 'adb', return_value='ok') as send:
                m.root_shell('test:5555', script)
                self.assertEqual(shlex.split('su -c ' + send.call_args.args[-1]),
                                 ['su', '-c', script])

    def test_inventory_happy_path_uses_only_reads(self):
        cam32 = '/system/lib/libpvrtrackingcamera.so'
        cam64 = '/system/lib64/libpvrtrackingcamera.so'
        prod_system = '/system/lib64/vendor.test.quickcamera@1.0.so'
        prod_vendor = '/vendor/lib64/vendor.test.quickcamera@1.0.so'
        core = '/vendor/lib64/quickcamera.core.so'
        impl = '/vendor/lib64/hw/pico.camera.quickcameramodule@1.0-impl.so'
        listing = '\n'.join((cam32, cam64, prod_system, prod_vendor, core, impl))
        calls = []
        def fake_adb(serial, *args, timeout=120):
            calls.append(args)
            if args == ('get-state',):
                return 'device'
            if args[:2] == ('shell', 'getprop'):
                return 'mock-build'
            raise AssertionError('Unexpected adb call: ' + repr(args))
        def fake_root(serial, command, timeout=120):
            calls.append(('root', command))
            if command == 'id':
                return 'uid=0(root) gid=0(root)'
            if command.startswith('for d in '):
                return listing
            if command.startswith('sha256sum '):
                path = command[len('sha256sum '):]
                sha = m.CAMERA_SHA if path == cam64 else 'a'*64
                return sha + '  ' + path
            raise AssertionError('Unexpected root command: ' + command)
        with patch.object(m, 'adb', side_effect=fake_adb), \
             patch.object(m, 'root_shell', side_effect=fake_root), \
             patch.object(m, 'pinned_needed', return_value=[prod_system.rsplit('/',1)[1]]):
            result = m.inventory('test:5555')
        self.assertEqual(result['status'], 'INVENTORY_READY')
        self.assertEqual(result['p2_exact_camera_paths'], [cam64])
        self.assertEqual(result['pvr_candidate_hashes'][cam32], 'a'*64)
        self.assertEqual(result['p2_matching_abi'], 'lib64')
        self.assertEqual(len(result['same_abi_dependency_paths'][prod_system.rsplit('/',1)[1]]), 2)
        self.assertEqual(result['additional_producer_candidates'], [impl, core])
        self.assertEqual(len(result['producer_hashes']), 4)
        self.assertFalse(result['producer_timestamp_proven'])
        self.assertTrue(all(c[0] in ('get-state', 'shell', 'root') for c in calls))

    def test_missing_sha_match_stays_partial(self):
        cam32 = '/system/lib/libpvrtrackingcamera.so'
        cam64 = '/system/lib64/libpvrtrackingcamera.so'
        with patch.object(m, 'adb', side_effect=lambda *a, **kw:
                          'device' if a[1:] == ('get-state',) else 'Pico'), \
             patch.object(m, 'root_shell', side_effect=lambda s, cmd, **kw:
                          'uid=0(root)' if cmd == 'id' else
                          cam32 + '\n' + cam64 if cmd.startswith('for d in ') else
                          'f'*64 + '  ' + cmd[len('sha256sum '):]), \
             patch.object(m, 'pinned_needed', return_value=['test.quickcamera.so']):
            result = m.inventory('test:5555')
        self.assertEqual(result['status'], 'PARTIAL')
        self.assertFalse(result['p2_sha_match'])
        self.assertFalse(result['producer_timestamp_proven'])

    def test_scan_only_existing_root_names(self):
        self.assertTrue(all(d.startswith('/') and not d.endswith('.so') for d in m.ROOTS))

if __name__ == '__main__':
    unittest.main()
