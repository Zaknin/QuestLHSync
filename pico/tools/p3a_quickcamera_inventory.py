"""P3-A read-only QuickCamera/HIDL same-firmware inventory; no ELF pulls."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from uuid import uuid4

REPO = Path(__file__).resolve().parents[2]
ROOT = r'\\192.168.23.63\Torrents\Codex\PicoLHSync\P3-A'
CAMERA_SHA = 'cf9e507f412ec33d62c2f720669fcdd093f1822c9cbf3adefd0a26a6b4d072ee'
SAFETY = dict(observe_only=True, exact_time=False, live_lighthouse_correction_allowed=False,
              mapping_verified=False, pose_verified=False)
ROOTS = ('/vendor', '/system', '/odm', '/product', '/system_ext', '/apex')


def cmd(argv, timeout=120):
    r = subprocess.run(argv, capture_output=True, text=True, encoding='utf-8',
                       errors='replace', timeout=timeout, check=False)
    if r.returncode:
        raise RuntimeError(f'exit={r.returncode}: {(r.stderr or r.stdout).strip()[:240]}')
    return r.stdout.strip()


def adb(serial, *args, timeout=120):
    return cmd(['adb', '-s', serial, *args], timeout=timeout)


def root_shell(serial, command, timeout=120):
    return adb(serial, 'shell', 'su', '-c', command, timeout=timeout)


def parse_needed(text):
    return sorted(set(re.findall(r'\(NEEDED\).*?\[([^\]]+)\]', text)))


def parse_inventory(text):
    paths = sorted(set(p.strip() for p in text.splitlines()
                       if re.fullmatch(r'/[a-zA-Z0-9_./+@=-]+\.so', p.strip())))
    selected = sorted(p for p in paths if re.search(r'quickcamera|pvrtracking|camera.*hidl|hidl.*camera',
                                                    p.rsplit('/', 1)[-1], re.I))
    return paths, selected


def match_paths(names, paths):
    return {name: [p for p in paths if p.rsplit('/', 1)[-1] == name] for name in names}


def pinned_needed():
    local = sorted((REPO / 'pico/build').glob('p2-static-clock-private-*/libpvrtrackingcamera.so'), reverse=True)
    trusted = next((p for p in local if hashlib.sha256(p.read_bytes()).hexdigest() == CAMERA_SHA), None)
    if trusted is None:
        raise RuntimeError('SHA-pinned P2 camera ELF missing from pico/build')
    sdk = Path(os.environ.get('ANDROID_HOME') or os.environ.get('ANDROID_SDK_ROOT') or
               os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Android', 'Sdk'))
    bins = sorted((sdk / 'ndk').glob('*/toolchains/llvm/prebuilt/windows-x86_64/bin/llvm-readelf.exe'), reverse=True)
    if not bins:
        raise RuntimeError('Android NDK llvm-readelf.exe not found')
    needed = [n for n in parse_needed(cmd([str(bins[0]), '--dynamic', str(trusted)], 30))
              if 'quickcamera' in n.lower()]
    if not needed:
        raise RuntimeError('No QuickCamera DT_NEEDED in pinned P2 camera ELF')
    return needed


def digest_line(raw):
    m = re.match(r'^([a-fA-F0-9]{64})\s+/', raw.strip())
    return m.group(1).lower() if m else None


def inventory(serial):
    result = dict(schema='p3a.inventory.v1', utc=datetime.now(timezone.utc).isoformat(),
                  safety=SAFETY, status='BLOCKED', errors=[], producer_timestamp_proven=False,
                  physical_exposure_event_proven=False, vendor_binaries_copied=False)
    try:
        if adb(serial, 'get-state', timeout=15) != 'device':
            raise RuntimeError('ADB device not ready')
        result['device'] = {key: adb(serial, 'shell', 'getprop', key, timeout=15)
                            for key in ('ro.build.fingerprint', 'ro.build.version.release',
                                        'ro.build.version.incremental', 'ro.build.version.sdk')}
        if 'uid=0(' not in root_shell(serial, 'id', timeout=15):
            raise RuntimeError('Root shell unavailable')
        # Only verified existing Android mount roots. Never presume a library path.
        shell = 'for d in ' + ' '.join(ROOTS) + '; do if [ -d "$d" ]; then find "$d" \\( -type f -o -type l \\); fi; done'
        paths, candidates = parse_inventory(root_shell(serial, shell, timeout=180))
        result['shared_object_count'] = len(paths)
        result['candidate_paths'] = candidates
        if not paths:
            raise RuntimeError('No installed ELF library paths discovered')
        needed = pinned_needed()
        result['p2_pinned_dt_needed'] = needed
        matches = match_paths(needed + ['libpvrtrackingcamera.so'], paths)
        result['exact_matches'] = matches
        if len(matches['libpvrtrackingcamera.so']) != 1:
            raise RuntimeError('Installed libpvrtrackingcamera.so missing or ambiguous')
        cam = matches['libpvrtrackingcamera.so'][0]
        actual_sha = digest_line(root_shell(serial, 'sha256sum ' + cam, timeout=30))
        result['device_pvr_camera_sha256'] = actual_sha
        result['p2_sha_match'] = actual_sha == CAMERA_SHA
        if actual_sha != CAMERA_SHA:
            raise RuntimeError('Installed PVR camera SHA differs from P2 binary')
        result['producer_hashes'] = {}
        for name in needed:
            if not matches[name]:
                result['errors'].append('Not found: ' + name)
            for p in matches[name]:
                result['producer_hashes'][p] = digest_line(root_shell(serial, 'sha256sum ' + p, timeout=30))
                if result['producer_hashes'][p] is None:
                    result['errors'].append('No device SHA256: ' + p)
        result['status'] = 'INVENTORY_READY' if not result['errors'] else 'PARTIAL'
    except (Exception, KeyboardInterrupt) as exc:
        result['errors'].append(type(exc).__name__ + ': ' + str(exc)[:350])
        result['status'] = 'PARTIAL' if result.get('candidate_paths') else 'BLOCKED'
    return result


def publish(record, root=ROOT):
    base = Path(root)
    base.mkdir(parents=True, exist_ok=True)
    name = datetime.now(timezone.utc).strftime('p3a-inventory-%Y%m%dT%H%M%SZ-') + uuid4().hex[:8]
    data = base / (name + '.json')
    partial = base / (name + '.json.part')
    blob = (json.dumps(record, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    sha = hashlib.sha256(blob).hexdigest()
    partial.write_bytes(blob)
    if hashlib.sha256(partial.read_bytes()).hexdigest() != sha:
        raise IOError('SMB .part integrity check failed')
    os.replace(partial, data)
    if hashlib.sha256(data.read_bytes()).hexdigest() != sha:
        raise IOError('SMB final evidence integrity check failed')
    sidecar = base / (name + '.sha256')
    sidecar_part = base / (name + '.sha256.part')
    sidecar_part.write_text(f'{sha}  {data.name}\n', encoding='ascii')
    commit_sha = hashlib.sha256(sidecar_part.read_bytes()).hexdigest()
    if hashlib.sha256(sidecar_part.read_bytes()).hexdigest() != commit_sha:
        raise IOError('SMB sidecar .part integrity failed')
    os.replace(sidecar_part, sidecar)  # published last
    if hashlib.sha256(sidecar.read_bytes()).hexdigest() != commit_sha:
        raise IOError('SMB final sidecar integrity failed')
    return dict(status=record['status'], evidence=str(data), sha256=str(sidecar),
                digest=sha, errors=record['errors'], installed_dependencies=record.get('p2_pinned_dt_needed', []))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--serial', default='192.168.23.12:5555')
    parser.add_argument('--output-root', default=ROOT)
    args = parser.parse_args()
    report = inventory(args.serial)
    try:
        summary = publish(report, args.output_root)
    except Exception as exc:
        print(f'CANONICAL SMB PUBLISH FAILED, no fallback: {exc}', file=sys.stderr)
        return 3
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if report['status'] == 'INVENTORY_READY' else 1


if __name__ == '__main__':
    sys.exit(main())
