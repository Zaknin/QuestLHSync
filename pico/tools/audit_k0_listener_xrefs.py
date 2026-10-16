"""Offline AArch64 PVR reverse xrefs for QuickCamera->CameraManager K0 producer.

This does NOT infer exposure time from slot130, alter any data, or
communicate with the device. It searches only two SHA-pinned vendor
ELF files already stored by the Pico owner.
"""
import argparse
import hashlib
import re
import subprocess
from pathlib import Path

SHA_CAMERA = "cf9e507f412ec33d62c2f720669fcdd093f1822c9cbf3adefd0a26a6b4d072ee"
SHA_SERVICE = "45194b15539875ea1ce01fb702d34773b708d248a3409d369877ac199849b8de"

FUNC = re.compile(r"^\s*([0-9a-f]{4,16}) <(.+)>:\s*$")
INSN = re.compile(r"^\s*([0-9a-f]{4,16}):\s+([a-z.0-9]+)\s*(.*)$")
CALL = re.compile(r"\b(?:bl|blr)\s+")
CONFIG_STORE = re.compile(
    r"^\s*[0-9a-f]+:\s+(?:str|stur|stp)\b.*\[[xw]\d+,\s*#0x(?:330|338)\]",
    re.I,
)
CONFIG_REF = re.compile(r"\[[xw]\d+,\s*#0x(?:330|338)\]", re.I)


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def run(argv):
    result = subprocess.run(argv, capture_output=True, text=True, errors="replace", check=False)
    if result.returncode:
        raise RuntimeError(f"offline tool {argv[0]} failed (exit {result.returncode}): {result.stderr[:800]}")
    return result.stdout


def parse_functions(disassembly):
    lines = disassembly.splitlines()
    owner = "(no symbol)"
    mapping = []
    for line in lines:
        match = FUNC.match(line)
        if match:
            owner = match.group(2)
        mapping.append(owner)
    return lines, mapping


def find_matches(lines, owners, predicate, max_matches=60, before=5, after=4):
    hits = []
    for i, line in enumerate(lines):
        if predicate(line, owners[i]):
            context = []
            for j in range(max(0, i - before), min(len(lines), i + after + 1)):
                if INSN.match(lines[j]) or FUNC.match(lines[j]):
                    context.append((">> " if i == j else "   ") + lines[j].strip()[:230])
            hits.append({
                "owner": owners[i],
                "at": INSN.match(line).group(1) if INSN.match(line) else "?",
                "text": line.strip()[:230],
                "context": context,
            })
            if len(hits) >= max_matches:
                break
    return hits


def extract_range(lines, start, end):
    selected = []
    for line in lines:
        inst = INSN.match(line)
        if inst and start <= int(inst.group(1), 16) < end:
            selected.append(line.strip()[:240])
    return selected


def vtable_target(relocation_text):
    """Return exact relocation target of service vtable slot +0x10."""
    for line in relocation_text.splitlines():
        cols = line.split()
        if len(cols) < 5:
            continue
        if (cols[0].lower().lstrip("0") == "15e6b0"
                and cols[2] == "R_AARCH64_ABS64"
                and cols[3].lower().lstrip("0") == "abbfc"
                and "CameraImageListener" in line
                and "onFrameAvailable" in line):
            return True
    return False


def format_hits(label, hits):
    output = [f"[{label}] count_shown={len(hits)}"]
    if not hits:
        output.append("No exact matching source instructions found; this is NOT proof of absence.")
    for hit in hits:
        output.append(f"Function: {hit['owner']}  @0x{hit['at']}")
        output.extend(hit["context"])
    return "\n".join(output)


def analyze(camera, service, objdump, readelf):
    expected = ((camera, SHA_CAMERA), (service, SHA_SERVICE))
    for path, wanted in expected:
        actual = sha256(path)
        if actual != wanted:
            raise ValueError(f"ELF SHA256 mismatch: {Path(path).name}, expected {wanted}, got {actual}")
    cam_asm = run([str(objdump), "-d", "--demangle", "--no-show-raw-insn", str(camera)])
    svc_asm = run([str(objdump), "-d", "--demangle", "--no-show-raw-insn", str(service)])
    relocs = run([str(readelf), "--relocations", "--wide", str(service)])
    if not vtable_target(relocs):
        raise ValueError("CameraImageListener vtable+0x10 relocation not confirmed; refusing to assume callback target")

    cam, cam_owners = parse_functions(cam_asm)
    svc, svc_owners = parse_functions(svc_asm)
    output = [
        "PICO_P2_OFFLINE_LISTENER_XREF_V1",
        "sha256=camera/service: MATCH pinned 2026-10-13 firmware",
        "service_vtable_slot_0x15e6b0=CameraImageListener::onFrameAvailable: RELOCATION_VERIFIED",
        "Important: virtual interface compatibility does NOT prove actual runtime listener registration.",
        "",
        "[CameraImageListener::onFrameAvailable exact body, service]",
        *extract_range(svc, 0xabbfc, 0xabc64),
        "",
        "[QuickCamera virtual call construction, camera]",
        *extract_range(cam, 0x666c4, 0x666f4),
        "",
    ]
    for label, lines, owners in (
        ("SERVICE", svc, svc_owners),
        ("CAMERA", cam, cam_owners),
    ):
        registration = find_matches(
            lines, owners,
            lambda s, fn: bool(INSN.match(s) and CALL.search(s)
                               and "setPvrImageListener" in s),
            max_matches=24, before=12, after=7,
        )
        output.append(format_hits(label + " direct setPvrImageListener calls", registration))
        output.append("")
        extra_calls = find_matches(
            lines, owners,
            lambda s, fn: bool(
                INSN.match(s) and CALL.search(s) and (
                    "CameraImageListener::onFrameAvailable" in s
                    or "CameraManager::onFrameAvailable" in s
                    or "PvrCameraDevice::setPvrImageListener" in s
                    or "CameraManager::CameraImageListener::" in s
                )
            ),
            max_matches=24, before=8, after=5,
        )
        output.append(format_hits(label + " listener/manager direct call edges", extra_calls))
        output.append("")
        writes = find_matches(
            lines, owners,
            lambda s, fn: bool(CONFIG_STORE.match(s)),
            max_matches=30, before=12, after=5,
        )
        output.append(format_hits(label + " STR/STUR/STP to per-camera +0x330/+0x338", writes))
        output.append("")
        config_refs = find_matches(
            lines, owners,
            lambda s, fn: bool(INSN.match(s) and CONFIG_REF.search(s)),
            max_matches=30, before=7, after=3,
        )
        output.append(format_hits(label + " ALL +0x330/+0x338 accesses", config_refs))
        output.append("")
    output.extend([
        "NEXT_GATES:",
        "runtime_listener_wiring=UNVERIFIED",
        "raw_offset_330_338_matches_are_NOT_proven_to_be_camera_config=TRUE",
        "QuickCamera_FrameMetaDate_clock_origin=UNVERIFIED",
        "CameraManager_A_B_E_physical_meaning=UNVERIFIED",
        "slot130_physical_exposure_instant=UNVERIFIED",
        "live_lighthouse_correction_allowed=false",
        "OBSERVE_ONLY=true",
    ])
    return "\n".join(output) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--camera", type=Path, required=True)
    parser.add_argument("--service", type=Path, required=True)
    parser.add_argument("--objdump", type=Path, required=True)
    parser.add_argument("--readelf", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args()
    result = analyze(args.camera, args.service, args.objdump, args.readelf)
    args.output.write_text(result, encoding="utf-8")
    if args.summary:
        print("PICO_P2_OFFLINE_LISTENER_XREF_V1")
        lines = result.splitlines()
        for line in lines:
            if (line.startswith("[") or line.startswith("Function:")
                    or line.startswith("service_vtable")
                    or line.startswith("runtime_listener_")
                    or line.startswith("QuickCamera_FrameMetaDate_")
                    or line.startswith("CameraManager_A_B_E_")
                    or line.startswith("slot130_physical_")
                    or line.startswith("live_lighthouse_")
                    or line.startswith("OBSERVE_ONLY")):
                print(line[:260])
        print(f"Complete private report: {args.output}")
        print("No active K0 producer verified solely by a matching vtable ABI.")
    else:
        print(result)


if __name__ == "__main__":
    main()
