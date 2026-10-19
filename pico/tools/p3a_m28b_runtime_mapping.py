"""M2.8B: bounded read-only mapping inventory for already-running Pico processes.

Default mode is device-free. The explicit owner-authorized mode uses the
pinned Android SDK ADB executable, a fixed target binding, an exact argument
allowlist, and one fixed POSIX probe. It never opens a camera or reads mapped
memory, descriptors, process environment, or complete process/maps output.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile
import time
import zipfile
from typing import Any, Callable, Mapping
from uuid import uuid4

if __package__:
    from . import p3a_m27b_camx_provider as m27b
    from .p3a_collect_producers import canonical_commit
    from .p3a_quickcamera_inventory import ROOT
else:
    import p3a_m27b_camx_provider as m27b
    from p3a_collect_producers import canonical_commit
    from p3a_quickcamera_inventory import ROOT


ACTION = 'read-only-runtime-provider-mapping'
SCHEMA = 'p3a.m28b.runtime_provider_mapping.v1'
COLLECTOR_REVISION = 'P3-A6-M2.8B-v1'
TARGET_DEVICE = 'Pico 4 Pro'
TARGET_SERIAL_ENV = m27b.TARGET_SERIAL_ENV
TARGET_FINGERPRINT = m27b.TARGET_FINGERPRINT
TARGET_ABI = m27b.TARGET_ABI
MAX_DURATION_SECONDS = 15
MAX_OBSERVATIONS = 40
MAX_ADB_COMMANDS = 5
MAX_ADB_OUTPUT_BYTES = 64 * 1024
MAX_SINGLE_COMMAND_SECONDS = 6
MAX_PROCESSES = 40
EXPECTED_LIBRARIES = (
    '/vendor/lib64/camx_core.so',
    '/vendor/lib64/quickcamera.core.so',
)
PROCESS_NAME_PATTERN = r'(quickcamera|pvr|hidl.*camera|camera.*hidl)'
SAFETY = {
    'observe_only': True,
    'exact_time': False,
    'mapping_verified': False,
    'pose_verified': False,
    'shared_buffer_identity_verified': False,
    'frame_meta_bridge_verified': False,
    'physical_event_verified': False,
    'live_lighthouse_correction_allowed': False,
}


def _load_probe_script() -> str:
    source = Path(__file__).with_name('p3a_m28b_runtime_probe.sh').read_bytes()
    normalized = source.replace(b'\r\n', b'\n')
    if b'\r' in normalized:
        raise RuntimeError('PROBE_SCRIPT_HAS_STANDALONE_CR')
    return normalized.decode('ascii', errors='strict')


def render_probe_script_for_fixture(proc_root: str) -> str:
    """Test-only /tmp fixture renderer; the native allowlist accepts PROBE_SCRIPT only."""
    if not re.fullmatch(r'/tmp/p3a-m28b-[a-f0-9]{32}/proc', proc_root):
        raise ValueError('UNAPPROVED_PROC_ROOT')
    return PROBE_SCRIPT.replace("PROC_ROOT='/proc'", f"PROC_ROOT='{proc_root}'", 1)


PROBE_SCRIPT = _load_probe_script()
PROBE_ARGUMENT = shlex.quote(PROBE_SCRIPT)
PROBE_SHA256 = hashlib.sha256(PROBE_SCRIPT.encode('ascii')).hexdigest()


class RunnerStop(RuntimeError):
    def __init__(self, status: str, code: str):
        super().__init__(code)
        self.status = status
        self.code = code


def _uint(value: str, *, maximum: int = (1 << 64) - 1, allow_zero: bool = True) -> int:
    if not isinstance(value, str) or not re.fullmatch(r'[0-9]{1,20}', value):
        raise ValueError('INVALID_NUMERIC_FIELD')
    parsed = int(value, 10)
    if parsed > maximum or (not allow_zero and parsed == 0):
        raise ValueError('INVALID_NUMERIC_FIELD')
    return parsed


def _protocol_lines(raw: str) -> list[str]:
    try:
        encoded_length = len(raw.encode('utf-8', errors='strict')) if isinstance(raw, str) else 0
    except UnicodeError as exc:
        raise ValueError('OUTPUT_FRAMING') from exc
    if not isinstance(raw, str) or not raw or encoded_length > MAX_ADB_OUTPUT_BYTES:
        raise ValueError('OUTPUT_FRAMING')
    normalized = raw.replace('\r\n', '\n')
    if '\r' in normalized or not normalized.endswith('\n'):
        raise ValueError('OUTPUT_FRAMING')
    lines = normalized[:-1].split('\n')
    if any(not line or any((ord(ch) < 0x20 and ch != '\t') or ord(ch) > 0x7e for ch in line)
           for line in lines):
        raise ValueError('OUTPUT_FRAMING')
    return lines


def _validate_process_name(name: str) -> bool:
    return (isinstance(name, str) and len(name) <= 256
            and re.fullmatch(r'[A-Za-z0-9_.:@+-]{1,256}', name) is not None
            and re.search(PROCESS_NAME_PATTERN, name, re.IGNORECASE) is not None)


def parse_probe_output(raw: str) -> dict[str, Any]:
    lines = _protocol_lines(raw)
    if len(lines) < 2 or lines[0] != 'P3A28B\tBEGIN\t1':
        raise ValueError('OUTPUT_FRAMING')
    if not lines[-1].startswith('P3A28B\tEND\t'):
        raise ValueError('OUTPUT_FRAMING')

    mappings: list[dict[str, Any]] = []
    process_statuses: list[dict[str, Any]] = []
    fs_stats: dict[str, dict[str, Any]] = {}
    global_status: str | None = None
    seen_pids: set[int] = set()
    duplicate_maps: set[tuple[Any, ...]] = set()
    codes = {
        'NO_TARGET_MAPPING', 'MAPPED', 'PROC_ACCESS_DENIED', 'PROCESS_EXITED',
        'PID_REUSED', 'PROCESS_IDENTITY_CHANGED', 'PROCESS_IDENTITY_UNAVAILABLE',
        'PROC_MAPS_UNAVAILABLE', 'MALFORMED_MAPS', 'RECORD_LIMIT_REACHED',
    }
    for line in lines[1:-1]:
        fields = line.split('\t')
        if len(fields) == 6 and fields[:2] == ['P3A28B', 'PROCESS_STATUS']:
            _, _, pid_text, name, start_text, code = fields
            pid = _uint(pid_text, maximum=2_147_483_647, allow_zero=False)
            if not _validate_process_name(name) or code not in codes or pid in seen_pids:
                raise ValueError('INVALID_PROCESS_RECORD')
            seen_pids.add(pid)
            if start_text == 'NOT_OBSERVED':
                if code not in ('PROCESS_EXITED', 'PROCESS_IDENTITY_UNAVAILABLE'):
                    raise ValueError('INVALID_PROCESS_RECORD')
                start = None
            else:
                start = _uint(start_text, allow_zero=False)
            process_statuses.append({'pid': pid, 'process_name': name, 'starttime': start, 'status': code})
        elif len(fields) == 11 and fields[:2] == ['P3A28B', 'MAP']:
            _, _, pid_text, name, start_text, address_range, permissions, offset, device, inode_text, path = fields
            pid = _uint(pid_text, maximum=2_147_483_647, allow_zero=False)
            starttime = _uint(start_text, allow_zero=False)
            if not _validate_process_name(name):
                raise ValueError('INVALID_PROCESS_RECORD')
            match = re.fullmatch(r'([0-9a-fA-F]{1,16})-([0-9a-fA-F]{1,16})', address_range)
            if not match:
                raise ValueError('INVALID_MAP_RANGE')
            address_start, address_end = (int(part, 16) for part in match.groups())
            if address_start >= address_end:
                raise ValueError('INVALID_MAP_RANGE')
            if not re.fullmatch(r'[r-][w-][x-][ps]', permissions):
                raise ValueError('INVALID_MAP_PERMISSIONS')
            if not re.fullmatch(r'[0-9a-fA-F]{1,16}', offset):
                raise ValueError('INVALID_MAP_OFFSET')
            match_dev = re.fullmatch(r'([0-9a-fA-F]{1,8}):([0-9a-fA-F]{1,8})', device)
            if not match_dev:
                raise ValueError('INVALID_MAP_DEVICE')
            inode = _uint(inode_text, allow_zero=False)
            deleted = path.endswith(' (deleted)')
            clean_path = path[:-10] if deleted else path
            if clean_path not in EXPECTED_LIBRARIES:
                raise ValueError('UNEXPECTED_MAP_PATH')
            item = {
                'pid': pid, 'process_name': name, 'starttime': starttime,
                'address_range': address_range.lower(), 'permissions': permissions,
                'offset': offset.lower(), 'device': device.lower(),
                'device_major': int(match_dev.group(1), 16),
                'device_minor': int(match_dev.group(2), 16),
                'inode': inode, 'path': clean_path, 'deleted': deleted,
            }
            key = tuple(item[k] for k in (
                'pid', 'starttime', 'address_range', 'permissions', 'offset',
                'device', 'inode', 'path', 'deleted',
            ))
            if key in duplicate_maps:
                raise ValueError('DUPLICATE_MAP_RECORD')
            duplicate_maps.add(key)
            mappings.append(item)
        elif len(fields) == 6 and fields[:2] == ['P3A28B', 'FSSTAT']:
            _, _, path, state, device_text, inode_text = fields
            if path not in EXPECTED_LIBRARIES or path in fs_stats:
                raise ValueError('INVALID_FSSTAT_PATH')
            if state != 'OBSERVED':
                raise ValueError('INVALID_FSSTAT_RECORD')
            device = _uint(device_text)
            inode = _uint(inode_text, allow_zero=False)
            fs_stats[path] = {'status': state, 'device': device, 'inode': inode}
        elif len(fields) == 5 and fields[:2] == ['P3A28B', 'FSSTAT']:
            _, _, path, state, code = fields
            if (path not in EXPECTED_LIBRARIES or path in fs_stats
                    or state != 'UNAVAILABLE' or code != 'STAT_UNAVAILABLE'):
                raise ValueError('INVALID_FSSTAT_RECORD')
            fs_stats[path] = {'status': state, 'reason_code': code}
        elif len(fields) == 3 and fields[:2] == ['P3A28B', 'GLOBAL_STATUS']:
            if global_status is not None or fields[2] not in (
                    'PROCESS_INVENTORY_UNAVAILABLE', 'PROCESS_INVENTORY_MALFORMED',
                    'PROCESS_LIMIT_REACHED', 'NO_MATCHING_PROCESSES'):
                raise ValueError('INVALID_GLOBAL_STATUS')
            global_status = fields[2]
        else:
            raise ValueError('UNEXPECTED_RECORD')

    end = lines[-1].split('\t')
    if len(end) != 4 or end[:2] != ['P3A28B', 'END']:
        raise ValueError('OUTPUT_FRAMING')
    count = _uint(end[2])
    status = end[3]
    if status not in (
            'COMPLETE', 'LIMIT_REACHED', 'BLOCKED_PROCESS_INVENTORY',
            'NO_MATCHING_PROCESSES', 'PROCESS_LIMIT_REACHED',
            'PROCESS_EXITED', 'PID_REUSED', 'PROCESS_IDENTITY_CHANGED',
            'PROCESS_IDENTITY_UNAVAILABLE', 'PROC_ACCESS_DENIED', 'PROC_MAPS_UNAVAILABLE',
            'MALFORMED_MAPS',
            'NO_TARGET_MAPPING'):
        raise ValueError('INVALID_END_STATUS')
    normalized_count = len(mappings) + len(process_statuses) + len(fs_stats) + int(global_status is not None)
    if count != normalized_count:
        raise ValueError('RECORD_COUNT_MISMATCH')
    if count > MAX_OBSERVATIONS:
        raise ValueError('OBSERVATION_LIMIT')
    if status == 'NO_MATCHING_PROCESSES' and global_status != 'NO_MATCHING_PROCESSES':
        raise ValueError('GLOBAL_STATUS_MISMATCH')
    if status == 'PROCESS_LIMIT_REACHED' and global_status != 'PROCESS_LIMIT_REACHED':
        raise ValueError('GLOBAL_STATUS_MISMATCH')
    process_by_pid = {item['pid']: item for item in process_statuses}
    for mapping in mappings:
        process = process_by_pid.get(mapping['pid'])
        if (process is None or process['status'] != 'MAPPED'
                or process['process_name'] != mapping['process_name']
                or process['starttime'] != mapping['starttime']):
            raise ValueError('MAP_PROCESS_IDENTITY_MISMATCH')
    map_pids = {mapping['pid'] for mapping in mappings}
    if any((item['status'] == 'MAPPED') != (item['pid'] in map_pids)
           for item in process_statuses):
        raise ValueError('PROCESS_MAP_STATUS_MISMATCH')
    return {
        'mappings': mappings,
        'process_statuses': process_statuses,
        'filesystem_stats': fs_stats,
        'global_status': global_status,
        'scan_status': status,
        'record_count': count,
        'raw_process_table_saved': False,
        'raw_maps_saved': False,
    }


def _stat_device_matches(map_record: Mapping[str, Any], fsstat: Mapping[str, Any]) -> bool:
    if fsstat.get('status') != 'OBSERVED':
        return False
    try:
        stat_device = int(fsstat['device'])
        return (_linux_major(stat_device) == map_record['device_major']
                and _linux_minor(stat_device) == map_record['device_minor']
                and int(fsstat['inode']) == map_record['inode'])
    except (AttributeError, OverflowError, ValueError, TypeError):
        return False


def _linux_major(device: int) -> int:
    return ((device >> 8) & 0xFFF) | ((device >> 32) & ~0xFFF)


def _linux_minor(device: int) -> int:
    return (device & 0xFF) | ((device >> 12) & ~0xFF)


def evaluate_mapping_result(parsed: Mapping[str, Any]) -> dict[str, Any]:
    statuses = list(parsed.get('process_statuses', []))
    mappings = list(parsed.get('mappings', []))
    terminal = parsed.get('scan_status')
    blocking_codes = {
        'PROC_ACCESS_DENIED', 'PROCESS_EXITED', 'PID_REUSED',
        'PROCESS_IDENTITY_CHANGED', 'PROCESS_IDENTITY_UNAVAILABLE',
        'PROC_MAPS_UNAVAILABLE', 'MALFORMED_MAPS', 'RECORD_LIMIT_REACHED',
    }
    stop_reason = next((item['status'] for item in statuses if item['status'] in blocking_codes), None)
    if stop_reason is None and terminal in blocking_codes:
        stop_reason = terminal
    if stop_reason or parsed.get('global_status') in (
            'PROCESS_INVENTORY_UNAVAILABLE', 'PROCESS_INVENTORY_MALFORMED',
            'PROCESS_LIMIT_REACHED', 'NO_MATCHING_PROCESSES'):
        return {
            'status': 'BLOCKED',
            'stop_reason': stop_reason or parsed.get('global_status') or terminal,
            'provider_mapping_count': sum(m['path'] == EXPECTED_LIBRARIES[0] and not m['deleted'] for m in mappings),
            'quickcamera_mapping_count': sum(m['path'] == EXPECTED_LIBRARIES[1] and not m['deleted'] for m in mappings),
            'device_inode_match': False,
            'quickcamera_device_inode_match': False,
        }

    camx = [item for item in mappings if item['path'] == EXPECTED_LIBRARIES[0] and not item['deleted']]
    quick = [item for item in mappings if item['path'] == EXPECTED_LIBRARIES[1] and not item['deleted']]
    deleted_camx = any(item['path'] == EXPECTED_LIBRARIES[0] and item['deleted'] for item in mappings)
    stats = parsed.get('filesystem_stats', {})
    camx_matches = [item for item in camx if _stat_device_matches(item, stats.get(EXPECTED_LIBRARIES[0], {}))]
    quick_matches = [item for item in quick if _stat_device_matches(item, stats.get(EXPECTED_LIBRARIES[1], {}))]
    same_process_pairs = [
        (provider, companion) for provider in camx for companion in quick
        if provider['pid'] == companion['pid']
        and provider['starttime'] == companion['starttime']
        and re.search(r'quickcamera', provider['process_name'], re.IGNORECASE)
    ]
    corroborated_pairs = [
        (provider, companion) for provider, companion in same_process_pairs
        if _stat_device_matches(provider, stats.get(EXPECTED_LIBRARIES[0], {}))
    ]
    if corroborated_pairs:
        status = 'PASS'
    elif camx or deleted_camx:
        status = 'PARTIAL'
    else:
        status = 'BLOCKED'
    return {
        'status': status,
        'stop_reason': None if status != 'BLOCKED' else (terminal or 'NO_TARGET_MAPPING'),
        'provider_mapping_count': len(camx),
        'quickcamera_mapping_count': len(quick),
        'same_quickcamera_process_pair_count': len(same_process_pairs),
        'device_inode_match': bool(camx_matches),
        'quickcamera_device_inode_match': bool(quick_matches),
        'confirmed_processes': sorted({
            (item['pid'], item['process_name'], item['starttime'])
            for item in mappings if item['path'] in EXPECTED_LIBRARIES and not item['deleted']
        }),
    }


def allowed_adb_arguments(arguments: list[str] | tuple[str, ...],
                          selector: list[str] | tuple[str, ...]) -> bool:
    try:
        target = m27b.owner_authorized_target_serial()
    except (ValueError, OSError):
        return False
    if list(selector) != ['-s', target]:
        return False
    argv = list(arguments)
    if argv == ['connect', target]:
        return True
    if argv[:2] != ['-s', target]:
        return False
    command = argv[2:]
    return command in (
        ['get-state'],
        ['shell', 'getprop', 'ro.build.fingerprint'],
        ['shell', 'getprop', 'ro.product.cpu.abi'],
        ['shell', 'sh', '-c', PROBE_ARGUMENT],
    )


def _single_value(raw: str) -> str:
    try:
        return m27b.parse_single_value(raw)
    except ValueError as exc:
        raise RunnerStop('BLOCKED_ADB_OUTPUT', str(exc)) from exc


def _parse_connect(raw: str, target: str) -> str:
    try:
        return m27b.parse_connect_output(raw, target)
    except ValueError as exc:
        raise RunnerStop('BLOCKED_ADB_CONNECT', str(exc)) from exc


def native_adb_executor(executable: Path) -> Callable[..., str]:
    def execute(arguments: list[str], *, timeout: float, stage: Path) -> str:
        if timeout <= 0 or timeout > MAX_DURATION_SECONDS:
            raise RunnerStop('BLOCKED_TIMEOUT', 'INVALID_COMMAND_TIMEOUT')
        try:
            return_code, output = m27b.run_bounded_process(
                [str(executable), *arguments], timeout=min(timeout, MAX_SINGLE_COMMAND_SECONDS),
                max_output_bytes=MAX_ADB_OUTPUT_BYTES,
            )
        except subprocess.TimeoutExpired as exc:
            raise RunnerStop('BLOCKED_TIMEOUT', 'ADB_TIMEOUT') from exc
        except m27b.ProcessOutputLimitError as exc:
            raise RunnerStop('BLOCKED_OUTPUT_LIMIT', 'ADB_OUTPUT_LIMIT') from exc
        except OSError as exc:
            raise RunnerStop('BLOCKED_ADB_ERROR', 'ADB_EXECUTION_ERROR') from exc
        if return_code != 0:
            raise RunnerStop('BLOCKED_ADB_ERROR', 'ADB_NONZERO_EXIT')
        try:
            return output.decode('utf-8', errors='strict')
        except UnicodeDecodeError as exc:
            raise RunnerStop('BLOCKED_ADB_OUTPUT', 'ADB_OUTPUT_ENCODING') from exc
    return execute


def resolve_adb_executable() -> Path:
    return m27b.resolve_adb_executable()


def _base_report(target: str | None = None) -> dict[str, Any]:
    return {
        'schema': SCHEMA,
        'collector_revision': COLLECTOR_REVISION,
        'action': ACTION,
        'device': TARGET_DEVICE,
        'authorization_mode': 'OWNER_AUTHORIZED_DIRECT_INSTRUCTION',
        'approval_record_created': False,
        'target_binding_sha256': hashlib.sha256(target.encode()).hexdigest() if target else None,
        'status': 'BLOCKED',
        'runtime_result': {},
        'started_at_utc': datetime.now(timezone.utc).isoformat(),
        'finished_at_utc': None,
        'duration_seconds': None,
        'limits': {
            'max_duration_seconds': MAX_DURATION_SECONDS,
            'max_observations': MAX_OBSERVATIONS,
            'max_processes': MAX_PROCESSES,
            'max_adb_commands': MAX_ADB_COMMANDS,
            'max_output_bytes_per_command': MAX_ADB_OUTPUT_BYTES,
        },
        'build_identity': {
            'fingerprint': {'status': 'NOT_OBSERVED', 'value': None},
            'abi': {'status': 'NOT_OBSERVED', 'value': None},
        },
        'process_statuses': [],
        'mappings': [],
        'filesystem_stats': {},
        'normalized_observation_count': 0,
        'adb_command_count': 0,
        'probe_sha256': PROBE_SHA256,
        'probe_status': 'NOT_OBSERVED',
        'probe_window_utc': None,
        'diagnostics': [],
        'raw_process_table_saved': False,
        'raw_maps_saved': False,
        'raw_adb_output_saved': False,
        'proprietary_bytes_copied': False,
        'files': [],
        'requested_count': 0,
        'safety': dict(SAFETY),
    }


def collect_mapping(selector: list[str] | tuple[str, ...], stage: Path, *,
                    executor: Callable[..., str], owner_authorized: bool,
                    monotonic_fn: Callable[[], float] = time.monotonic) -> dict[str, Any]:
    try:
        target = m27b.owner_authorized_target_serial()
    except (ValueError, OSError):
        target = None
    report = _base_report(target)
    if owner_authorized is not True:
        report['status'] = 'BLOCKED_OWNER_AUTHORIZATION_REQUIRED'
        report['diagnostics'].append({'code': 'OWNER_AUTHORIZATION_REQUIRED'})
        return report
    if target is None or list(selector) != ['-s', target]:
        report['status'] = 'BLOCKED_TARGET_BINDING'
        report['diagnostics'].append({'code': 'TARGET_BINDING_MISMATCH'})
        return report

    started = monotonic_fn()
    report['started_at_utc'] = datetime.now(timezone.utc).isoformat()

    def call(arguments: list[str]) -> str:
        elapsed = monotonic_fn() - started
        remaining = MAX_DURATION_SECONDS - elapsed
        if remaining <= 0:
            raise RunnerStop('BLOCKED_TIMEOUT', 'DURATION_LIMIT')
        if report['adb_command_count'] >= MAX_ADB_COMMANDS:
            raise RunnerStop('BLOCKED_LIMIT_REACHED', 'ADB_COMMAND_LIMIT')
        if not allowed_adb_arguments(arguments, selector):
            raise RunnerStop('BLOCKED_COMMAND_NOT_ALLOWLISTED', 'COMMAND_NOT_ALLOWLISTED')
        report['adb_command_count'] += 1
        try:
            output = executor(arguments, timeout=min(remaining, MAX_SINGLE_COMMAND_SECONDS), stage=stage)
        except RunnerStop:
            raise
        except subprocess.TimeoutExpired as exc:
            raise RunnerStop('BLOCKED_TIMEOUT', 'ADB_TIMEOUT') from exc
        except (OSError, RuntimeError) as exc:
            raise RunnerStop('BLOCKED_ADB_ERROR', 'ADB_EXECUTION_ERROR') from exc
        if monotonic_fn() - started >= MAX_DURATION_SECONDS:
            raise RunnerStop('BLOCKED_TIMEOUT', 'DURATION_LIMIT')
        return output

    try:
        connect = call(['connect', target])
        report['connection_status'] = _parse_connect(connect, target)
        state = _single_value(call([*selector, 'get-state']))
        if state != 'device':
            raise RunnerStop('BLOCKED_DEVICE_STATE', 'ADB_TARGET_NOT_READY')
        fingerprint = _single_value(call([*selector, 'shell', 'getprop', 'ro.build.fingerprint']))
        report['build_identity']['fingerprint'] = {
            'status': 'OBSERVED' if fingerprint == TARGET_FINGERPRINT else 'MISMATCH',
            'value': fingerprint if fingerprint == TARGET_FINGERPRINT else None,
        }
        if fingerprint != TARGET_FINGERPRINT:
            raise RunnerStop('BLOCKED_IDENTITY_MISMATCH', 'FINGERPRINT_MISMATCH')
        abi = _single_value(call([*selector, 'shell', 'getprop', 'ro.product.cpu.abi']))
        report['build_identity']['abi'] = {
            'status': 'OBSERVED' if abi == TARGET_ABI else 'MISMATCH',
            'value': abi if abi == TARGET_ABI else None,
        }
        if abi != TARGET_ABI:
            raise RunnerStop('BLOCKED_IDENTITY_MISMATCH', 'ABI_MISMATCH')
        report['build_identity']['hardware_variant'] = 'OWNER_ESTABLISHED_PICO_4_PRO'
        try:
            probe_started_at = datetime.now(timezone.utc).isoformat()
            probe_raw = call([*selector, 'shell', 'sh', '-c', PROBE_ARGUMENT])
            probe_finished_at = datetime.now(timezone.utc).isoformat()
            parsed = parse_probe_output(probe_raw)
        except ValueError as exc:
            report['probe_status'] = 'MALFORMED_OUTPUT'
            raise RunnerStop('BLOCKED_UNEXPECTED_OUTPUT', str(exc)) from exc
        report['probe_window_utc'] = {
            'started_at': probe_started_at,
            'finished_at': probe_finished_at,
            'meaning': 'host UTC bounds for the fixed shell snapshot; not a per-mapping device timestamp',
        }
        report['probe_status'] = parsed['scan_status']
        report['normalized_observation_count'] = parsed['record_count']
        report['process_statuses'] = parsed['process_statuses']
        report['mappings'] = parsed['mappings']
        report['filesystem_stats'] = parsed['filesystem_stats']
        for mapping in report['mappings']:
            mapping['observation_window_utc'] = {
                'started_at': probe_started_at,
                'finished_at': probe_finished_at,
            }
        for process_status in report['process_statuses']:
            process_status['observation_window_utc'] = {
                'started_at': probe_started_at,
                'finished_at': probe_finished_at,
            }
        report['raw_process_table_saved'] = parsed['raw_process_table_saved']
        report['raw_maps_saved'] = parsed['raw_maps_saved']
        report['runtime_result'] = evaluate_mapping_result(parsed)
        report['status'] = report['runtime_result']['status']
        if report['status'] == 'BLOCKED':
            report['diagnostics'].append({'code': report['runtime_result'].get('stop_reason', 'NO_TARGET_MAPPING')})
    except RunnerStop as exc:
        report['status'] = exc.status
        report['diagnostics'].append({'code': exc.code})
    finally:
        report['finished_at_utc'] = datetime.now(timezone.utc).isoformat()
        report['duration_seconds'] = round(max(0.0, monotonic_fn() - started), 6)
    if report['duration_seconds'] is not None and report['duration_seconds'] > MAX_DURATION_SECONDS:
        report['status'] = 'BLOCKED_TIMEOUT'
        report['runtime_result'] = {'status': 'BLOCKED', 'stop_reason': 'DURATION_LIMIT'}
        report['diagnostics'].append({'code': 'DURATION_LIMIT'})
    return report


def dry_run_plan() -> dict[str, Any]:
    return {
        'action': ACTION,
        'device': TARGET_DEVICE,
        'target_binding': 'fixed owner-bound ADB serial; no device enumeration',
        'max_duration_seconds': MAX_DURATION_SECONDS,
        'max_observations': MAX_OBSERVATIONS,
        'max_processes': MAX_PROCESSES,
        'max_adb_commands': MAX_ADB_COMMANDS,
        'allowed_libraries': list(EXPECTED_LIBRARIES),
        'process_name_pattern': PROCESS_NAME_PATTERN,
        'probe_sha256': PROBE_SHA256,
        'device_facing_calls_performed': False,
        'approval_record_created': False,
        'status': 'DRY_RUN_ONLY',
        'safety': dict(SAFETY),
    }


def build_evidence_package(report: dict[str, Any]) -> bytes:
    bio = io.BytesIO()
    with zipfile.ZipFile(bio, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        archive.writestr('manifest.json', json.dumps(report, indent=2, ensure_ascii=False) + '\n')
    return bio.getvalue()


def _preflight_report(code: str) -> dict[str, Any]:
    report = _base_report()
    report['status'] = 'BLOCKED_PREFLIGHT'
    report['finished_at_utc'] = datetime.now(timezone.utc).isoformat()
    report['diagnostics'].append({'code': code})
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--dry-run', action='store_true')
    modes.add_argument('--owner-authorized-run', action='store_true',
                       help='run only under the direct owner authorization in the current task')
    args = parser.parse_args(argv)
    if args.dry_run or not args.owner_authorized_run:
        print(json.dumps(dry_run_plan(), separators=(',', ':')))
        return 0 if args.dry_run else 2

    target = None
    try:
        target = m27b.owner_authorized_target_serial()
        adb_path = resolve_adb_executable()
    except (ValueError, OSError):
        adb_path = None
    run_name = datetime.now(timezone.utc).strftime('p3a-m28b-runtime-map-%Y%m%dT%H%M%SZ-') + uuid4().hex[:8]
    if target is None or adb_path is None:
        report = _preflight_report('TARGET_BINDING_OR_PINNED_ADB_UNAVAILABLE')
    else:
        with tempfile.TemporaryDirectory(prefix='p3a-m28b-private-') as temp:
            report = collect_mapping(
                ['-s', target], Path(temp), executor=native_adb_executor(adb_path),
                owner_authorized=True,
            )
    try:
        package = build_evidence_package(report)
        receipt = canonical_commit(Path(ROOT), run_name, report, package)
    except Exception:
        print('PUBLICATION_BLOCKED: canonical SMB commit failed; no fallback used', file=sys.stderr)
        return 3
    print(json.dumps(receipt, separators=(',', ':')))
    return 0 if report['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
