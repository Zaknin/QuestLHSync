"""Pure offline check: look for another compiled A/B constant pair.

The source-constructor pair from VA 0x73170 predicts 223621 ns, while
the existing 1204 frames show 225997 ns. Searches only file-backed,
readable, non-writable, non-executable ELF64 load segments for aligned
(B:int64, A:int64) literal pairs predicting the observed correction.
Matches are *candidates*, never evidence of runtime use.
"""
import argparse
import hashlib
import json
import struct
from pathlib import Path

from pico.tools.audit_k0_listener_table import SERVICE_HASH
from pico.tools.audit_k0_q1_coefficients import correction_ns

EXPECTED_CORRECTION = 225997


def readonly_segments(blob):
    if len(blob) < 64 or blob[:4] != bytes.fromhex("7f454c46") or blob[4:6] != bytes([2, 1]):
        raise ValueError("Not a supported ELF64 LE")
    if struct.unpack_from("<H", blob, 18)[0] != 183:
        raise ValueError("Not AArch64")
    off = struct.unpack_from("<Q", blob, 32)[0]
    size, count = struct.unpack_from("<HH", blob, 54)
    if size < 56 or not 1 <= count <= 4096 or off + size * count > len(blob):
        raise ValueError("Malformed program headers")
    out = []
    for n in range(count):
        p = off + n * size
        kind, flags, fileoff, va, _, filesz, memsz, _ = struct.unpack_from("<IIQQQQQQ", blob, p)
        if kind != 1 or flags & 7 != 4:
            continue
        if fileoff + filesz > len(blob) or filesz > memsz:
            raise ValueError("Malformed PT_LOAD")
        out.append((va, memoryview(blob)[fileoff:fileoff + filesz]))
    return out


def find_pairs(va, segment, target=EXPECTED_CORRECTION):
    pairs = []
    start = (-va) % 8
    for pos in range(start, len(segment) - 15, 8):
        b, a = struct.unpack_from("<qq", segment, pos)
        if 0 <= b <= 10_000_000 and -10_000_000 <= a <= 10_000_000:
            if correction_ns(a, b, 4) == target:
                pairs.append({"va": hex(va + pos), "B": b, "A": a})
    return pairs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--service", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    blob = args.service.read_bytes()
    if hashlib.sha256(blob).hexdigest() != SERVICE_HASH:
        raise ValueError("Wrong pinned firmware hash")
    segments = readonly_segments(blob)
    anchor_va = 0x73170
    if not any(va <= anchor_va and anchor_va + 16 <= va + len(data) for va, data in segments):
        raise ValueError("Known constructor q1 literal not in a RO-only PT_LOAD segment; scan cannot establish absence")
    matches = [pair for va, data in segments for pair in find_pairs(va, data)]
    result = {
        "status": "ALTERNATE_STATIC_LITERALS_ONLY_UNVERIFIED",
        "ro_segments": len(segments), "target_ns": EXPECTED_CORRECTION,
        "candidate_count": len(matches), "candidates": matches[:100],
        "effective_runtime_A_B_verified": False,
        "live_lighthouse_correction_allowed": False,
    }
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"read_only_segments={len(segments)} candidate_count={len(matches)}")
    for pair in matches[:15]:
        print(f"candidate {pair['va']} B={pair['B']} A={pair['A']}")
    print("Static candidates only, no producer or runtime provenance verified.")
    print(f"Private report: {args.output}")


if __name__ == "__main__":
    main()
