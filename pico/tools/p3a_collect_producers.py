"""P3-A: extract SHA-pinned QuickCamera producer ELFs read-only, then publish privately."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import struct
import sys
from uuid import uuid4
import zipfile

if __package__:
    from pico.tools.p3a_quickcamera_inventory import (ROOT, CAMERA_SHA, REPO,
                                                       SAFETY, adb, root_shell, digest_line)
else:
    from p3a_quickcamera_inventory import (ROOT, CAMERA_SHA, REPO,
                                            SAFETY, adb, root_shell, digest_line)

SCHEMA = 'p3a.producer_package.v1'
SAFE_PATH = re.compile(r'^/(?:system|vendor)/lib64/(?:[A-Za-z0-9_.@+-]+/)*[A-Za-z0-9_.@+-]+\.so$')
SAFE_PACKAGE_NAME = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$')


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def valid_path(path: str) -> bool:
    return isinstance(path, str) and bool(SAFE_PATH.fullmatch(path)) and '..' not in PurePosixPath(path).parts


def validate_arm64_elf(content: bytes) -> None:
    if len(content) < 64 or content[:4] != b'\x7fELF':
        raise ValueError('Not a valid ELF file')
    if content[4] != 2 or content[5] != 1 or struct.unpack_from('<H', content, 18)[0] != 183:
        raise ValueError('ELF is not AArch64/ELF64 little-endian')


def trusted_inventory(path: Path) -> tuple[dict, str]:
    sidecar = path.with_suffix('.sha256')
    if not sidecar.is_file():
        raise ValueError('Inventory sidecar is missing: not a committed result')
    parts = sidecar.read_text(encoding='ascii').strip().split()
    if len(parts) != 2 or not re.fullmatch('[a-f0-9]{64}', parts[0]) or parts[1] != path.name:
        raise ValueError('Invalid inventory sha256 sidecar')
    raw = path.read_bytes()
    actual = sha256(raw)
    if actual != parts[0]:
        raise ValueError('Inventory sha256 readback mismatch')
    obj = json.loads(raw)
    if obj.get('status') != 'INVENTORY_READY' or obj.get('p2_sha_match') is not True:
        raise ValueError('Inventory is not ready or P2 SHA was not verified')
    camera_paths = obj.get('p2_exact_camera_paths')
    if not isinstance(camera_paths, list) or len(camera_paths) != 1 or not valid_path(camera_paths[0]):
        raise ValueError('Ambiguous or invalid P2 camera path')
    if obj.get('pvr_candidate_hashes', {}).get(camera_paths[0]) != CAMERA_SHA:
        raise ValueError('P2 camera SHA claim does not match pinned hash')
    if obj.get('safety') != SAFETY:
        raise ValueError('Inventory safety gates differ')
    return obj, actual


def pick_latest_inventory(root: Path) -> Path:
    for candidate in sorted(root.glob('p3a-inventory-*.json'), reverse=True):
        try:
            trusted_inventory(candidate)
            return candidate
        except (ValueError, OSError, json.JSONDecodeError):
            continue
    raise FileNotFoundError('No SHA-committed INVENTORY_READY P3-A report in canonical SMB root')


def select_producers(inventory: dict) -> dict[str, str]:
    expected_paths = set()
    deps = inventory.get('same_abi_dependency_paths')
    extras = inventory.get('additional_producer_candidates')
    digests = inventory.get('producer_hashes')
    if not isinstance(deps, dict) or not isinstance(extras, list) or not isinstance(digests, dict):
        raise ValueError('Inventory producer data is incomplete')
    pinned = inventory.get('p2_pinned_dt_needed')
    if not isinstance(pinned, list) or not pinned or set(pinned) != set(deps):
        raise ValueError('Missing or inconsistent pinned DT_NEEDED entries')
    for dep in pinned:
        candidates = deps[dep]
        if not isinstance(candidates, list) or not candidates:
            raise ValueError('No matching same-ABI dependency for ' + dep)
        for p in candidates:
            if PurePosixPath(p).name != dep:
                raise ValueError('Library path does not match DT_NEEDED basename: ' + p)
            expected_paths.add(p)
    if not extras:
        raise ValueError('HIDL/Core producer candidates missing from inventory')
    for p in extras:
        expected_paths.add(p)
    if expected_paths != set(digests):
        raise ValueError('Producer path set does not match inventoried hashes')
    for p, digest in digests.items():
        if not valid_path(p) or not re.fullmatch('[0-9a-f]{64}', str(digest)):
            raise ValueError('Invalid producer path or SHA-256 entry')
    return {p: digests[p] for p in sorted(expected_paths)}


def device_hash(serial: str, path: str) -> str:
    actual = digest_line(root_shell(serial, 'sha256sum ' + path, timeout=40))
    if actual is None:
        raise ValueError('No valid remote sha256sum for ' + path)
    return actual


def copy_one(serial: str, remote_path: str, destination: Path, expected: str,
             *, adb_pull=adb, hasher=device_hash) -> dict:
    if not valid_path(remote_path):
        raise ValueError('Unsafe ELF device path')
    before = hasher(serial, remote_path)
    if before != expected:
        raise ValueError('Remote SHA-256 does not match inventory (pre-pull)')
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Paths are from committed device inventory; ADB pull reads only.
    adb_pull(serial, 'pull', remote_path, str(destination), timeout=120)
    data = destination.read_bytes()
    validate_arm64_elf(data)
    if sha256(data) != expected:
        raise ValueError('Locally retrieved ELF differs from inventory SHA-256')
    if hasher(serial, remote_path) != expected:
        raise ValueError('Remote SHA changed during extraction')
    return {'source': remote_path, 'entry': remote_path.lstrip('/'),
            'sha256': expected, 'bytes': len(data)}


def collect(inventory: dict, inventory_sha: str, serial: str, stage: Path,
            *, read_device_hash=device_hash, pull=adb, read_getprop=adb) -> dict:
    report = {'schema': SCHEMA, 'created_utc': datetime.now(timezone.utc).isoformat(),
              'inventory_sha256': inventory_sha, 'source_fingerprint':
              inventory.get('device', {}).get('ro.build.fingerprint'),
              'safety': SAFETY, 'status': 'BLOCKED', 'errors': [], 'files': [],
              'timestamp_producer_verified': False, 'physical_event_verified': False}
    try:
        producers = select_producers(inventory)
        if read_getprop(serial, 'get-state', timeout=15) != 'device':
            raise RuntimeError('ADB target is not connected')
        current = read_getprop(serial, 'shell', 'getprop', 'ro.build.fingerprint', timeout=15)
        if not current or current != report['source_fingerprint']:
            raise ValueError('PICO firmware fingerprint changed since inventory')
        for path, expected in producers.items():
            destination = stage / path.lstrip('/')
            try:
                info = copy_one(serial, path, destination, expected,
                                adb_pull=pull, hasher=read_device_hash)
                report['files'].append(info)
            except (Exception, KeyboardInterrupt) as exc:
                report['errors'].append({'path': path, 'reason': f'{type(exc).__name__}: {str(exc)[:200]}'})
                destination.unlink(missing_ok=True)
        report['requested_count'] = len(producers)
        report['verified_count'] = len(report['files'])
        report['status'] = ('PACKAGE_READY' if not report['errors'] and
                            len(report['files']) == len(producers) else
                            'PARTIAL' if report['files'] else 'BLOCKED')
    except (Exception, KeyboardInterrupt) as exc:
        report['errors'].append({'stage': 'preflight', 'reason': f'{type(exc).__name__}: {str(exc)[:260]}'})
        report['status'] = 'PARTIAL' if report['files'] else 'BLOCKED'
    return report


def build_zip(stage: Path, report: dict) -> bytes:
    """Package only verified binaries; retain FAIL/PARTIAL diagnostics."""
    bio = io.BytesIO()
    with zipfile.ZipFile(bio, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for f in report['files']:
            entry = f['entry']
            data = (stage / entry).read_bytes()
            if sha256(data) != f['sha256']:
                raise IOError('Staged ELF hash changed before archival')
            z.writestr(entry, data)
        z.writestr('manifest.json', json.dumps(report, indent=2, ensure_ascii=False) + '\n')
    return bio.getvalue()


def canonical_commit(root: Path, name: str, report: dict, package: bytes,
                     *, readback=None) -> dict:
    """Canonical SMB .part -> independent readback SHA -> rename -> .sha256 LAST."""
    if not isinstance(name, str) or not SAFE_PACKAGE_NAME.fullmatch(name):
        raise ValueError('Invalid canonical package name')
    root.mkdir(parents=True, exist_ok=True)
    readback = readback or (lambda p: p.read_bytes())
    manifest = (json.dumps(report, indent=2, ensure_ascii=False) + '\n').encode('utf-8')
    outputs = [(name + '.zip', package), (name + '.manifest.json', manifest)]
    hashes = {}
    sidecar = root / (name + '.sha256')
    all_finals = [root / filename for filename, _ in outputs] + [sidecar]
    all_parts = [root / (filename + '.part') for filename, _ in outputs]
    all_parts.append(root / (name + '.sha256.part'))
    # A generated run name is expected to be unique. Refuse collisions rather
    # than replacing an earlier publication or following a planted .part link.
    if any(path.exists() or path.is_symlink() for path in (*all_finals, *all_parts)):
        raise FileExistsError('Canonical package name already has published or temporary files')

    created_parts: list[Path] = []
    try:
        for filename, content in outputs:
            final = root / filename
            part = root / (filename + '.part')
            digest = sha256(content)
            with part.open('xb') as stream:
                created_parts.append(part)
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            if sha256(readback(part)) != digest:
                raise IOError('Canonical SMB .part readback hash mismatch: ' + filename)
            if final.exists() or final.is_symlink():
                raise FileExistsError('Canonical destination appeared during publication')
            os.replace(part, final)
            created_parts.remove(part)
            if sha256(readback(final)) != digest:
                raise IOError('Canonical SMB final readback mismatch: ' + filename)
            hashes[filename] = digest

        body = ''.join(f'{digest}  {filename}\n' for filename, digest in hashes.items()).encode('ascii')
        part = root / (name + '.sha256.part')
        with part.open('xb') as stream:
            created_parts.append(part)
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())
        if sha256(readback(part)) != sha256(body):
            raise IOError('Canonical SMB sidecar .part readback failed')
        if sidecar.exists() or sidecar.is_symlink():
            raise FileExistsError('Canonical sidecar destination appeared during publication')
        os.replace(part, sidecar)  # FINAL commit indicator
        created_parts.remove(part)
        if sha256(readback(sidecar)) != sha256(body):
            raise IOError('Canonical SMB sidecar verification failed')
    except BaseException as failure:
        cleanup_failed = False
        for part in created_parts:
            try:
                part.unlink(missing_ok=True)
            except OSError:
                cleanup_failed = True
        if cleanup_failed:
            raise IOError('Canonical publication failed and temporary-file cleanup was incomplete') from failure
        raise
    files = report.get('files', [])
    verified_libraries = len(files) if isinstance(files, (list, tuple)) else 0
    return {'status': report['status'], 'zip': str(root / (name + '.zip')),
            'manifest': str(root / (name + '.manifest.json')), 'sha256': str(sidecar),
            'package_digest': hashes[name + '.zip'], 'verified_libraries': verified_libraries,
            'requested_libraries': report.get('requested_count', 0),
            'errors': report.get('errors', [])}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--serial', default='192.168.23.12:5555')
    parser.add_argument('--inventory', type=Path, help='SHA-committed canonical P3-A inventory JSON')
    parser.add_argument('--output-root', type=Path, default=Path(ROOT))
    args = parser.parse_args(argv)
    try:
        source_path = args.inventory or pick_latest_inventory(args.output_root)
        source, source_sha = trusted_inventory(source_path)
    except Exception as exc:
        print('INVENTORY_PREFLIGHT_BLOCKED: ' + str(exc), file=sys.stderr)
        return 2
    name = datetime.now(timezone.utc).strftime('p3a-producers-%Y%m%dT%H%M%SZ-') + uuid4().hex[:8]
    stage = REPO / 'pico/build' / (name + '-private')
    stage.mkdir(parents=True, exist_ok=False)
    report = collect(source, source_sha, args.serial, stage)
    try:
        package = build_zip(stage, report)
        outcome = canonical_commit(args.output_root, name, report, package)
    except Exception as exc:
        print('CANONICAL_SMB_PUBLICATION_FAILED (no fallback): ' + str(exc), file=sys.stderr)
        return 3
    outcome['local_private_stage'] = str(stage)
    print(json.dumps(outcome, ensure_ascii=False))
    return 0 if report['status'] == 'PACKAGE_READY' else 1


if __name__ == '__main__':
    sys.exit(main())
