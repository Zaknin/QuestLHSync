#!/usr/bin/env python3
"""P3-A4E: decode ARM64 callback-vtable ELF relocations without device access.

Reads the owner's SHA-pinned, PRIVATE PVR ELF and SHA-verified P3-A4D manifest.
Never uploads ELF bytes. Does not communicate with Pico/SteamVR.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import uuid
import zipfile
from datetime import datetime, timezone

PIN_PVR = 'cf9e507f412ec33d62c2f720669fcdd093f1822c9cbf3adefd0a26a6b4d072ee'
CANONICAL = r'\\192.168.23.63\Torrents\Codex\PicoLHSync\P3-A'
SLOTS_LOW, SLOTS_HIGH = 0x752B0, 0x75330
R_AARCH64_RELATIVE = 1027
PT_LOAD, PF_X = 1, 1
SHT_RELA, SHT_REL, SHT_RELR, SHT_ANDROID_RELR = 4, 9, 19, 0x6fffff00


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


class Elf64Arm:
    """Minimal bounds-checked AArch64 ELF64 parser (no external dependencies)."""

    def __init__(self, raw: bytes):
        self.raw = raw
        if len(raw) < 64 or raw[:6] != b'\x7fELF\x02\x01':
            raise ValueError('Expected little-endian ELF64')
        h = self.unpack('<16sHHIQQQIHHHHHH', 0)
        if h[2] != 183:  # EM_AARCH64
            raise ValueError('Wrong ELF machine: expected AArch64')
        phoff, shoff, phentsize, phnum, shentsize, shnum = h[5], h[6], h[9], h[10], h[11], h[12]
        if phnum > 4096 or shnum > 65534 or phentsize < 56 or shentsize < 64:
            raise ValueError('Invalid ELF header table dimensions')
        self.segments = []
        for i in range(phnum):
            item = self.unpack('<IIQQQQQQ', phoff + i * phentsize)
            typ, flags, offset, vaddr, _paddr, filesz, memsz, _align = item
            if typ == PT_LOAD:
                if filesz > memsz or offset + filesz > len(raw):
                    raise ValueError('Invalid ELF LOAD segment extent')
                self.segments.append((flags, offset, vaddr, filesz, memsz))
        if not self.segments:
            raise ValueError('ELF has no LOAD segments')
        self.sections = []
        for i in range(shnum):
            x = self.unpack('<IIQQQQIIQQ', shoff + i * shentsize)
            _name, typ, _flags, _addr, offset, size, _link, _info, _align, entsize = x
            if size and offset + size > len(raw) and typ != 8:  # NOBITS
                raise ValueError('Invalid ELF section extent')
            self.sections.append((typ, offset, size, entsize))

    def unpack(self, fmt: str, offset: int):
        size = struct.calcsize(fmt)
        if offset < 0 or offset + size > len(self.raw):
            raise ValueError('ELF read outside file')
        return struct.unpack_from(fmt, self.raw, offset)

    def va_to_file(self, address: int, size: int = 8) -> int:
        for _flags, offset, vaddr, filesz, _memsz in self.segments:
            if address >= vaddr and address + size <= vaddr + filesz:
                return offset + address - vaddr
        raise ValueError(f'Unmapped ELF virtual address 0x{address:x}')

    def executable(self, address: int) -> bool:
        return any(flags & PF_X and vaddr <= address < vaddr + filesz
                   for flags, _off, vaddr, filesz, _memsz in self.segments)

    def relocated_slots(self) -> dict[int, dict]:
        """Parse normal REL/RELA and ELF/Android RELR compact relocation bitmaps.

        Important: Android 10 vendor binaries often use ANDROID_RELR for
        R_AARCH64_RELATIVE. llvm-readelf expands them into apparent RELATIVE
        entries without addends, and SHT_RELA/SHT_REL-only parsing misses them.
        """
        slots: dict[int, dict] = {}

        def record(slot: int, fmt: str, source: str, addend: int | None) -> None:
            if not (SLOTS_LOW <= slot < SLOTS_HIGH):
                return
            if slot & 7:
                raise ValueError(f'Unaligned relative relocation slot 0x{slot:x}')
            if slot in slots:
                raise ValueError(f'Duplicate relative relocation for 0x{slot:x}')
            raw_word = self.unpack('<Q', self.va_to_file(slot, 8))[0]
            candidate = addend if addend is not None else raw_word
            executable = candidate >= 0 and self.executable(candidate)
            slots[slot] = {
                'slot': f'0x{slot:x}',
                'relocation_format': fmt,
                'addend_source': source,
                'addend_hex': f'0x{candidate & 0xffffffffffffffff:x}',
                'raw_slot_hex': f'0x{raw_word:x}',
                'candidate_executable': executable,
                'candidate_address': candidate if executable else None,
            }

        for typ, off, size, entsize in self.sections:
            if typ in (SHT_RELR, SHT_ANDROID_RELR):
                if size % 8 or entsize not in (0, 8):
                    raise ValueError('Invalid ELF RELR section dimensions')
                if size // 8 > 2_000_000:
                    raise ValueError('Excessive ELF RELR entries')
                base: int | None = None
                fmt = 'ANDROID_RELR' if typ == SHT_ANDROID_RELR else 'RELR'
                for pos in range(off, off + size, 8):
                    word = self.unpack('<Q', pos)[0]
                    if (word & 1) == 0:
                        if word & 7:
                            raise ValueError('Unaligned ELF RELR anchor')
                        record(word, fmt, 'implicit_slot_contents', None)
                        base = word + 8
                    else:
                        if base is None:
                            raise ValueError('ELF RELR bitmap before anchor')
                        # Bits 1..63 describe 63 successive pointer-sized slots.
                        for bit in range(63):
                            if word & (1 << (bit + 1)):
                                record(base + bit * 8, fmt, 'implicit_slot_contents', None)
                        base += 63 * 8
                continue
            if typ not in (SHT_REL, SHT_RELA):
                continue
            record_size = 24 if typ == SHT_RELA else 16
            stride = entsize or record_size
            if stride < record_size or size % stride:
                raise ValueError('Invalid ELF relocation record size')
            if size // stride > 2_000_000:
                raise ValueError('Excessive ELF relocation entries')
            for pos in range(off, off + size, stride):
                if typ == SHT_RELA:
                    slot, info, addend = self.unpack('<QQq', pos)
                else:
                    slot, info = self.unpack('<QQ', pos)
                    addend = None
                if (info & 0xffffffff) != R_AARCH64_RELATIVE:
                    continue
                record(slot, 'RELA' if typ == SHT_RELA else 'REL',
                       'explicit_rela' if typ == SHT_RELA else 'implicit_slot_contents',
                       addend)
        return slots


def check_owner_manifest(json_path: Path, expected_pvr_sha: str = PIN_PVR) -> tuple[dict, dict]:
    """Reject partial/unsidecarred source artifacts and unfrozen Pico gates."""
    sidecar = json_path.with_suffix('.sha256')
    archive = json_path.with_suffix('.zip')
    if not sidecar.is_file() or not archive.is_file():
        raise ValueError('Missing completed archive or final SHA-256 marker')
    marker = sidecar.read_text(encoding='ascii')
    entries = {}
    for line in marker.splitlines():
        m = re.fullmatch(r'([0-9a-f]{64})\s+([^\\/]+)', line.strip())
        if not m:
            raise ValueError('Invalid integrity marker')
        if m.group(2) in entries:
            raise ValueError('Duplicate integrity entry')
        entries[m.group(2)] = m.group(1)
    if set(entries) != {json_path.name, archive.name}:
        raise ValueError('Unexpected manifest marker entries')
    for path in (json_path, archive):
        if sha256_file(path) != entries[path.name]:
            raise ValueError(f'Integrity mismatch: {path.name}')
    evidence = json.loads(json_path.read_text(encoding='utf-8-sig'))
    if (evidence.get('schema') != 'p3a4.offline.bridge.v3'
            or evidence.get('status') != 'TRACE_CAPTURED_NOT_PROVEN'
            or evidence.get('input_sha256', {}).get('pvr') != expected_pvr_sha):
        raise ValueError('Not the expected P3-A4D source evidence')
    for name, expected in [('observe_only', True), ('exact_time', False),
                           ('live_lighthouse_correction_allowed', False),
                           ('mapping_verified', False), ('pose_verified', False),
                           ('frame_meta_bridge_verified', False)]:
        if evidence.get(name) is not expected:
            raise ValueError(f'Gate mismatch: {name}')
    return evidence, entries


def find_pvr(build: Path) -> Path:
    for candidate in sorted(build.glob('p2-static-clock-private-*/libpvrtrackingcamera.so'), reverse=True):
        if candidate.is_file() and sha256_file(candidate) == PIN_PVR:
            return candidate
    raise FileNotFoundError('Pinned P2 private libpvrtrackingcamera.so not found')


def find_manifest(output: Path) -> Path:
    # Only final markers from the observed Windows run are eligible.
    for f in sorted(output.glob('p3a4-bridge-*.json'), reverse=True):
        try:
            check_owner_manifest(f)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        return f
    raise FileNotFoundError('No verified P3-A4D schema-v3 manifest / SHA marker')


def find_objdump() -> str:
    roots = [Path(os.environ[v]) for v in ('ANDROID_HOME', 'ANDROID_SDK_ROOT') if os.environ.get(v)]
    roots.append(Path(os.environ.get('LOCALAPPDATA', str(Path.home() / 'AppData' / 'Local'))) / 'Android' / 'Sdk')
    for sdk in roots:
        tools = sorted(sdk.glob('ndk/*/toolchains/llvm/prebuilt/windows-x86_64/bin/llvm-objdump.exe'), reverse=True)
        if tools:
            return str(tools[0])
    direct = shutil.which('llvm-objdump')
    if direct:
        return direct
    raise FileNotFoundError('llvm-objdump is not available in Android NDK')


def atomic_publish(stage: Path, destination: Path, run: str, report: dict, excerpts: dict[str, str]) -> dict:
    stage.mkdir(parents=True, exist_ok=False)
    report_path = stage / 'manifest.json'
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    for name, body in excerpts.items():
        (stage / name).write_text(body, encoding='utf-8')
    archive = stage / f'{run}.zip'
    with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as z:
        z.write(report_path, 'manifest.json')
        for name in sorted(excerpts):
            z.write(stage / name, name)
    destination.mkdir(parents=True, exist_ok=True)
    published = []
    for source, name in ((archive, archive.name), (report_path, f'{run}.json')):
        part = destination / f'{name}.part'
        final = destination / name
        shutil.copyfile(source, part)
        digest = sha256_file(source)
        if sha256_file(part) != digest:
            raise IOError('SMB staged file integrity failure')
        os.replace(part, final)
        if sha256_file(final) != digest:
            raise IOError('SMB published file integrity failure')
        published.append((digest, name))
    marker = destination / f'{run}.sha256'
    marker_tmp = destination / f'{run}.sha256.part'
    marker_tmp.write_text(''.join(f'{digest}  {name}\n' for digest, name in published), encoding='ascii')
    expected = sha256_file(marker_tmp)
    os.replace(marker_tmp, marker)
    if sha256_file(marker) != expected:
        raise IOError('SMB marker integrity failure')
    return {'zip': str(destination / archive.name), 'manifest': str(destination / f'{run}.json'),
            'marker': str(marker)}


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-root', type=Path, default=Path(CANONICAL))
    parser.add_argument('--manifest', type=Path, help='SHA-verified v3 owner manifest; auto-locate newest if omitted')
    parser.add_argument('--pvr', type=Path, help='Private ELF path; SHA-pinned in all modes')
    args = parser.parse_args(argv)
    repo = Path(__file__).resolve().parents[2]
    build = repo / 'pico' / 'build'
    pvr = args.pvr if args.pvr is not None else find_pvr(build)
    if sha256_file(pvr) != PIN_PVR:
        raise ValueError('PVR source hash does not match the pinned P2 ELF')
    manifest = args.manifest if args.manifest is not None else find_manifest(args.output_root)
    owner, owner_hashes = check_owner_manifest(manifest)
    elf = Elf64Arm(pvr.read_bytes())
    decoded = elf.relocated_slots()
    target_slots = set()
    for item in owner['callback_relocations']:
        if item['type'] != 'R_AARCH64_RELATIVE':
            continue
        slot = int(item['slot'], 16)
        if not SLOTS_LOW <= slot < SLOTS_HIGH:
            raise ValueError('Unexpected callback relocation slot')
        target_slots.add(slot)
    if not target_slots:
        raise ValueError('Source manifest did not record the expected callback relocations')
    records = []
    candidate_addrs = set()
    for slot in sorted(target_slots):
        record = decoded.get(slot)
        if record is None:
            records.append({'slot': f'0x{slot:x}', 'status': 'RELOCATION_NOT_FOUND_IN_ELF_TABLES'})
            continue
        records.append(dict(record, status='RELOCATION_PARSED'))
        if record['candidate_address'] is not None:
            candidate_addrs.add(record['candidate_address'])
    candidates = sorted(candidate_addrs)[:8]
    excerpts = {}
    if candidates:
        objdump = find_objdump()
        for idx, address in enumerate(candidates):
            # A bounded excerpt only, never export a complete proprietary ELF.
            result = subprocess.run([
                objdump, '-d', '--demangle', '--no-show-raw-insn',
                f'--start-address=0x{address:x}', f'--stop-address=0x{address+0x600:x}', str(pvr)
            ], capture_output=True, text=True, timeout=30, check=True)
            if len(result.stdout.splitlines()) < 7:
                raise RuntimeError(f'No disassembly at verified executable VA 0x{address:x}')
            excerpts[f'callback-{idx:02d}-0x{address:x}.txt'] = result.stdout
    status = 'CANDIDATES_CAPTURED_NOT_PROVEN' if candidates else 'NO_EXECUTABLE_CANDIDATE_NOT_PROVEN'
    report = {
        'schema': 'p3a4e.callback_relocations.v1', 'status': status,
        'source_manifest': manifest.name,
        'source_manifest_sha256': owner_hashes[manifest.name],
        'pvr_sha256': PIN_PVR,
        'observe_only': True,
        'exact_time': False,
        'live_lighthouse_correction_allowed': False,
        'mapping_verified': False,
        'pose_verified': False,
        'frame_meta_bridge_verified': False,
        'callback_vtable_identity_verified': False,
        'shared_buffer_identity_verified': False,
        'physical_event_verified': False,
        'relocation_slots_requested': len(target_slots),
        'relocation_slots_parsed': sum(rec['status'] == 'RELOCATION_PARSED' for rec in records),
        'relocation_section_types': sorted({f'0x{typ:x}' for typ, _off, _size, _ent in elf.sections
                                           if typ in (SHT_REL, SHT_RELA, SHT_RELR, SHT_ANDROID_RELR)}),
        'callback_candidate_addresses': [f'0x{a:x}' for a in candidates],
        'records': records,
    }
    run_id = 'p3a4e-reloc-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:8]
    stage = build / (run_id + '-private')
    published = atomic_publish(stage, args.output_root, run_id, report, excerpts)
    print(json.dumps({'status': status, **published,
                      'relocations_parsed': report['relocation_slots_parsed'],
                      'relocations_requested': len(target_slots),
                      'disassembly_candidates': len(candidates)}, separators=(',', ':')))
    return 0


if __name__ == '__main__':
    try:
        sys.exit(run())
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        print(json.dumps({'status': 'ERROR', 'reason': str(exc)}), file=sys.stderr)
        sys.exit(1)
