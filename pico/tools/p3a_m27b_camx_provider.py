"""M2.7B: separately approved, read-only acquisition of observed camx_core ELF files.

Importing this module and running --dry-run are device-free.  The CLI requires
an exact, scoped approval, an explicit ADB target, and an interactive `yes`.
Every native ADB operation is re-gated and checked against a fixed allowlist.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shlex
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any, Callable, Mapping
from uuid import uuid4

if __package__:
    from .p3a_collect_producers import build_zip, canonical_commit, sha256, validate_arm64_elf
    from .p3a_quickcamera_inventory import ROOT, ROOTS
    from .p3a6_execution_gate import APPROVAL_SCHEMA, TARGET_DEVICE, check_hardware_execution_gate
else:
    from p3a_collect_producers import build_zip, canonical_commit, sha256, validate_arm64_elf
    from p3a_quickcamera_inventory import ROOT, ROOTS
    from p3a6_execution_gate import APPROVAL_SCHEMA, TARGET_DEVICE, check_hardware_execution_gate


ACTION = 'read-only-camx-core-provider-acquisition'
SCHEMA = 'p3a.m27b.camx_core_provider.v1'
MAX_DURATION_SECONDS = 60
MAX_OBSERVATIONS = 200
MAX_ADB_COMMANDS = 160
MAX_CANDIDATES = 16
MAX_PROVIDER_FILE_BYTES = 64 * 1024 * 1024
MAX_TOTAL_PROVIDER_BYTES = 128 * 1024 * 1024
MAX_OUTPUT_BYTES = 64 * 1024
MAX_READELF_OUTPUT_BYTES = 4 * 1024 * 1024
MAX_APPROVAL_BYTES = 64 * 1024
TARGET_FINGERPRINT = 'Pico/Phoenix_ovs/PICOA8110:10/5.11.2/smartcm.1725996131:user/dev-keys'
TARGET_ABI = 'arm64-v8a'
EXPECTED_PROPERTIES = {
    'ro.product.model': 'A8110',
    'ro.product.device': 'PICOA8110',
    'ro.product.name': 'Phoenix_ovs',
    'ro.product.manufacturer': 'Pico',
    'ro.build.fingerprint': TARGET_FINGERPRINT,
    'ro.product.cpu.abi': TARGET_ABI,
}
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
BRIDGE_SYMBOLS = (
    'CSLRegisterMessageHandler',
    'CSLHwInternalDefaultSubscribeEvents',
    'CSLHwInternalDQEvent',
    'CSLHwInternalSendRequestManagerEvent',
)


def _render_discovery_script(roots: tuple[str, ...] = ROOTS) -> str:
    """Render the fixed POSIX probe; non-production roots are test-only."""
    if roots != ROOTS:
        # Tests may replace paths only in a local script; the native allowlist
        # below accepts the production constant, never a rendered override.
        if not roots or any(not re.fullmatch(r'/[A-Za-z0-9_.+-]+(?:/[A-Za-z0-9_.+-]+)*', root)
                            or '..' in PurePosixPath(root).parts for root in roots):
            raise ValueError('Invalid synthetic probe roots')
    root_words = ' '.join(roots)
    root_case_patterns = '|'.join(root.rstrip('/') + '/*' for root in roots)
    return (
        'set -f\n'
        f'for root in {root_words}; do\n'
        '  if [ ! -d "$root" ]; then\n'
        "    printf 'P3A27A\\tROOT\\t%s\\tABSENT\\n' \"$root\"\n"
        '    continue\n'
        '  fi\n'
        '  if [ ! -r "$root" ] || [ ! -x "$root" ]; then\n'
        "    printf 'P3A27A\\tROOT\\t%s\\tUNAVAILABLE\\n' \"$root\"\n"
        '    continue\n'
        '  fi\n'
        "  paths=$(find \"$root\" -name 'camx_core.so' -print 2>/dev/null)\n"
        '  find_status=$?\n'
        '  if [ "$find_status" -ne 0 ]; then\n'
        "    printf 'P3A27A\\tROOT\\t%s\\tFIND_ERROR\\n' \"$root\"\n"
        '    continue\n'
        '  fi\n'
        "  printf 'P3A27A\\tROOT\\t%s\\tSCANNED\\n' \"$root\"\n"
        '  old_ifs=$IFS\n'
        "  IFS='\n'\n"
        '  for candidate in $paths; do\n'
        '    [ -n "$candidate" ] || continue\n'
        '    if [ -L "$candidate" ]; then\n'
        '      resolved=$(readlink -f "$candidate" 2>/dev/null)\n'
        '      resolve_status=$?\n'
        '      if [ "$resolve_status" -ne 0 ] || [ -z "$resolved" ]; then\n'
        "        printf 'P3A27A\\tCANDIDATE_LIMITATION\\t%s\\tLINK_UNRESOLVED\\n' \"$candidate\"\n"
        '      else\n'
        '        case "$resolved" in\n'
        f'          {root_case_patterns})\n'
        '            case "$resolved" in\n'
        "              */lib64/*) printf 'P3A27A\\tCANDIDATE\\t%s\\t%s\\n' \"$candidate\" \"$resolved\" ;;\n"
        "              *) printf 'P3A27A\\tCANDIDATE_LIMITATION\\t%s\\tTARGET_ABI_PATH_MISMATCH\\n' \"$candidate\" ;;\n"
        '            esac ;;\n'
        "          *) printf 'P3A27A\\tCANDIDATE_LIMITATION\\t%s\\tTARGET_OUTSIDE_ALLOWED_ROOTS\\n' \"$candidate\" ;;\n"
        '        esac\n'
        '      fi\n'
        '    elif [ -f "$candidate" ]; then\n'
        "      printf 'P3A27A\\tCANDIDATE\\t%s\\t%s\\n' \"$candidate\" \"$candidate\"\n"
        '    else\n'
        "      printf 'P3A27A\\tCANDIDATE_LIMITATION\\t%s\\tNOT_REGULAR_FILE\\n' \"$candidate\"\n"
        '    fi\n'
        '  done\n'
        '  IFS=$old_ifs\n'
        'done\n'
    )


DISCOVERY_SCRIPT = _render_discovery_script()
SH_DISCOVERY_ARGUMENT = shlex.quote(DISCOVERY_SCRIPT)
SCRIPT_SHA256 = hashlib.sha256(DISCOVERY_SCRIPT.encode('utf-8')).hexdigest()
_SEGMENT = re.compile(r'^[A-Za-z0-9_.+@=-]+$')
_BUILD_ID = re.compile(r'\bBuild ID:\s*([a-fA-F0-9]{16,64})\b')
_NEEDED = re.compile(r'\(NEEDED\).*?\[([^\]\r\n]{1,256})\]')


class LimitReachedError(ValueError):
    def __init__(self, code: str, count: int):
        super().__init__(code)
        self.code = code
        self.count = count


class RunnerStop(RuntimeError):
    def __init__(self, status: str, code: str):
        super().__init__(code)
        self.status = status
        self.code = code


def device_selector(*, serial: str | None = None,
                    transport_id: int | str | None = None) -> list[str]:
    if (serial is None) == (transport_id is None):
        raise ValueError('Select exactly one explicit ADB serial or transport ID')
    if serial is not None:
        if not isinstance(serial, str) or not re.fullmatch(r'[A-Za-z0-9._:-]{1,128}', serial):
            raise ValueError('Invalid ADB serial selector')
        return ['-s', serial]
    if isinstance(transport_id, bool) or not str(transport_id).isdigit() or int(transport_id) < 1:
        raise ValueError('Transport ID must be a positive decimal integer')
    return ['-t', str(int(transport_id))]


def resolve_adb_executable(env: Mapping[str, str] | None = None) -> Path:
    """Use only the pinned SDK executable; never search PATH or other SDKs."""
    env = os.environ if env is None else env
    local = env.get('LOCALAPPDATA')
    if not local:
        raise FileNotFoundError('LOCALAPPDATA is unavailable; pinned SDK ADB cannot be resolved')
    expected = Path(local) / 'Android' / 'Sdk' / 'platform-tools' / 'adb.exe'
    try:
        resolved = expected.resolve(strict=True)
    except OSError as exc:
        raise FileNotFoundError('Pinned Android SDK adb.exe is missing') from exc
    # Canonicalize LOCALAPPDATA itself (which can have a Windows 8.3 alias),
    # then require every SDK subpath component to remain at the pinned path.
    configured_path = Path(local).resolve(strict=True) / 'Android' / 'Sdk' / 'platform-tools' / 'adb.exe'
    if os.path.normcase(os.path.normpath(str(resolved))) != os.path.normcase(
            os.path.normpath(str(configured_path))):
        raise FileNotFoundError('Pinned Android SDK adb.exe resolves outside the configured SDK path')
    if not resolved.is_file() or resolved.name.lower() != 'adb.exe':
        raise FileNotFoundError('Pinned Android SDK path is not an adb.exe file')
    return resolved


def valid_library_path(path: str, roots: tuple[str, ...] = ROOTS) -> bool:
    if not isinstance(path, str) or not path.startswith('/') or '\\' in path:
        return False
    parts = path.split('/')
    root = next((item for item in sorted(roots, key=len, reverse=True)
                 if path.startswith(item.rstrip('/') + '/')), None)
    if len(parts) < 4 or parts[0] != '' or root is None:
        return False
    if any(not part or part in ('.', '..') or not _SEGMENT.fullmatch(part) for part in parts[1:]):
        return False
    relative_parts = path[len(root.rstrip('/')) + 1:].split('/')
    return (bool(re.fullmatch(r'[A-Za-z0-9_.+@=-]+\.so(?:\.[0-9]+)*', parts[-1]))
            and 'lib64' in relative_parts[:-1])


def valid_source_path(path: str, roots: tuple[str, ...] = ROOTS) -> bool:
    return valid_library_path(path, roots) and PurePosixPath(path).name == 'camx_core.so'


def _protocol_lines(raw: str) -> list[str]:
    if not isinstance(raw, str) or not raw:
        raise ValueError('OUTPUT_FRAMING')
    normalized = raw.replace('\r\n', '\n')
    if '\r' in normalized or not normalized.endswith('\n'):
        raise ValueError('OUTPUT_FRAMING')
    lines = normalized[:-1].split('\n')
    if any(not line or any(ord(ch) < 0x20 and ch != '\t' for ch in line) for line in lines):
        raise ValueError('OUTPUT_FRAMING')
    return lines


def parse_discovery_output(raw: str, roots: tuple[str, ...] = ROOTS) -> dict[str, Any]:
    expected_roots = tuple(roots)
    roots_seen: dict[str, str] = {}
    candidates: list[dict[str, str]] = []
    limitations: list[dict[str, str]] = []
    statuses = {'SCANNED', 'ABSENT', 'UNAVAILABLE', 'FIND_ERROR'}
    for line in _protocol_lines(raw):
        fields = line.split('\t')
        if len(fields) == 4 and fields[0:2] == ['P3A27A', 'ROOT']:
            _, _, root, status = fields
            if root not in expected_roots or root in roots_seen or status not in statuses:
                raise ValueError('UNEXPECTED_RECORD')
            roots_seen[root] = status
        elif len(fields) == 4 and fields[0:2] == ['P3A27A', 'CANDIDATE']:
            observed_path, source_path = fields[2:]
            if (not valid_source_path(observed_path, expected_roots)
                    or not valid_library_path(source_path, expected_roots)):
                raise ValueError('INVALID_SOURCE_PATH')
            path_root = next((root for root in expected_roots
                              if observed_path.startswith(root.rstrip('/') + '/')), None)
            if path_root not in roots_seen or roots_seen[path_root] != 'SCANNED':
                raise ValueError('UNEXPECTED_RECORD')
            if any(item['observed_path'] == observed_path for item in candidates):
                raise ValueError('DUPLICATE_SOURCE_PATH')
            candidates.append({'observed_path': observed_path, 'source_path': source_path})
            if len(candidates) > MAX_CANDIDATES:
                raise LimitReachedError('CANDIDATE_LIMIT', len(candidates))
        elif len(fields) == 4 and fields[0:2] == ['P3A27A', 'CANDIDATE_LIMITATION']:
            observed_path, code = fields[2:]
            if not valid_source_path(observed_path, expected_roots) or code not in (
                    'LINK_UNRESOLVED', 'TARGET_ABI_PATH_MISMATCH',
                    'TARGET_OUTSIDE_ALLOWED_ROOTS', 'NOT_REGULAR_FILE'):
                raise ValueError('INVALID_CANDIDATE_LIMITATION')
            path_root = next((root for root in expected_roots
                              if observed_path.startswith(root.rstrip('/') + '/')), None)
            if path_root not in roots_seen or roots_seen[path_root] != 'SCANNED':
                raise ValueError('UNEXPECTED_RECORD')
            limitations.append({'observed_path': observed_path, 'code': code})
        else:
            raise ValueError('UNEXPECTED_RECORD')
    if set(roots_seen) != set(expected_roots):
        raise ValueError('MISSING_ROOT_STATUS')
    return {
        'root_status': roots_seen,
        'candidates': candidates,
        'candidate_limitations': limitations,
        'limited_roots': [root for root, status in roots_seen.items()
                          if status in ('UNAVAILABLE', 'FIND_ERROR')],
        'status': 'CANDIDATES_FOUND' if candidates else
                  'LIMITATIONS_ONLY' if limitations else 'NO_CANDIDATES',
    }


def parse_single_value(raw: str) -> str:
    lines = _protocol_lines(raw)
    if len(lines) != 1 or '\t' in lines[0]:
        raise ValueError('OUTPUT_FRAMING')
    return lines[0]


def parse_sha256sum(raw: str, expected_path: str) -> str:
    line = parse_single_value(raw)
    match = re.fullmatch(r'([a-fA-F0-9]{64})\s+(.+)', line)
    if not match or match.group(2) != expected_path:
        raise ValueError('SHA256_OUTPUT_MISMATCH')
    return match.group(1).lower()


def parse_remote_size(raw: str, expected_path: str) -> int:
    line = parse_single_value(raw)
    match = re.fullmatch(r'\s*([0-9]{1,12})\s+(.+)', line)
    if not match or match.group(2) != expected_path:
        raise ValueError('REMOTE_SIZE_OUTPUT_MISMATCH')
    return int(match.group(1))


def validate_identity(properties: Mapping[str, str]) -> None:
    for key, expected in EXPECTED_PROPERTIES.items():
        if properties.get(key) != expected:
            if key == 'ro.product.cpu.abi':
                raise RunnerStop('BLOCKED_ABI_MISMATCH', 'ABI_MISMATCH')
            raise RunnerStop('BLOCKED_UNEXPECTED_DEVICE', 'IDENTITY_MISMATCH')


def parse_readelf_metadata(output: str) -> dict[str, Any]:
    if (not isinstance(output, str)
            or len(output.encode('utf-8', errors='replace')) > MAX_READELF_OUTPUT_BYTES):
        raise ValueError('READELF_OUTPUT_LIMIT')
    build = _BUILD_ID.search(output)
    needed = list(dict.fromkeys(_NEEDED.findall(output)))
    exported: set[str] = set()
    undefined: set[str] = set()
    for line in output.splitlines():
        fields = line.split(None, 7)
        if len(fields) != 8 or not re.fullmatch(r'\d+:', fields[0]):
            continue
        bind, visibility, section, name = fields[4:8]
        name = name.split()[0] if name else ''
        if not name or bind not in ('GLOBAL', 'WEAK', 'GNU_UNIQUE'):
            continue
        if section == 'UND':
            undefined.add(name)
        elif visibility in ('DEFAULT', 'PROTECTED'):
            exported.add(name)
    all_symbols = exported | undefined
    hits = sorted(name for name in all_symbols
                  if name.split('@', 1)[0] in BRIDGE_SYMBOLS)
    has_dynsym = bool(re.search(r"Symbol table ['\"]\.dynsym['\"]", output))
    return {
        'build_id': build.group(1).lower() if build else None,
        'exported_symbols': sorted(exported),
        'undefined_symbols': sorted(undefined),
        'dt_needed': needed,
        'bridge_symbol_hits': hits,
        'dynamic_symbol_table_present': has_dynsym,
        'metadata_status': 'OBSERVED' if build and has_dynsym else 'PARTIAL',
    }


def destination_for(stage: Path, source_path: str) -> Path:
    if not valid_source_path(source_path):
        raise ValueError('INVALID_SOURCE_PATH')
    base = stage.resolve()
    destination = base.joinpath(*PurePosixPath(source_path).parts[1:]).resolve()
    if not destination.is_relative_to(base):
        raise ValueError('UNSAFE_LOCAL_DESTINATION')
    return destination


def allowed_adb_arguments(arguments: list[str] | tuple[str, ...],
                          selector: list[str] | tuple[str, ...],
                          candidates: list[Any] | tuple[Any, ...],
                          stage: Path) -> bool:
    argv = list(arguments)
    prefix = list(selector)
    if (len(prefix) != 2 or not (
            (prefix[0] == '-s' and re.fullmatch(r'[A-Za-z0-9._:-]{1,128}', prefix[1]))
            or (prefix[0] == '-t' and prefix[1].isdigit() and int(prefix[1]) >= 1))):
        return False
    if argv[:len(prefix)] != prefix:
        return False
    command = argv[len(prefix):]
    if command == ['get-state']:
        return True
    if len(command) == 3 and command[:2] == ['shell', 'getprop']:
        return command[2] in EXPECTED_PROPERTIES
    if command == ['shell', 'sh', '-c', SH_DISCOVERY_ARGUMENT]:
        return True
    candidate_map = {
        item['observed_path']: item['source_path'] if 'source_path' in item else item['observed_path']
        for item in candidates if isinstance(item, Mapping)
    }
    candidate_map.update({item: item for item in candidates if isinstance(item, str)})
    source_paths = set(candidate_map.values())
    if len(command) == 4 and command[:3] == ['shell', 'readlink', '-f']:
        return command[3] in candidate_map and valid_source_path(command[3])
    if len(command) == 3 and command[:2] == ['shell', 'sha256sum']:
        return command[2] in source_paths and valid_library_path(command[2])
    if len(command) == 4 and command[:3] == ['shell', 'wc', '-c']:
        return command[3] in source_paths and valid_library_path(command[3])
    if len(command) == 3 and command[0] == 'pull':
        path, local = command[1:]
        if not valid_library_path(path):
            return False
        for observed, resolved in candidate_map.items():
            if resolved != path:
                continue
            try:
                if Path(local) == destination_for(stage, observed):
                    return True
            except (OSError, ValueError):
                continue
        return False
    return False


def dry_run_plan() -> dict[str, Any]:
    return {
        'action': ACTION,
        'device': TARGET_DEVICE,
        'max_duration_seconds': MAX_DURATION_SECONDS,
        'max_observations': MAX_OBSERVATIONS,
        'max_adb_commands': MAX_ADB_COMMANDS,
        'max_candidates': MAX_CANDIDATES,
        'max_provider_file_bytes': MAX_PROVIDER_FILE_BYTES,
        'max_total_provider_bytes': MAX_TOTAL_PROVIDER_BYTES,
        'max_stdout_bytes': MAX_OUTPUT_BYTES,
        'discovery_script_sha256': SCRIPT_SHA256,
        'device_facing_calls_performed': False,
        'status': 'DRY_RUN_ONLY',
    }


class ProcessOutputLimitError(RuntimeError):
    pass


def run_bounded_process(arguments: list[str], *, timeout: float,
                        max_output_bytes: int) -> tuple[int, bytes]:
    """Run a local tool with a streaming stdout cap and no captured stderr."""
    try:
        process = subprocess.Popen(
            arguments, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
        )
    except OSError:
        raise

    chunks: list[bytes] = []
    overflow = threading.Event()
    read_errors: list[Exception] = []
    byte_count = 0

    def drain_stdout() -> None:
        nonlocal byte_count
        try:
            assert process.stdout is not None
            while True:
                chunk = process.stdout.read(8192)
                if not chunk:
                    break
                byte_count += len(chunk)
                if byte_count > max_output_bytes:
                    overflow.set()
                    process.kill()
                    break
                chunks.append(chunk)
        except Exception as exc:
            read_errors.append(exc)
            try:
                process.kill()
            except OSError:
                pass

    reader = threading.Thread(target=drain_stdout, name='p3a-m27b-bounded-stdout', daemon=True)
    reader.start()
    try:
        return_code = process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            process.kill()
        except OSError:
            pass
        process.wait()
        reader.join(timeout=2)
        if process.stdout is not None:
            process.stdout.close()
        raise
    reader.join(timeout=2)
    if reader.is_alive():
        try:
            process.kill()
        except OSError:
            pass
        if process.stdout is not None:
            process.stdout.close()
        raise OSError('Process stdout reader did not terminate')
    if process.stdout is not None:
        process.stdout.close()
    if overflow.is_set() or byte_count > max_output_bytes:
        raise ProcessOutputLimitError('Process stdout exceeded its byte limit')
    if read_errors:
        raise OSError('Process stdout could not be read') from read_errors[0]
    return return_code, b''.join(chunks)


def native_adb_executor(executable: Path) -> Callable[..., str]:
    def execute(arguments: list[str], *, timeout: float, stage: Path) -> str:
        try:
            return_code, output = run_bounded_process(
                [str(executable), *arguments], timeout=timeout,
                max_output_bytes=MAX_OUTPUT_BYTES,
            )
        except subprocess.TimeoutExpired as exc:
            raise RunnerStop('PARTIAL_ADB_TIMEOUT', 'ADB_TIMEOUT') from exc
        except ProcessOutputLimitError as exc:
            raise RunnerStop('PARTIAL_OUTPUT_LIMIT', 'ADB_OUTPUT_LIMIT') from exc
        except OSError as exc:
            raise RunnerStop('PARTIAL_ADB_ERROR', 'ADB_EXECUTION_ERROR') from exc
        if return_code != 0:
            raise RunnerStop('PARTIAL_ADB_ERROR', 'ADB_NONZERO_EXIT')
        return output.decode('utf-8', errors='replace')
    return execute


def readelf_metadata(path: Path, executable: Path | None = None,
                     timeout: float = 20) -> dict[str, Any]:
    if executable is None:
        local = os.environ.get('LOCALAPPDATA', '')
        ndk = Path(local) / 'Android' / 'Sdk' / 'ndk'
        candidates = sorted(ndk.glob('*/toolchains/llvm/prebuilt/windows-x86_64/bin/llvm-readelf.exe'), reverse=True)
        if not candidates:
            raise FileNotFoundError('NDK llvm-readelf.exe unavailable')
        executable = candidates[0]
    try:
        return_code, output = run_bounded_process(
            [str(executable), '--notes', '--dyn-syms', '--dynamic', '--wide', str(path)],
            timeout=max(0.1, min(20.0, timeout)),
            max_output_bytes=MAX_READELF_OUTPUT_BYTES,
        )
    except (OSError, subprocess.TimeoutExpired, ProcessOutputLimitError) as exc:
        raise RuntimeError('READELF_EXECUTION_FAILED') from exc
    if return_code != 0:
        raise RuntimeError('READELF_OUTPUT_UNAVAILABLE')
    return parse_readelf_metadata(output.decode('utf-8', errors='replace'))


def _valid_approval_limits(approval: Mapping[str, Any]) -> bool:
    duration = approval.get('max_duration_seconds')
    observations = approval.get('max_observations')
    return (
        type(duration) is int and 1 <= duration <= MAX_DURATION_SECONDS
        and type(observations) is int and 1 <= observations <= MAX_OBSERVATIONS
    )


def collect_provider(
    approval: Mapping[str, Any] | None,
    confirmation_response: str,
    selector: list[str] | tuple[str, ...],
    stage: Path,
    *,
    executor: Callable[..., str],
    metadata_reader: Callable[..., Mapping[str, Any]],
    direct_user_instruction: bool,
    now_utc_fn: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    monotonic_fn: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    created_utc = datetime.now(timezone.utc).isoformat()
    report: dict[str, Any] = {
        'schema': SCHEMA,
        'created_utc': created_utc,
        'started_utc': created_utc,
        'finished_utc': None,
        'action': ACTION,
        'device': TARGET_DEVICE,
        'status': 'BLOCKED',
        'safety': SAFETY.copy(),
        'build_identity': {},
        'methods': {
            'device_selection': 'explicit ADB serial or numeric transport ID; no adb devices scan',
            'library_discovery': 'fixed POSIX find/readlink probe over six P3-A library roots',
            'size_preflight': 'unprivileged wc -c for every candidate before any pull; 64 MiB/file and 128 MiB aggregate caps',
            'remote_sha256': 'unprivileged adb shell sha256sum before and after each pull',
            'transfer': 'adb pull into ephemeral local staging only',
            'elf_metadata': 'local NDK llvm-readelf Build ID, dynamic symbols, and DT_NEEDED',
            'publication': 'canonical SMB .part readback, atomic finalization, sidecar last',
        },
        'discovery_script_sha256': SCRIPT_SHA256,
        'root_status': {},
        'candidates': [],
        'candidate_sizes': [],
        'planned_provider_bytes': 0,
        'candidate_limitations': [],
        'files': [],
        'errors': [],
        'adb_command_count': 0,
        'observations': 0,
        'timestamp_proven': False,
        'bridge_verified': False,
        'runtime_dependency_verified': False,
        'kernel_event_identity_verified': False,
    }
    if confirmation_response != 'yes':
        report['status'] = 'BLOCKED_CONFIRMATION_REQUIRED'
        report['errors'].append({'code': 'CONFIRMATION_REQUIRED'})
        return report
    if not direct_user_instruction:
        report['status'] = 'BLOCKED_DIRECT_INSTRUCTION_REQUIRED'
        report['errors'].append({'code': 'DIRECT_INSTRUCTION_REQUIRED'})
        return report
    if not isinstance(approval, Mapping):
        report['status'] = 'BLOCKED_NO_APPROVAL'
        report['errors'].append({'code': 'NO_APPROVAL'})
        return report
    if not _valid_approval_limits(approval):
        report['status'] = 'BLOCKED_UNBOUNDED_APPROVAL'
        report['errors'].append({'code': 'APPROVAL_LIMITS_EXCEED_ACTION_CAPS'})
        return report
    approval_id = approval.get('approval_id')
    if not isinstance(approval_id, str) or not approval_id:
        report['status'] = 'BLOCKED_INVALID_APPROVAL'
        report['errors'].append({'code': 'INVALID_APPROVAL_ID'})
        return report
    # The full gate token is constructed only after exact interactive `yes`.
    gate_confirmation = f'P3-A6 APPROVE {approval_id} {ACTION}'
    report['approval_id'] = approval_id
    started = monotonic_fn()
    duration_limit = min(MAX_DURATION_SECONDS, approval['max_duration_seconds'])
    observation_limit = min(MAX_OBSERVATIONS, approval['max_observations'])
    candidates: list[dict[str, str]] = []

    def call(arguments: list[str]) -> str:
        elapsed = monotonic_fn() - started
        if elapsed >= duration_limit:
            raise RunnerStop('PARTIAL_TIMEOUT', 'DURATION_LIMIT')
        if report['adb_command_count'] >= MAX_ADB_COMMANDS or report['observations'] >= observation_limit:
            raise RunnerStop('PARTIAL_LIMIT_REACHED', 'OBSERVATION_LIMIT')
        decision = check_hardware_execution_gate(
            approval, ACTION, gate_confirmation, now_utc=now_utc_fn(),
        )
        if not decision.allowed:
            raise RunnerStop(decision.status, decision.status)
        if not allowed_adb_arguments(arguments, selector, candidates, stage):
            raise RunnerStop('BLOCKED_COMMAND_NOT_ALLOWLISTED', 'COMMAND_NOT_ALLOWLISTED')
        remaining = duration_limit - (monotonic_fn() - started)
        if remaining <= 0:
            raise RunnerStop('PARTIAL_TIMEOUT', 'DURATION_LIMIT')
        report['adb_command_count'] += 1
        report['observations'] += 1
        return executor(arguments, timeout=min(15.0, remaining), stage=stage)

    def property_value(key: str) -> str:
        return parse_single_value(call([*selector, 'shell', 'getprop', key]))

    def identity_refresh() -> tuple[str, str]:
        fingerprint = property_value('ro.build.fingerprint')
        abi = property_value('ro.product.cpu.abi')
        if fingerprint != TARGET_FINGERPRINT:
            raise RunnerStop('PARTIAL_IDENTITY_CHANGED', 'FINGERPRINT_CHANGED')
        if abi != TARGET_ABI:
            raise RunnerStop('PARTIAL_ABI_CHANGED', 'ABI_CHANGED')
        return fingerprint, abi

    try:
        state = parse_single_value(call([*selector, 'get-state']))
        if state != 'device':
            raise RunnerStop('BLOCKED_DEVICE_STATE', 'ADB_TARGET_NOT_READY')
        properties = {key: property_value(key) for key in EXPECTED_PROPERTIES}
        report['build_identity'] = properties
        validate_identity(properties)

        try:
            probe = call([*selector, 'shell', 'sh', '-c', SH_DISCOVERY_ARGUMENT])
            found = parse_discovery_output(probe)
        except LimitReachedError as exc:
            report['discovery_status'] = 'LIMIT_REACHED'
            report['candidate_count_at_least'] = exc.count
            raise RunnerStop('BLOCKED_LIMIT_REACHED', exc.code) from exc
        except ValueError as exc:
            report['discovery_status'] = 'MALFORMED_OUTPUT'
            raise RunnerStop('BLOCKED_UNEXPECTED_OUTPUT', str(exc)) from exc

        report['root_status'] = found['root_status']
        report['candidates'] = found['candidates']
        report['candidate_limitations'] = found['candidate_limitations']
        report['discovery_status'] = found['status']
        if not found['candidates']:
            has_limitations = bool(found['limited_roots'] or found['candidate_limitations'])
            code = 'NO_PROVIDER_FOUND' if not has_limitations else 'DISCOVERY_LIMITATIONS'
            status = 'BLOCKED_NO_PROVIDER' if not has_limitations else 'PARTIAL_DISCOVERY'
            raise RunnerStop(status, code)
        candidates.extend(found['candidates'])

        # Size every candidate before pulling any of them. If the aggregate
        # cannot fit the private staging/ZIP budget, no path is selected based
        # on discovery order.
        sizes: dict[str, int] = {}
        for candidate in candidates:
            source_path = candidate['source_path']
            try:
                size = parse_remote_size(
                    call([*selector, 'shell', 'wc', '-c', source_path]), source_path,
                )
            except ValueError as exc:
                raise RunnerStop('BLOCKED_UNEXPECTED_OUTPUT', str(exc)) from exc
            sizes[candidate['observed_path']] = size
            report['candidate_sizes'].append({
                'observed_path': candidate['observed_path'],
                'source_path': source_path,
                'bytes': size,
            })
        report['planned_provider_bytes'] = sum(sizes.values())
        if any(size > MAX_PROVIDER_FILE_BYTES for size in sizes.values()):
            raise RunnerStop('BLOCKED_LIMIT_REACHED', 'PROVIDER_FILE_SIZE_LIMIT')
        if report['planned_provider_bytes'] > MAX_TOTAL_PROVIDER_BYTES:
            raise RunnerStop('BLOCKED_LIMIT_REACHED', 'TOTAL_PROVIDER_SIZE_LIMIT')

        for candidate in candidates:
            observed_path = candidate['observed_path']
            source_path = candidate['source_path']
            destination = destination_for(stage, observed_path)
            destination.parent.mkdir(parents=True, exist_ok=True)
            before = local_sha = after = None
            try:
                identity_refresh()
                resolved_before = parse_single_value(
                    call([*selector, 'shell', 'readlink', '-f', observed_path]),
                )
                if resolved_before != source_path:
                    raise ValueError('SOURCE_PATH_CHANGED')
                before = parse_sha256sum(
                    call([*selector, 'shell', 'sha256sum', source_path]), source_path,
                )
                call([*selector, 'pull', source_path, str(destination)])
                data = destination.read_bytes()
                if len(data) != sizes[observed_path]:
                    raise ValueError('LOCAL_SIZE_MISMATCH')
                local_sha = sha256(data)
                if local_sha != before:
                    raise ValueError('LOCAL_HASH_MISMATCH')
                validate_arm64_elf(data)
                resolved_after = parse_single_value(
                    call([*selector, 'shell', 'readlink', '-f', observed_path]),
                )
                if resolved_after != source_path:
                    raise ValueError('SOURCE_PATH_CHANGED')
                after = parse_sha256sum(
                    call([*selector, 'shell', 'sha256sum', source_path]), source_path,
                )
                if after != before:
                    raise ValueError('SOURCE_HASH_CHANGED')
            except RunnerStop as exc:
                destination.unlink(missing_ok=True)
                report['errors'].append({
                    'observed_path': observed_path, 'source_path': source_path,
                    'code': exc.code, 'sha256_before': before,
                    'sha256_local': local_sha, 'sha256_after': after,
                })
                raise
            except (OSError, ValueError) as exc:
                destination.unlink(missing_ok=True)
                report['errors'].append({'observed_path': observed_path, 'source_path': source_path,
                                         'code': str(exc)[:80],
                                         'sha256_before': before, 'sha256_local': local_sha,
                                         'sha256_after': after})
                continue

            try:
                metadata_remaining = duration_limit - (monotonic_fn() - started)
                if metadata_remaining <= 0:
                    raise RunnerStop('PARTIAL_TIMEOUT', 'DURATION_LIMIT')
                elf_metadata = dict(metadata_reader(
                    destination, timeout=min(20.0, metadata_remaining),
                ))
            except RunnerStop:
                raise
            except Exception:
                elf_metadata = {
                    'build_id': None, 'exported_symbols': [], 'undefined_symbols': [],
                    'dt_needed': [], 'bridge_symbol_hits': [], 'metadata_status': 'UNAVAILABLE',
                }
                report['errors'].append({'observed_path': observed_path, 'source_path': source_path,
                                         'code': 'ELF_METADATA_UNAVAILABLE'})
            else:
                symbol_fields = ('exported_symbols', 'undefined_symbols', 'dt_needed')
                if (elf_metadata.get('metadata_status') != 'OBSERVED'
                        or not elf_metadata.get('build_id')
                        or any(not isinstance(elf_metadata.get(key), list) for key in symbol_fields)):
                    report['errors'].append({'observed_path': observed_path, 'source_path': source_path,
                                             'code': 'ELF_METADATA_PARTIAL'})
            info = {
                'observed_path': observed_path,
                'source_path': source_path,
                'sha256_before': before,
                'sha256': local_sha,
                'sha256_after': after,
                'bytes': len(data),
                'entry': observed_path.lstrip('/'),
                'elf_class': 'ELF64',
                'elf_machine': 'AArch64',
                'elf': elf_metadata,
            }
            report['files'].append(info)

        report['requested_count'] = len(candidates)
        report['verified_count'] = len(report['files'])
        if (report['errors'] or found['limited_roots'] or found['candidate_limitations']
                or len(report['files']) != len(candidates)):
            report['status'] = 'PARTIAL' if report['files'] else 'BLOCKED'
        else:
            report['status'] = 'PACKAGE_READY'
    except RunnerStop as exc:
        report['errors'].append({'code': exc.code})
        report['status'] = exc.status if not report['files'] else 'PARTIAL'
    except Exception as exc:
        # Do not retain adb stdout/stderr or exception text that may contain
        # serials or unrelated device paths.
        report['errors'].append({'code': type(exc).__name__.upper()})
        report['status'] = 'PARTIAL' if report['files'] else 'BLOCKED'
    report['finished_utc'] = datetime.now(timezone.utc).isoformat()
    report['verified_count'] = len(report['files'])
    report['requested_count'] = len(report.get('candidates', []))
    return report


def _load_approval(path: Path) -> Mapping[str, Any]:
    raw = path.read_bytes()
    if len(raw) > MAX_APPROVAL_BYTES:
        raise ValueError('Approval record exceeds size limit')
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError('Approval record must be an object')
    return value


def main(argv: list[str] | None = None, *, input_fn: Callable[[str], str] = input) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    selector = parser.add_mutually_exclusive_group()
    selector.add_argument('--serial')
    selector.add_argument('--transport-id')
    parser.add_argument('--approval-file', type=Path)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args(argv)
    if args.dry_run:
        print(json.dumps(dry_run_plan(), separators=(',', ':')))
        return 0
    if args.serial is None and args.transport_id is None:
        print('BLOCKED: explicit --serial or --transport-id is required', file=sys.stderr)
        return 2
    if args.approval_file is None:
        print('BLOCKED: a separate M2.7B approval file is required', file=sys.stderr)
        return 2
    try:
        device_args = device_selector(serial=args.serial, transport_id=args.transport_id)
        approval = _load_approval(args.approval_file)
        if not _valid_approval_limits(approval):
            raise ValueError('Approval limits exceed the M2.7B action caps')
        if not sys.stdin.isatty():
            print('BLOCKED: interactive exact lowercase yes is required', file=sys.stderr)
            return 2
        effective_duration = min(MAX_DURATION_SECONDS, approval['max_duration_seconds'])
        effective_observations = min(MAX_OBSERVATIONS, approval['max_observations'])
        print(
            f'Device: {TARGET_DEVICE}\n'
            f'Action: {ACTION}\n'
            f'Maximum duration: {effective_duration} seconds\n'
            f'Maximum ADB observations: {effective_observations}\n'
            f'Maximum candidates: {MAX_CANDIDATES}\n'
            f'Maximum ELF transfer: {MAX_PROVIDER_FILE_BYTES // (1024 * 1024)} MiB each, '
            f'{MAX_TOTAL_PROVIDER_BYTES // (1024 * 1024)} MiB total\n'
            'Required identity: exact owner-bound firmware fingerprint and arm64-v8a ABI'
        )
        if input_fn('Confirm operation (yes/no): ') != 'yes':
            print('BLOCKED: confirmation rejected', file=sys.stderr)
            return 2
        adb_executable = resolve_adb_executable()
    except Exception as exc:
        print(f'BLOCKED_PREFLIGHT: {type(exc).__name__}', file=sys.stderr)
        return 2

    name = datetime.now(timezone.utc).strftime('p3a-m27b-camx-core-%Y%m%dT%H%M%SZ-') + uuid4().hex[:8]
    # Temporary local staging is deleted on success, partial result, and SMB
    # publication failure. Canonical SMB is the only persistent ELF location.
    with tempfile.TemporaryDirectory(prefix='p3a-m27b-camx-private-') as temp:
        stage = Path(temp)
        report = collect_provider(
            approval, 'yes', device_args, stage,
            executor=native_adb_executor(adb_executable), metadata_reader=readelf_metadata,
            direct_user_instruction=True,
        )
        try:
            package = build_zip(stage, report)
            receipt = canonical_commit(Path(ROOT), name, report, package)
        except Exception:
            print('PUBLICATION_BLOCKED: canonical SMB commit failed; no fallback used', file=sys.stderr)
            return 3
        print(json.dumps(receipt, separators=(',', ':')))
        return 0 if report['status'] == 'PACKAGE_READY' else 1


if __name__ == '__main__':
    raise SystemExit(main())
