"""Synthetic P3-A6 M2.7B provider tests; never invokes ADB or device services."""
import hashlib
import io
import os
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

from pico.tools import p3a_m27b_camx_provider as m


TEST_TARGET = 'm27b-test.invalid:5555'


def elf64():
    raw = bytearray(64)
    raw[:6] = b'\x7fELF\x02\x01'
    struct.pack_into('<H', raw, 18, 183)
    return bytes(raw)


def discovery(paths=()):
    lines = [f'P3A27A\tROOT\t{root}\tSCANNED' for root in m.ROOTS]
    lines.extend(f'P3A27A\tCANDIDATE\t{path}\t{path}' for path in paths)
    return '\n'.join(lines) + '\n'


class CamxProviderOfflineTests(unittest.TestCase):
    def setUp(self):
        self.target_env = patch.dict(os.environ, {m.TARGET_SERIAL_ENV: TEST_TARGET})
        self.target_env.start()
        self.target_hash = patch.object(
            m, 'TARGET_SERIAL_SHA256', hashlib.sha256(TEST_TARGET.encode('utf-8')).hexdigest(),
        )
        self.target_hash.start()

    def tearDown(self):
        self.target_hash.stop()
        self.target_env.stop()

    def test_owner_authorized_target_and_connect_are_exactly_pinned(self):
        selector = m.device_selector()
        self.assertEqual(selector, ['-s', TEST_TARGET])
        self.assertTrue(m.allowed_adb_arguments(
            ['connect', TEST_TARGET], selector, (), Path('.')))
        self.assertFalse(m.allowed_adb_arguments(
            ['connect', 'other-m27b-test.invalid:5555'], selector, (), Path('.')))
        self.assertFalse(m.allowed_adb_arguments(
            ['connect', TEST_TARGET, 'other'], selector, (), Path('.')))
        self.assertTrue(m.allowed_adb_arguments(
            [*selector, 'get-state'], selector, (), Path('.')))
        self.assertFalse(m.allowed_adb_arguments(
            ['-s', 'another-target:5555', 'get-state'],
            ['-s', 'another-target:5555'], (), Path('.')))

    def test_owner_authorized_collection_connects_then_checks_state_and_identity(self):
        selector = m.device_selector()
        calls = []

        def executor(argv, *, timeout, stage):
            self.assertTrue(m.allowed_adb_arguments(argv, selector, (), stage), argv)
            calls.append(tuple(argv))
            if argv == ['connect', TEST_TARGET]:
                return f'connected to {TEST_TARGET}\n'
            cmd = argv[len(selector):]
            if cmd == ['get-state']:
                return 'device\n'
            if len(cmd) == 3 and cmd[:2] == ['shell', 'getprop']:
                return m.EXPECTED_PROPERTIES[cmd[2]] + '\n'
            if cmd == ['shell', 'sh', '-c', m.SH_DISCOVERY_ARGUMENT]:
                return discovery()
            self.fail(f'unexpected synthetic ADB vector: {argv!r}')

        with tempfile.TemporaryDirectory() as td:
            report = m.collect_provider(
                selector, Path(td), executor=executor,
                metadata_reader=lambda path, timeout=20: {},
                owner_authorized=True,
                monotonic_fn=lambda: 0.0,
            )

        self.assertEqual(report['status'], 'BLOCKED_NO_PROVIDER')
        self.assertEqual(report['authorization_mode'], 'OWNER_AUTHORIZED_DIRECT_INSTRUCTION')
        self.assertEqual(report['target_serial'], TEST_TARGET)
        self.assertEqual(report['connection_status'], 'CONNECTED')
        self.assertEqual(calls[:2], [
            ('connect', TEST_TARGET), (*selector, 'get-state'),
        ])
        self.assertEqual(report['adb_command_count'], len(calls))

    def test_owner_authorized_cli_needs_no_approval_tty_or_confirmation_token(self):
        class NonInteractiveInput(io.StringIO):
            def isatty(self):
                return False

        captured = {}
        report = {'status': 'BLOCKED_NO_PROVIDER'}

        def collect(selector, stage, **kwargs):
            captured['selector'] = selector
            captured['stage'] = stage
            captured.update(kwargs)
            return report

        with patch.object(m.sys, 'stdin', NonInteractiveInput()), \
             patch.object(m, 'resolve_adb_executable', return_value=Path('pinned-adb.exe')) as resolve, \
             patch.object(m, 'collect_provider', side_effect=collect) as collect_mock, \
             patch.object(m, 'build_zip', return_value=b'synthetic package'), \
             patch.object(m, 'canonical_commit', return_value={'status': 'BLOCKED_NO_PROVIDER'}):
            self.assertEqual(m.main(['--owner-authorized-run']), 1)

        resolve.assert_called_once_with()
        collect_mock.assert_called_once()
        self.assertEqual(captured['selector'], ['-s', TEST_TARGET])
        self.assertIs(captured['owner_authorized'], True)
        self.assertNotIn('approval', captured)
        self.assertNotIn('confirmation_response', captured)

    def test_unattended_mode_rejects_missing_mode_without_resolving_adb(self):
        with patch.object(m, 'resolve_adb_executable', side_effect=AssertionError('must not resolve ADB')):
            self.assertEqual(m.main([]), 2)

    def test_cli_rejects_user_selected_serial_transport_and_approval_files(self):
        for arguments in (
            ['--owner-authorized-run', '--serial', TEST_TARGET],
            ['--owner-authorized-run', '--transport-id', '42'],
            ['--owner-authorized-run', '--approval-file', 'not-read.json'],
        ):
            with self.subTest(arguments=arguments), \
                 patch.object(m, 'resolve_adb_executable', side_effect=AssertionError('must not resolve ADB')):
                with self.assertRaises(SystemExit) as raised:
                    m.main(arguments)
                self.assertEqual(raised.exception.code, 2)

    def test_connect_output_must_confirm_exact_target(self):
        self.assertEqual(
            m.parse_connect_output(f'connected to {TEST_TARGET}\r\n'),
            'CONNECTED',
        )
        self.assertEqual(
            m.parse_connect_output(f'already connected to {TEST_TARGET}\n'),
            'ALREADY_CONNECTED',
        )
        for raw in ('connected to other-m27b-test.invalid:5555\n', 'failed to connect\n',
                    f'connected to {TEST_TARGET}\nextra\n'):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                m.parse_connect_output(raw)
        with self.assertRaisesRegex(ValueError, 'ADB_CONNECT_AUTHENTICATION_FAILED'):
            m.parse_connect_output(f'failed to authenticate to {TEST_TARGET}\n')
        with self.assertRaisesRegex(ValueError, 'ADB_CONNECT_FAILED'):
            m.parse_connect_output(f'failed to connect to {TEST_TARGET}\n')
        with self.assertRaisesRegex(ValueError, 'ADB_CONNECT_REFUSED'):
            m.parse_connect_output(
                f'cannot connect to {TEST_TARGET}: No connection could be made because the target machine actively refused it. (10061)\n',
            )

    def test_connect_diagnostic_redacts_target_and_bounds_output(self):
        preview = m.redacted_connect_output_preview(
            f'connected to {TEST_TARGET} extra other-m27b-test.invalid:5555\n' + ('x' * 500),
            TEST_TARGET,
        )
        self.assertNotIn(TEST_TARGET, preview)
        self.assertNotIn('other-m27b-test.invalid:5555', preview)
        self.assertLessEqual(len(preview), 256)

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
        selector = m.device_selector()
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
        selector = m.device_selector()
        with tempfile.TemporaryDirectory() as td:
            stage = Path(td)
            candidate = '/vendor/lib64/camx_core.so'
            self.assertTrue(m.allowed_adb_arguments(
                [*selector, 'shell', 'sha256sum', candidate], selector, [candidate], stage))
            self.assertFalse(m.allowed_adb_arguments(
                [*selector, 'shell', 'su', '-c', 'id'], selector, [candidate], stage))
            self.assertFalse(m.allowed_adb_arguments(
                [*selector, 'shell', 'sha256sum', '/system/lib64/other.so'], selector, [candidate], stage))
        self.assertFalse(m.allowed_adb_arguments(
            ['-t', '42', 'get-state'], ['-t', '42'], (), Path('.')))
        self.assertFalse(m.allowed_adb_arguments(
            ['-s', 'other-m27b-test.invalid:5555', 'get-state'],
            ['-s', 'other-m27b-test.invalid:5555'], (), Path('.')))

    def test_fixed_serial_allowlist_accepts_exact_candidate_vectors_only(self):
        selector = m.device_selector()
        alias = '/vendor/lib64/camx_core.so'
        source = '/vendor/lib64/libcamx_core.so.1'
        candidates = [{'observed_path': alias, 'source_path': source}]
        with tempfile.TemporaryDirectory() as td:
            stage = Path(td)
            destination = m.destination_for(stage, alias)
            allowed = (
                ['connect', TEST_TARGET],
                [*selector, 'get-state'],
                [*selector, 'shell', 'getprop', 'ro.build.fingerprint'],
                [*selector, 'shell', 'sh', '-c', m.SH_DISCOVERY_ARGUMENT],
                [*selector, 'shell', 'readlink', '-f', alias],
                [*selector, 'shell', 'wc', '-c', source],
                [*selector, 'shell', 'sha256sum', source],
                [*selector, 'pull', source, str(destination)],
            )
            for vector in allowed:
                with self.subTest(vector=vector):
                    self.assertTrue(m.allowed_adb_arguments(vector, selector, candidates, stage))
            self.assertFalse(m.allowed_adb_arguments(
                [*selector, 'shell', 'wc', '-c', '/vendor/lib64/unobserved.so'],
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
        selector = m.device_selector()
        calls = []
        metadata = {'build_id': 'ab' * 20, 'exported_symbols': ['CSLRegisterMessageHandler'],
                    'undefined_symbols': ['ioctl'], 'dt_needed': ['libcamx_utils.so'],
                    'bridge_symbol_hits': ['CSLRegisterMessageHandler'],
                    'dynamic_symbol_table_present': True, 'metadata_status': 'OBSERVED'}

        def executor(argv, *, timeout, stage):
            self.assertTrue(m.allowed_adb_arguments(argv, selector, paths, stage), argv)
            calls.append(tuple(argv))
            if argv == ['connect', TEST_TARGET]:
                return f'connected to {TEST_TARGET}\n'
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
            report = m.collect_provider(
                selector, stage, executor=executor,
                metadata_reader=lambda path, timeout=20: metadata,
                owner_authorized=True, monotonic_fn=lambda: 0.0,
            )
            self.assertEqual(report['status'], 'PACKAGE_READY', report)
            self.assertEqual([f['observed_path'] for f in report['files']], paths)
            self.assertEqual(report['target_serial'], TEST_TARGET)
            self.assertEqual([f['sha256'] for f in report['files']], [digest, digest])
            self.assertEqual([f['bytes'] for f in report['files']], [len(data), len(data)])
            self.assertEqual([f['elf']['build_id'] for f in report['files']], ['ab' * 20] * 2)
            self.assertEqual(report['adb_command_count'], len(calls))

    def test_total_size_limit_blocks_all_pulls_before_arbitrary_candidate_selection(self):
        paths = ['/system/lib64/camx_core.so', '/vendor/lib64/camx_core.so',
                 '/odm/lib64/camx_core.so']
        selector = m.device_selector()
        calls = []
        def executor(argv, *, timeout, stage):
            self.assertTrue(m.allowed_adb_arguments(argv, selector, paths, stage), argv)
            calls.append(tuple(argv))
            if argv == ['connect', TEST_TARGET]:
                return f'connected to {TEST_TARGET}\n'
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
                selector, Path(td), executor=executor,
                metadata_reader=lambda path, timeout=20: {}, owner_authorized=True,
                monotonic_fn=lambda: 0.0,
            )
        self.assertEqual(report['status'], 'BLOCKED_LIMIT_REACHED')
        self.assertEqual(report['errors'][-1]['code'], 'TOTAL_PROVIDER_SIZE_LIMIT')
        self.assertFalse(any(call[:len(selector)] == tuple(selector)
                             and call[len(selector)] == 'pull' for call in calls))
        self.assertEqual(report['candidates'], [
            {'observed_path': path, 'source_path': path} for path in paths
        ])

    def test_single_file_size_limit_blocks_pull(self):
        path = '/vendor/lib64/camx_core.so'
        selector = m.device_selector()
        calls = []
        def executor(argv, *, timeout, stage):
            self.assertTrue(m.allowed_adb_arguments(argv, selector, [path], stage), argv)
            calls.append(tuple(argv))
            if argv == ['connect', TEST_TARGET]:
                return f'connected to {TEST_TARGET}\n'
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
                selector, Path(td), executor=executor,
                metadata_reader=lambda candidate, timeout=20: {}, owner_authorized=True,
                monotonic_fn=lambda: 0.0,
            )
        self.assertEqual(report['status'], 'BLOCKED_LIMIT_REACHED')
        self.assertEqual(report['errors'][-1]['code'], 'PROVIDER_FILE_SIZE_LIMIT')
        self.assertFalse(any(call[:len(selector)] == tuple(selector)
                             and call[len(selector)] == 'pull' for call in calls))

    def test_missing_owner_authorization_or_wrong_target_never_calls_executor(self):
        selector = m.device_selector()
        with tempfile.TemporaryDirectory() as td:
            for selected, authorized in (
                (selector, False),
                (['-s', 'other-m27b-test.invalid:5555'], True),
                (['-t', '42'], True),
            ):
                calls = []
                report = m.collect_provider(
                    selected, Path(td),
                    executor=lambda *a, **k: calls.append(a),
                    metadata_reader=lambda path, timeout=20: {}, owner_authorized=authorized,
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
            selector = m.device_selector()
            calls = []
            def executor(argv, *, timeout, stage):
                self.assertTrue(m.allowed_adb_arguments(argv, selector, (), stage), argv)
                calls.append(tuple(argv))
                if argv == ['connect', TEST_TARGET]:
                    return f'connected to {TEST_TARGET}\n'
                cmd = argv[len(selector):]
                if cmd == ['get-state']:
                    return 'device\n'
                key = cmd[2]
                value = m.EXPECTED_PROPERTIES[key]
                return (wrong_value if key == mismatch_key else value) + '\n'
            with tempfile.TemporaryDirectory() as td:
                report = m.collect_provider(
                    selector, Path(td), executor=executor,
                    metadata_reader=lambda path, timeout=20: {}, owner_authorized=True,
                    monotonic_fn=lambda: 0.0,
                )
            self.assertEqual(report['status'], expected_status)
            self.assertFalse(any(call[len(selector):len(selector) + 3] == ('shell', 'sh', '-c')
                                 for call in calls))
            self.assertEqual(len(calls), 2 + len(m.EXPECTED_PROPERTIES))

    def test_collection_rejects_unexpected_connect_output_before_target_selection(self):
        selector = m.device_selector()
        calls = []
        def executor(argv, *, timeout, stage):
            self.assertTrue(m.allowed_adb_arguments(argv, selector, (), stage), argv)
            calls.append(tuple(argv))
            return 'connected to other-m27b-test.invalid:5555\n'
        with tempfile.TemporaryDirectory() as td:
            report = m.collect_provider(
                selector, Path(td), executor=executor,
                metadata_reader=lambda path, timeout=20: {}, owner_authorized=True,
                monotonic_fn=lambda: 0.0,
            )
        self.assertEqual(report['status'], 'BLOCKED_CONNECT_OUTPUT')
        self.assertEqual(report['errors'][-1]['code'], 'ADB_CONNECT_OUTPUT_UNEXPECTED')
        self.assertEqual(report['connection_diagnostic']['raw_output_saved'], False)
        self.assertEqual(calls, [('connect', TEST_TARGET)])

    def test_collection_classifies_refused_tcp_before_any_device_command(self):
        selector = m.device_selector()
        calls = []
        def executor(argv, *, timeout, stage):
            self.assertTrue(m.allowed_adb_arguments(argv, selector, (), stage), argv)
            calls.append(tuple(argv))
            return (
                f'cannot connect to {TEST_TARGET}: No connection could be made because '
                'the target machine actively refused it. (10061)\n'
            )
        with tempfile.TemporaryDirectory() as td:
            report = m.collect_provider(
                selector, Path(td), executor=executor,
                metadata_reader=lambda path, timeout=20: {}, owner_authorized=True,
                monotonic_fn=lambda: 0.0,
            )
        self.assertEqual(report['status'], 'BLOCKED_ADB_CONNECT_REFUSED')
        self.assertEqual(report['errors'][-1]['code'], 'ADB_CONNECT_REFUSED')
        self.assertNotIn(TEST_TARGET, report['connection_diagnostic']['redacted_preview'])
        self.assertEqual(calls, [('connect', TEST_TARGET)])

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

if __name__ == '__main__':
    unittest.main()
