"""Synthetic P3-A6 M2.7B provider tests; never invokes ADB or device services."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
import io
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

from pico.tools import p3a_m27b_camx_provider as m


def elf64():
    raw = bytearray(64)
    raw[:6] = b'\x7fELF\x02\x01'
    struct.pack_into('<H', raw, 18, 183)
    return bytes(raw)


def approval(action=m.ACTION, *, issued=None, expires=None, duration=60, observations=200):
    issued = issued or datetime(2026, 10, 19, 12, tzinfo=timezone.utc)
    expires = expires or issued + timedelta(minutes=10)
    return {
        'schema': m.APPROVAL_SCHEMA,
        'approval_id': 'synthetic-m27b-test',
        'device': m.TARGET_DEVICE,
        'approved_actions': [action],
        'issued_at_utc': issued.isoformat(),
        'expires_at_utc': expires.isoformat(),
        'max_duration_seconds': duration,
        'max_observations': observations,
    }


def discovery(paths=()):
    lines = [f'P3A27A\tROOT\t{root}\tSCANNED' for root in m.ROOTS]
    lines.extend(f'P3A27A\tCANDIDATE\t{path}\t{path}' for path in paths)
    return '\n'.join(lines) + '\n'


class CamxProviderOfflineTests(unittest.TestCase):
    def test_discovery_parser_preserves_all_paths_and_root_status(self):
        paths = ['/system/lib64/camx_core.so', '/vendor/lib64/hw/camx_core.so']
        parsed = m.parse_discovery_output(discovery(paths))
        self.assertEqual(parsed['candidates'], [
            {'observed_path': path, 'source_path': path} for path in paths
        ])
        self.assertEqual(set(parsed['root_status']), set(m.ROOTS))
        self.assertEqual(parsed['root_status']['/system'], 'SCANNED')

    def test_discovery_parser_rejects_bad_framing_records_and_paths(self):
        bad_outputs = (
            discovery().replace('\n', '\r', 1),
            discovery().rstrip('\n'),
            discovery().replace('P3A27A\tROOT', 'P3A27A\\tROOT', 1),
            discovery() + 'P3A27A\tOTHER\tvalue\n',
            discovery(['/tmp/camx_core.so']),
            discovery(['/vendor/lib64/../lib64/camx_core.so']),
            discovery(['/vendor/lib/camx_core.so']),
        )
        for raw in bad_outputs:
            with self.subTest(raw=raw[:50]), self.assertRaises(ValueError):
                m.parse_discovery_output(raw)

    def test_discovery_parser_fails_closed_at_candidate_limit(self):
        paths = [f'/vendor/lib64/slot{i}/camx_core.so' for i in range(m.MAX_CANDIDATES + 1)]
        with self.assertRaisesRegex(m.LimitReachedError, 'CANDIDATE_LIMIT'):
            m.parse_discovery_output(discovery(paths))

    def test_discovery_parser_records_safe_symlink_targets_and_limitations(self):
        alias = '/vendor/lib64/camx_core.so'
        target = '/vendor/lib64/libcamx_core.so.1'
        raw = '\n'.join(
            [f'P3A27A\tROOT\t{root}\tSCANNED' for root in m.ROOTS]
            + [f'P3A27A\tCANDIDATE\t{alias}\t{target}',
               f'P3A27A\tCANDIDATE_LIMITATION\t/system/lib64/camx_core.so\tLINK_UNRESOLVED']
        ) + '\n'
        parsed = m.parse_discovery_output(raw)
        self.assertEqual(parsed['candidates'], [{'observed_path': alias, 'source_path': target}])
        self.assertEqual(parsed['candidate_limitations'], [
            {'observed_path': '/system/lib64/camx_core.so', 'code': 'LINK_UNRESOLVED'}
        ])

    def test_sha256_output_is_bound_to_exact_source_path(self):
        path = '/vendor/lib64/camx_core.so'
        digest = 'a' * 64
        self.assertEqual(m.parse_sha256sum(f'{digest}  {path}\n', path), digest)
        for raw in (f'{digest}  /vendor/lib64/other.so\n', f'{digest}\n', f'{digest}  {path}\nextra\n'):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                m.parse_sha256sum(raw, path)

    def test_remote_size_output_is_bound_to_exact_path_and_limits(self):
        path = '/vendor/lib64/camx_core.so'
        self.assertEqual(m.parse_remote_size(f'4096 {path}\n', path), 4096)
        for raw in (f'4096 /vendor/lib64/other.so\n', f'-1 {path}\n',
                    f'not-a-size {path}\n', f'4096 {path}\nextra\n'):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                m.parse_remote_size(raw, path)

    def test_size_allowlist_accepts_only_observed_candidate_source(self):
        selector = m.device_selector(transport_id='42')
        observed = [{'observed_path': '/vendor/lib64/camx_core.so',
                     'source_path': '/vendor/lib64/libcamx_core.so.1'}]
        self.assertTrue(m.allowed_adb_arguments(
            [*selector, 'shell', 'wc', '-c', '/vendor/lib64/libcamx_core.so.1'],
            selector, observed, Path('.')))
        self.assertFalse(m.allowed_adb_arguments(
            [*selector, 'shell', 'wc', '-c', '/system/lib64/other.so'],
            selector, observed, Path('.')))

    def test_native_adb_output_limit_kills_overproducing_client(self):
        class FakeProcess:
            def __init__(self, *args, **kwargs):
                self.stdout = io.BytesIO(b'x' * (m.MAX_OUTPUT_BYTES + 1))
                self.killed = False
            def wait(self, timeout=None):
                return -9 if self.killed else 0
            def kill(self):
                self.killed = True
        with patch.object(m.subprocess, 'Popen', FakeProcess):
            with self.assertRaisesRegex(m.RunnerStop, 'ADB_OUTPUT_LIMIT'):
                m.native_adb_executor(Path('pinned-adb.exe'))(
                    ['get-state'], timeout=1, stage=Path('.'),
                )

    def test_native_adb_timeout_kills_client_and_fails_closed(self):
        class FakeProcess:
            def __init__(self, *args, **kwargs):
                self.stdout = io.BytesIO(b'')
                self.killed = False
                self.wait_count = 0
            def wait(self, timeout=None):
                self.wait_count += 1
                if timeout is not None:
                    raise m.subprocess.TimeoutExpired('adb', timeout)
                return -9
            def kill(self):
                self.killed = True
        process = FakeProcess()
        with patch.object(m.subprocess, 'Popen', return_value=process):
            with self.assertRaisesRegex(m.RunnerStop, 'ADB_TIMEOUT'):
                m.native_adb_executor(Path('pinned-adb.exe'))(
                    ['get-state'], timeout=0.01, stage=Path('.'),
                )
        self.assertTrue(process.killed)

    def test_readelf_metadata_separates_build_id_exports_undefined_and_needed(self):
        output = '''
Displaying notes found in: .note.gnu.build-id
    Build ID: 0123456789abcdef0123456789abcdef01234567
Symbol table '.dynsym' contains 3 entries:
   Num:    Value          Size Type    Bind   Vis      Ndx Name
     1: 0000000000000000 0 FUNC    GLOBAL DEFAULT    12 CSLRegisterMessageHandler
     2: 0000000000000000 0 FUNC    GLOBAL DEFAULT  UND ioctl
     3: 0000000000000000 0 FUNC    LOCAL  DEFAULT     1 local_helper
Dynamic section at offset 0x100 contains 1 entry:
 0x0000000000000001 (NEEDED) Shared library: [libcamx_utils.so]
'''
        metadata = m.parse_readelf_metadata(output)
        self.assertEqual(metadata['build_id'], '0123456789abcdef0123456789abcdef01234567')
        self.assertEqual(metadata['exported_symbols'], ['CSLRegisterMessageHandler'])
        self.assertEqual(metadata['undefined_symbols'], ['ioctl'])
        self.assertEqual(metadata['dt_needed'], ['libcamx_utils.so'])
        self.assertTrue(metadata['dynamic_symbol_table_present'])
        self.assertIn('CSLRegisterMessageHandler', metadata['bridge_symbol_hits'])

    def test_exact_native_allowlist_rejects_unrelated_shell_and_unobserved_path(self):
        selector = m.device_selector(serial='synthetic-pico-serial-01')
        with tempfile.TemporaryDirectory() as td:
            stage = Path(td)
            candidate = '/vendor/lib64/camx_core.so'
            self.assertTrue(m.allowed_adb_arguments(
                [*selector, 'shell', 'sha256sum', candidate], selector, [candidate], stage))
            self.assertFalse(m.allowed_adb_arguments(
                [*selector, 'shell', 'su', '-c', 'id'], selector, [candidate], stage))
            self.assertFalse(m.allowed_adb_arguments(
                [*selector, 'shell', 'sha256sum', '/system/lib64/other.so'], selector, [candidate], stage))
        transport = m.device_selector(transport_id='42')
        self.assertEqual(transport, ['-t', '42'])
        self.assertTrue(m.allowed_adb_arguments([*transport, 'get-state'], transport, (), Path('.')))
        self.assertFalse(m.allowed_adb_arguments(
            ['-s', 'first', '-s', 'second', 'get-state'],
            ['-s', 'first', '-s', 'second'], (), Path('.')))

    def test_transport_id_allowlist_accepts_exact_candidate_vectors_only(self):
        selector = m.device_selector(transport_id='42')
        alias = '/vendor/lib64/camx_core.so'
        source = '/vendor/lib64/libcamx_core.so.1'
        candidates = [{'observed_path': alias, 'source_path': source}]
        with tempfile.TemporaryDirectory() as td:
            stage = Path(td)
            destination = m.destination_for(stage, alias)
            allowed = (
                ['-t', '42', 'get-state'],
                ['-t', '42', 'shell', 'getprop', 'ro.build.fingerprint'],
                ['-t', '42', 'shell', 'sh', '-c', m.SH_DISCOVERY_ARGUMENT],
                ['-t', '42', 'shell', 'readlink', '-f', alias],
                ['-t', '42', 'shell', 'wc', '-c', source],
                ['-t', '42', 'shell', 'sha256sum', source],
                ['-t', '42', 'pull', source, str(destination)],
            )
            for vector in allowed:
                with self.subTest(vector=vector):
                    self.assertTrue(m.allowed_adb_arguments(vector, selector, candidates, stage))
            self.assertFalse(m.allowed_adb_arguments(
                ['-t', '42', 'shell', 'wc', '-c', '/vendor/lib64/unobserved.so'],
                selector, candidates, stage,
            ))

    def test_pinned_sdk_adb_wins_over_path_copies_and_missing_sdk_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            local = Path(td) / 'LocalAppData'
            pinned = local / 'Android' / 'Sdk' / 'platform-tools' / 'adb.exe'
            pinned.parent.mkdir(parents=True)
            pinned.write_bytes(b'synthetic executable placeholder')
            other = Path(td) / 'other' / 'adb.exe'
            other.parent.mkdir()
            other.write_bytes(b'other placeholder')
            env = {'LOCALAPPDATA': str(local), 'PATH': str(other.parent)}
            self.assertEqual(m.resolve_adb_executable(env), pinned.resolve())
            real_resolve = Path.resolve
            def redirect_pinned_path(path, *args, **kwargs):
                if path == pinned:
                    return other
                return real_resolve(path, *args, **kwargs)
            with patch.object(Path, 'resolve', redirect_pinned_path):
                with self.assertRaisesRegex(FileNotFoundError, 'resolves outside'):
                    m.resolve_adb_executable(env)
            with self.assertRaises(FileNotFoundError):
                m.resolve_adb_executable({'LOCALAPPDATA': str(Path(td) / 'missing'), 'PATH': str(other.parent)})

    def test_mocked_collection_extracts_every_candidate_after_identity_and_hash_checks(self):
        paths = ['/system/lib64/camx_core.so', '/vendor/lib64/camx_core.so']
        data = elf64()
        digest = hashlib.sha256(data).hexdigest()
        selector = m.device_selector(serial='synthetic-pico-serial-01')
        calls = []
        metadata = {'build_id': 'ab' * 20, 'exported_symbols': ['CSLRegisterMessageHandler'],
                    'undefined_symbols': ['ioctl'], 'dt_needed': ['libcamx_utils.so'],
                    'bridge_symbol_hits': ['CSLRegisterMessageHandler'],
                    'dynamic_symbol_table_present': True, 'metadata_status': 'OBSERVED'}

        def executor(argv, *, timeout, stage):
            self.assertTrue(m.allowed_adb_arguments(argv, selector, paths, stage), argv)
            calls.append(tuple(argv))
            cmd = argv[len(selector):]
            if cmd == ['get-state']:
                return 'device\n'
            if len(cmd) == 3 and cmd[:2] == ['shell', 'getprop']:
                return m.EXPECTED_PROPERTIES[cmd[2]] + '\n'
            if cmd == ['shell', 'sh', '-c', m.SH_DISCOVERY_ARGUMENT]:
                return discovery(paths)
            if len(cmd) == 4 and cmd[:3] == ['shell', 'wc', '-c']:
                return f'{len(data)} {cmd[3]}\n'
            if len(cmd) == 4 and cmd[:3] == ['shell', 'readlink', '-f']:
                return cmd[3] + '\n'
            if len(cmd) == 3 and cmd[:2] == ['shell', 'sha256sum']:
                return f'{digest}  {cmd[2]}\n'
            if len(cmd) == 3 and cmd[0] == 'pull':
                destination = Path(cmd[2])
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(data)
                return ''
            self.fail(f'unexpected synthetic ADB vector: {argv!r}')

        with tempfile.TemporaryDirectory() as td:
            stage = Path(td)
            with patch.object(m, 'check_hardware_execution_gate', wraps=m.check_hardware_execution_gate) as gate:
                report = m.collect_provider(
                    approval(), 'yes', selector, stage, executor=executor,
                    metadata_reader=lambda path, timeout=20: metadata,
                    direct_user_instruction=True,
                    now_utc_fn=lambda: datetime(2026, 10, 19, 12, 1, tzinfo=timezone.utc),
                    monotonic_fn=lambda: 0.0,
                )
            self.assertEqual(report['status'], 'PACKAGE_READY', report)
            self.assertEqual([f['observed_path'] for f in report['files']], paths)
            self.assertNotIn('synthetic-pico-serial-01', json.dumps(report))
            self.assertEqual([f['sha256'] for f in report['files']], [digest, digest])
            self.assertEqual([f['bytes'] for f in report['files']], [len(data), len(data)])
            self.assertEqual([f['elf']['build_id'] for f in report['files']], ['ab' * 20] * 2)
            self.assertEqual(gate.call_count, len(calls))

    def test_total_size_limit_blocks_all_pulls_before_arbitrary_candidate_selection(self):
        paths = ['/system/lib64/camx_core.so', '/vendor/lib64/camx_core.so',
                 '/odm/lib64/camx_core.so']
        selector = m.device_selector(serial='synthetic-pico-serial-01')
        calls = []
        def executor(argv, *, timeout, stage):
            self.assertTrue(m.allowed_adb_arguments(argv, selector, paths, stage), argv)
            calls.append(tuple(argv))
            cmd = argv[len(selector):]
            if cmd == ['get-state']:
                return 'device\n'
            if len(cmd) == 3 and cmd[:2] == ['shell', 'getprop']:
                return m.EXPECTED_PROPERTIES[cmd[2]] + '\n'
            if cmd == ['shell', 'sh', '-c', m.SH_DISCOVERY_ARGUMENT]:
                return discovery(paths)
            if len(cmd) == 4 and cmd[:3] == ['shell', 'wc', '-c']:
                return f'{48 * 1024 * 1024} {cmd[3]}\n'
            self.fail(f'unexpected synthetic ADB vector: {argv!r}')
        with tempfile.TemporaryDirectory() as td:
            report = m.collect_provider(
                approval(), 'yes', selector, Path(td), executor=executor,
                metadata_reader=lambda path, timeout=20: {}, direct_user_instruction=True,
                now_utc_fn=lambda: datetime(2026, 10, 19, 12, 1, tzinfo=timezone.utc),
                monotonic_fn=lambda: 0.0,
            )
        self.assertEqual(report['status'], 'BLOCKED_LIMIT_REACHED')
        self.assertEqual(report['errors'][-1]['code'], 'TOTAL_PROVIDER_SIZE_LIMIT')
        self.assertFalse(any(call[len(selector)] == 'pull' for call in calls))
        self.assertEqual(report['candidates'], [
            {'observed_path': path, 'source_path': path} for path in paths
        ])

    def test_single_file_size_limit_blocks_pull(self):
        path = '/vendor/lib64/camx_core.so'
        selector = m.device_selector(serial='synthetic-device')
        calls = []
        def executor(argv, *, timeout, stage):
            self.assertTrue(m.allowed_adb_arguments(argv, selector, [path], stage), argv)
            calls.append(tuple(argv))
            cmd = argv[len(selector):]
            if cmd == ['get-state']:
                return 'device\n'
            if len(cmd) == 3 and cmd[:2] == ['shell', 'getprop']:
                return m.EXPECTED_PROPERTIES[cmd[2]] + '\n'
            if cmd == ['shell', 'sh', '-c', m.SH_DISCOVERY_ARGUMENT]:
                return discovery([path])
            if len(cmd) == 4 and cmd[:3] == ['shell', 'wc', '-c']:
                return f'{m.MAX_PROVIDER_FILE_BYTES + 1} {cmd[3]}\n'
            self.fail(f'unexpected synthetic ADB vector: {argv!r}')
        with tempfile.TemporaryDirectory() as td:
            report = m.collect_provider(
                approval(), 'yes', selector, Path(td), executor=executor,
                metadata_reader=lambda candidate, timeout=20: {}, direct_user_instruction=True,
                now_utc_fn=lambda: datetime(2026, 10, 19, 12, 1, tzinfo=timezone.utc),
                monotonic_fn=lambda: 0.0,
            )
        self.assertEqual(report['status'], 'BLOCKED_LIMIT_REACHED')
        self.assertEqual(report['errors'][-1]['code'], 'PROVIDER_FILE_SIZE_LIMIT')
        self.assertFalse(any(call[len(selector)] == 'pull' for call in calls))

    def test_missing_or_invalid_approval_and_confirmation_never_call_executor(self):
        selector = m.device_selector(serial='synthetic-pico-serial-01')
        with tempfile.TemporaryDirectory() as td:
            for approval_obj, confirmation, direct in (
                (None, 'yes', True),
                (approval(action='different-action'), 'yes', True),
                (approval(), 'YES', True),
                (approval(), 'yes', False),
            ):
                calls = []
                report = m.collect_provider(
                    approval_obj, confirmation, selector, Path(td),
                    executor=lambda *a, **k: calls.append(a),
                    metadata_reader=lambda path, timeout=20: {}, direct_user_instruction=direct,
                    now_utc_fn=lambda: datetime(2026, 10, 19, 12, 1, tzinfo=timezone.utc),
                    monotonic_fn=lambda: 0.0,
                )
                self.assertNotEqual(report['status'], 'PACKAGE_READY')
                self.assertEqual(calls, [])

    def test_wrong_firmware_abi_or_product_identity_stops_before_discovery(self):
        for mismatch_key, wrong_value, expected_status in (
            ('ro.build.fingerprint', 'wrong-fingerprint', 'BLOCKED_UNEXPECTED_DEVICE'),
            ('ro.product.cpu.abi', 'armeabi-v7a', 'BLOCKED_ABI_MISMATCH'),
            ('ro.product.device', 'PICOOTHER', 'BLOCKED_UNEXPECTED_DEVICE'),
        ):
            selector = m.device_selector(serial='synthetic-pico-serial-01')
            calls = []
            def executor(argv, *, timeout, stage):
                self.assertTrue(m.allowed_adb_arguments(argv, selector, (), stage), argv)
                calls.append(tuple(argv))
                cmd = argv[len(selector):]
                if cmd == ['get-state']:
                    return 'device\n'
                key = cmd[2]
                value = m.EXPECTED_PROPERTIES[key]
                return (wrong_value if key == mismatch_key else value) + '\n'
            with tempfile.TemporaryDirectory() as td:
                report = m.collect_provider(
                    approval(), 'yes', selector, Path(td), executor=executor,
                    metadata_reader=lambda path, timeout=20: {}, direct_user_instruction=True,
                    now_utc_fn=lambda: datetime(2026, 10, 19, 12, 1, tzinfo=timezone.utc),
                    monotonic_fn=lambda: 0.0,
                )
            self.assertEqual(report['status'], expected_status)
            self.assertFalse(any(call[len(selector):len(selector) + 3] == ('shell', 'sh', '-c')
                                 for call in calls))
            self.assertEqual(len(calls), 1 + len(m.EXPECTED_PROPERTIES))

    def test_expired_approval_mid_run_stops_before_next_adb_command(self):
        selector = m.device_selector(serial='synthetic-pico-serial-01')
        calls = []
        valid_now = datetime(2026, 10, 19, 12, 1, tzinfo=timezone.utc)
        expired_now = datetime(2026, 10, 19, 12, 11, tzinfo=timezone.utc)
        times = iter([valid_now, expired_now])
        def executor(argv, *, timeout, stage):
            self.assertTrue(m.allowed_adb_arguments(argv, selector, (), stage), argv)
            calls.append(tuple(argv))
            return 'device\n'
        with tempfile.TemporaryDirectory() as td:
            report = m.collect_provider(
                approval(), 'yes', selector, Path(td), executor=executor,
                metadata_reader=lambda path, timeout=20: {}, direct_user_instruction=True,
                now_utc_fn=lambda: next(times), monotonic_fn=lambda: 0.0,
            )
        self.assertEqual(report['status'], 'BLOCKED_EXPIRED')
        self.assertEqual(len(calls), 1)

    def test_dry_run_plan_is_device_free(self):
        plan = m.dry_run_plan()
        self.assertEqual(plan['action'], m.ACTION)
        self.assertEqual(plan['discovery_script_sha256'], m.SCRIPT_SHA256)
        self.assertFalse(plan['device_facing_calls_performed'])
        output = io.StringIO()
        with patch.object(m.sys, 'stdout', output), \
             patch.object(m, 'resolve_adb_executable', side_effect=AssertionError('must not resolve ADB')), \
             patch.object(m, 'native_adb_executor', side_effect=AssertionError('must not create ADB executor')):
            self.assertEqual(m.main(['--dry-run']), 0)
        self.assertIn('DRY_RUN_ONLY', output.getvalue())

    def test_cli_requires_interactive_exact_yes_before_resolving_adb(self):
        class InteractiveInput(io.StringIO):
            def isatty(self):
                return True
        class NonInteractiveInput(io.StringIO):
            def isatty(self):
                return False

        for response in ('no', '', 'YES', 'yes '):
            with self.subTest(response=response), \
                 patch.object(m.sys, 'stdin', InteractiveInput()), \
                 patch.object(m, '_load_approval', return_value=approval()), \
                 patch.object(m, 'resolve_adb_executable', side_effect=AssertionError('must not resolve ADB')):
                self.assertEqual(m.main([
                    '--approval-file', 'synthetic-approval.json', '--transport-id', '42',
                ], input_fn=lambda _: response), 2)

        with patch.object(m.sys, 'stdin', NonInteractiveInput()), \
             patch.object(m, '_load_approval', return_value=approval()), \
             patch.object(m, 'resolve_adb_executable', side_effect=AssertionError('must not resolve ADB')):
            self.assertEqual(m.main([
                '--approval-file', 'synthetic-approval.json', '--transport-id', '42',
            ], input_fn=lambda _: 'yes'), 2)

        blocked_report = {'status': 'PACKAGE_READY'}
        with patch.object(m.sys, 'stdin', InteractiveInput()), \
             patch.object(m, '_load_approval', return_value=approval()), \
             patch.object(m, 'resolve_adb_executable', return_value=Path('pinned-adb.exe')), \
             patch.object(m, 'collect_provider', return_value=blocked_report) as collect, \
             patch.object(m, 'build_zip', return_value=b'synthetic package'), \
             patch.object(m, 'canonical_commit', return_value={'status': 'PACKAGE_READY'}):
            self.assertEqual(m.main([
                '--approval-file', 'synthetic-approval.json', '--transport-id', '42',
            ], input_fn=lambda _: 'yes'), 0)
            self.assertEqual(collect.call_count, 1)


if __name__ == '__main__':
    unittest.main()
