"""Offline regressions for the bounded P3-A6 M2.8B maps collector."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from pico.tools import p3a_m28b_runtime_mapping as m


TEST_TARGET = '192.0.2.28:5555'
PROCESS = 'com.picovr.quickcamera:service'
PID = '412'
START = '987654'
DEVICE = (179 << 8) | 31
DEV_TEXT = 'b3:1f'


def map_record(path: str, *, start: str = '7a100000', end: str = '7a101000',
               permissions: str = 'r-xp', offset: str = '00000000',
               device: str = DEV_TEXT, inode: str = '112233') -> str:
    return f'P3A28B\tMAP\t{PID}\t{PROCESS}\t{START}\t{start}-{end}\t{permissions}\t{offset}\t{device}\t{inode}\t{path}'


def process_record(status: str = 'MAPPED') -> str:
    return f'P3A28B\tPROCESS_STATUS\t{PID}\t{PROCESS}\t{START}\t{status}'


def fs_record(path: str, inode: str) -> str:
    return f'P3A28B\tFSSTAT\t{path}\tOBSERVED\t{DEVICE}\t{inode}'


def probe_output(records: list[str], status: str = 'COMPLETE', global_status: str | None = None) -> str:
    records = list(records)
    if global_status:
        records.append(f'P3A28B\tGLOBAL_STATUS\t{global_status}')
    return '\n'.join([
        'P3A28B\tBEGIN\t1',
        *records,
        f'P3A28B\tEND\t{len(records)}\t{status}',
        '',
    ])


def successful_probe() -> str:
    camx = '/vendor/lib64/camx_core.so'
    quick = '/vendor/lib64/quickcamera.core.so'
    return probe_output([
        fs_record(camx, '112233'),
        fs_record(quick, '445566'),
        process_record(),
        map_record(camx),
        map_record(camx, start='7a102000', end='7a103000', permissions='r--p', offset='00002000'),
        map_record(quick, start='7a200000', end='7a201000', inode='445566'),
    ])


class RuntimeMappingParserTests(unittest.TestCase):
    def test_only_bounded_quickcamera_hidl_and_pvr_name_patterns_are_accepted(self):
        for name in ('com.picovr.quickcamera:service', 'vendor.camera.hidl.provider', 'PVRTrackingService'):
            self.assertTrue(m._validate_process_name(name), name)
        for name in ('quickcamera/path', 'quickcamera service', 'quickcamera;id', 'other.service'):
            self.assertFalse(m._validate_process_name(name), name)

    def test_exact_paths_and_multiple_segments_are_preserved_and_correlated(self):
        parsed = m.parse_probe_output(successful_probe())
        self.assertEqual(len(parsed['mappings']), 3)
        self.assertEqual(parsed['mappings'][0]['path'], '/vendor/lib64/camx_core.so')
        self.assertEqual(parsed['mappings'][0]['pid'], 412)
        self.assertEqual(parsed['mappings'][1]['offset'], '00002000')
        result = m.evaluate_mapping_result(parsed)
        self.assertEqual(result['status'], 'PASS')
        self.assertEqual(result['provider_mapping_count'], 2)
        self.assertEqual(result['quickcamera_mapping_count'], 1)
        self.assertTrue(result['device_inode_match'])

    def test_path_without_filesystem_device_inode_match_is_partial(self):
        raw = probe_output([
            'P3A28B\tFSSTAT\t/vendor/lib64/camx_core.so\tUNAVAILABLE\tSTAT_UNAVAILABLE',
            fs_record('/vendor/lib64/quickcamera.core.so', '445566'),
            process_record(), map_record('/vendor/lib64/camx_core.so'),
            map_record('/vendor/lib64/quickcamera.core.so', inode='445566'),
        ])
        parsed = m.parse_probe_output(raw)
        result = m.evaluate_mapping_result(parsed)
        self.assertEqual(result['status'], 'PARTIAL')
        self.assertFalse(result['device_inode_match'])

    def test_no_matching_process_and_no_mapping_are_not_pass(self):
        absent = m.parse_probe_output(probe_output([], 'NO_MATCHING_PROCESSES', 'NO_MATCHING_PROCESSES'))
        self.assertEqual(m.evaluate_mapping_result(absent)['status'], 'BLOCKED')
        no_map = m.parse_probe_output(probe_output([
            process_record('NO_TARGET_MAPPING'),
        ], 'NO_TARGET_MAPPING'))
        self.assertEqual(m.evaluate_mapping_result(no_map)['status'], 'BLOCKED')

    def test_permission_denial_and_pid_reuse_stop_the_attempt(self):
        for code in ('PROC_ACCESS_DENIED', 'PID_REUSED', 'PROCESS_EXITED'):
            with self.subTest(code=code):
                parsed = m.parse_probe_output(probe_output([process_record(code)], code))
                result = m.evaluate_mapping_result(parsed)
                self.assertEqual(result['status'], 'BLOCKED')
                self.assertEqual(result['stop_reason'], code)

    def test_malformed_lines_fields_and_paths_fail_closed_without_retaining_raw(self):
        invalid_rows = [
            map_record('/vendor/lib64/unexpected.so'),
            map_record('/vendor/lib64/camx_core.so', permissions='rwxp'),
            map_record('/vendor/lib64/camx_core.so', start='7a100000', end='7a0fffff'),
            map_record('/vendor/lib64/camx_core.so', device='bad:31'),
            'P3A28B\tUNEXPECTED\tPRIVATE_RAW_TEXT',
        ]
        for invalid in invalid_rows:
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                m.parse_probe_output(probe_output([invalid]))
        with self.assertRaisesRegex(ValueError, 'OUTPUT_FRAMING'):
            m.parse_probe_output('P3A28B\tBEGIN\t1\rBAD\n')
        with self.assertRaisesRegex(ValueError, 'OUTPUT_FRAMING'):
            m.parse_probe_output('P3A28B\tBEGIN\t1\n')

    def test_record_limit_and_protocol_count_are_enforced(self):
        too_many = [
            f'P3A28B\tPROCESS_STATUS\t{500 + i}\tcom.picovr.quickcamera:{i}\t{START}\tNO_TARGET_MAPPING'
            for i in range(m.MAX_OBSERVATIONS + 1)
        ]
        with self.assertRaisesRegex(ValueError, 'OBSERVATION_LIMIT'):
            m.parse_probe_output(probe_output(too_many, 'LIMIT_REACHED'))
        with self.assertRaisesRegex(ValueError, 'RECORD_COUNT_MISMATCH'):
            m.parse_probe_output('P3A28B\tBEGIN\t1\nP3A28B\tEND\t1\tCOMPLETE\n')

    def test_crlf_is_normalized_only_at_line_boundary(self):
        raw = successful_probe().replace('\n', '\r\n')
        self.assertEqual(len(m.parse_probe_output(raw)['mappings']), 3)
        with self.assertRaisesRegex(ValueError, 'OUTPUT_FRAMING'):
            m.parse_probe_output(successful_probe().replace('P3A28B\tMAP', 'P3A28B\rMAP', 1))


class RuntimeMappingCollectorTests(unittest.TestCase):
    def setUp(self):
        self.env_patch = patch.dict(os.environ, {m.TARGET_SERIAL_ENV: TEST_TARGET})
        self.env_patch.start()
        self.hash_patch = patch.object(
            m.m27b, 'TARGET_SERIAL_SHA256', hashlib.sha256(TEST_TARGET.encode()).hexdigest(),
        )
        self.hash_patch.start()

    def tearDown(self):
        self.hash_patch.stop()
        self.env_patch.stop()

    def test_exact_fixed_allowlist_rejects_arbitrary_commands(self):
        selector = ['-s', TEST_TARGET]
        self.assertTrue(m.allowed_adb_arguments(['connect', TEST_TARGET], selector))
        self.assertTrue(m.allowed_adb_arguments([*selector, 'get-state'], selector))
        for key in ('ro.build.fingerprint', 'ro.product.cpu.abi'):
            self.assertTrue(m.allowed_adb_arguments([*selector, 'shell', 'getprop', key], selector))
        self.assertTrue(m.allowed_adb_arguments(
            [*selector, 'shell', 'sh', '-c', m.PROBE_ARGUMENT], selector,
        ))
        for argv in (
            ['connect', '192.0.2.29:5555'],
            [*selector, 'shell', 'su', '-c', 'id'],
            [*selector, 'shell', 'cat', '/proc/1/maps'],
            [*selector, 'shell', 'sh', '-c', m.PROBE_ARGUMENT + '; id'],
            [*selector, 'pull', '/vendor/lib64/camx_core.so', 'out'],
        ):
            self.assertFalse(m.allowed_adb_arguments(argv, selector), argv)

    def test_collector_checks_identity_then_emits_exact_vectors(self):
        selector = ['-s', TEST_TARGET]
        calls = []

        def executor(argv, *, timeout, stage):
            self.assertTrue(m.allowed_adb_arguments(argv, selector), argv)
            calls.append(tuple(argv))
            if argv == ['connect', TEST_TARGET]:
                return f'already connected to {TEST_TARGET}\n'
            command = argv[len(selector):]
            if command == ['get-state']:
                return 'device\n'
            if command == ['shell', 'getprop', 'ro.build.fingerprint']:
                return m.TARGET_FINGERPRINT + '\n'
            if command == ['shell', 'getprop', 'ro.product.cpu.abi']:
                return m.TARGET_ABI + '\n'
            if command == ['shell', 'sh', '-c', m.PROBE_ARGUMENT]:
                return successful_probe()
            self.fail(f'unexpected ADB vector {argv!r}')

        with tempfile.TemporaryDirectory() as td:
            report = m.collect_mapping(selector, Path(td), executor=executor,
                                       owner_authorized=True, monotonic_fn=lambda: 0.0)
        self.assertEqual(report['status'], 'PASS')
        self.assertEqual(report['adb_command_count'], 5)
        self.assertEqual(calls, [
            ('connect', TEST_TARGET), (*selector, 'get-state'),
            (*selector, 'shell', 'getprop', 'ro.build.fingerprint'),
            (*selector, 'shell', 'getprop', 'ro.product.cpu.abi'),
            (*selector, 'shell', 'sh', '-c', m.PROBE_ARGUMENT),
        ])
        self.assertFalse(report['raw_process_table_saved'])
        self.assertFalse(report['raw_maps_saved'])
        self.assertNotIn(TEST_TARGET, str(report))
        self.assertIn('observation_window_utc', report['mappings'][0])
        self.assertEqual(report['safety']['mapping_verified'], False)
        self.assertEqual(report['safety']['live_lighthouse_correction_allowed'], False)

    def test_identity_mismatch_stops_before_procfs_probe(self):
        selector = ['-s', TEST_TARGET]
        calls = []

        def executor(argv, *, timeout, stage):
            self.assertTrue(m.allowed_adb_arguments(argv, selector), argv)
            calls.append(tuple(argv))
            if argv == ['connect', TEST_TARGET]:
                return f'connected to {TEST_TARGET}\n'
            if argv[-1:] == ['get-state']:
                return 'device\n'
            return 'unexpected-fingerprint\n'

        with tempfile.TemporaryDirectory() as td:
            report = m.collect_mapping(selector, Path(td), executor=executor,
                                       owner_authorized=True, monotonic_fn=lambda: 0.0)
        self.assertEqual(report['status'], 'BLOCKED_IDENTITY_MISMATCH')
        self.assertFalse(any(call[-4:-1] == ('shell', 'sh', '-c') for call in calls))

    def test_denial_or_pid_reuse_stops_without_retry(self):
        for stop in ('PROC_ACCESS_DENIED', 'PID_REUSED'):
            selector = ['-s', TEST_TARGET]
            raw = probe_output([process_record(stop)], stop)
            calls = []

            def executor(argv, *, timeout, stage):
                self.assertTrue(m.allowed_adb_arguments(argv, selector), argv)
                calls.append(tuple(argv))
                if argv == ['connect', TEST_TARGET]:
                    return f'already connected to {TEST_TARGET}\n'
                if argv[-1:] == ['get-state']:
                    return 'device\n'
                if argv[-1:] == ['ro.build.fingerprint']:
                    return m.TARGET_FINGERPRINT + '\n'
                if argv[-1:] == ['ro.product.cpu.abi']:
                    return m.TARGET_ABI + '\n'
                return raw

            with self.subTest(stop=stop), tempfile.TemporaryDirectory() as td:
                report = m.collect_mapping(selector, Path(td), executor=executor,
                                           owner_authorized=True, monotonic_fn=lambda: 0.0)
            self.assertEqual(report['status'], 'BLOCKED')
            self.assertEqual(report['runtime_result']['stop_reason'], stop)
            self.assertEqual(len(calls), 5)

    def test_duration_is_rechecked_before_every_native_command(self):
        selector = ['-s', TEST_TARGET]
        calls = []
        ticks = iter([0.0, 0.0, 16.0, 16.0])

        def executor(argv, *, timeout, stage):
            self.assertTrue(m.allowed_adb_arguments(argv, selector), argv)
            calls.append(tuple(argv))
            return f'already connected to {TEST_TARGET}\n'

        with tempfile.TemporaryDirectory() as td:
            report = m.collect_mapping(selector, Path(td), executor=executor,
                                       owner_authorized=True, monotonic_fn=lambda: next(ticks))
        self.assertEqual(report['status'], 'BLOCKED_TIMEOUT')
        self.assertEqual(len(calls), 1)

    def test_no_owner_mode_calls_nothing_and_dry_run_has_no_device_effects(self):
        selector = ['-s', TEST_TARGET]
        with tempfile.TemporaryDirectory() as td:
            report = m.collect_mapping(selector, Path(td), executor=lambda *a, **k: self.fail('ADB called'),
                                       owner_authorized=False)
        self.assertEqual(report['status'], 'BLOCKED_OWNER_AUTHORIZATION_REQUIRED')
        plan = m.dry_run_plan()
        self.assertEqual(plan['status'], 'DRY_RUN_ONLY')
        self.assertFalse(plan['device_facing_calls_performed'])
        with patch.object(m, 'resolve_adb_executable', side_effect=AssertionError('must not resolve ADB')), \
             patch.object(m, 'collect_mapping', side_effect=AssertionError('must not collect')), \
             patch.object(m, 'canonical_commit', side_effect=AssertionError('must not publish')):
            self.assertEqual(m.main(['--dry-run']), 0)

    def test_private_package_contains_only_filtered_manifest_and_hash_metadata(self):
        report = m._base_report(TEST_TARGET)
        report['mappings'] = [{'path': '/vendor/lib64/camx_core.so', 'pid': 412}]
        package = m.build_evidence_package(report)
        with zipfile.ZipFile(__import__('io').BytesIO(package)) as archive:
            self.assertEqual(archive.namelist(), ['manifest.json'])
            manifest = archive.read('manifest.json').decode('utf-8')
        self.assertIn('/vendor/lib64/camx_core.so', manifest)
        self.assertNotIn('/proc/412/maps', manifest)
        self.assertNotIn(TEST_TARGET, manifest)
        self.assertFalse(report['safety']['mapping_verified'])


if __name__ == '__main__':
    unittest.main()
