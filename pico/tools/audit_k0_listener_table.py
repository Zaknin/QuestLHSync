"""Offline reader for PVR CameraImageListener compact ARM64 jump table.

The firmware callback at 0xabbfc reads frame_item[0], accepts indices 0..3,
then reads four unsigned 8-bit table entries at 0x73a10. It computes a
branch target as 0xabc24+4*byte. Only addresses actually present in the
verified native disassembly are recognized. Source-level dispatch mapping
does NOT verify physical camera mapping, QTIMER origin, or exposure instant.

STRICTLY offline; file hashed to Pico OS 5.11.2 private firmware snapshot.
"""
import argparse
import hashlib
import json
import struct
from pathlib import Path

SERVICE_HASH = "45194b15539875ea1ce01fb702d34773b708d248a3409d369877ac199849b8de"
TABLE_VA = 0x73A10
TABLE_SIZE = 4
BRANCH_BASE = 0xABC24
TARGETS = {
    0xABC24: {"kind": "fixed_camera_id", "camera_id": 0},
    0xABC30: {"kind": "listener_member_camera_id", "camera_id": None},
    0xABC40: {"kind": "fixed_camera_id", "camera_id": 3},
    0xABC4C: {"kind": "fixed_camera_id", "camera_id": 4},
    0xABC58: {"kind": "fixed_camera_id", "camera_id": 5},
}


def read_elf_va(elf_path, va, length):
    if length < 1 or length > 4096 or va < 0:
        raise ValueError("Invalid bounded PT_LOAD read")
    blob = Path(elf_path).read_bytes()
    if len(blob) < 64 or blob[:4] != b"\x7fELF" or blob[4:6] != b"\x02\x01":
        raise ValueError("Expected little-endian ELF64")
    if struct.unpack_from("<H", blob, 18)[0] != 183:
        raise ValueError("Expected EM_AARCH64")
    phoff = struct.unpack_from("<Q", blob, 32)[0]
    entsize, phcount = struct.unpack_from("<HH", blob, 54)
    if (entsize < 56 or phcount < 1 or phcount > 4096
            or phoff + phcount * entsize > len(blob)):
        raise ValueError("Malformed ELF program headers")
    for i in range(phcount):
        p = phoff + i * entsize
        kind, flags, offset, virt, phys, filesz, memsz, align = struct.unpack_from(
            "<IIQQQQQQ", blob, p
        )
        if kind != 1 or not (virt <= va and va + length <= virt + filesz):
            continue
        pos = offset + va - virt
        if pos + length > len(blob):
            raise ValueError("PT_LOAD file bounds violated")
        return bytes(blob[pos:pos + length])
    raise ValueError(f"Virtual address {hex(va)} not covered by ELF PT_LOAD")


def decode_dispatch(entries):
    if len(entries) != TABLE_SIZE:
        raise ValueError("Expected four table bytes for frame_item[0] 0..3")
    output = []
    for index, delta in enumerate(entries):
        target = BRANCH_BASE + 4 * delta
        match = TARGETS.get(target)
        if match is None:
            raise ValueError(
                f"Unexpected indirect branch at {hex(target)}: no static proof"
            )
        output.append({
            "frame_item_first_byte": index,
            "unsigned_table_offset": delta,
            "target_va": f"0x{target:x}",
            "kind": match["kind"],
            "camera_id": match["camera_id"],
        })
    return output


def analyze(elf_path):
    digest = hashlib.sha256(Path(elf_path).read_bytes()).hexdigest()
    if digest != SERVICE_HASH:
        raise ValueError("Unexpected PVR service SHA256: refusing fixed firmware VAs")
    raw = read_elf_va(elf_path, TABLE_VA, TABLE_SIZE)
    return {
        "status": "PVR_CAMERAINAGELISTENER_DISPATCH_STATIC_ONLY",
        "source": "CameraImageListener::onFrameAvailable 0xabbfc–0xabc64",
        "sha256_verified": True,
        "table_va": f"0x{TABLE_VA:x}",
        "table_bytes_hex": raw.hex(),
        "index_routes": decode_dispatch(raw),
        "note": (
            "Maps callback frame_item[0] values 0..3 to CameraManager "
            "camera IDs *in code*. Does not prove physical K0 cam IDs, "
            "active listener binding, hardware QTIMER event, or exposure."
        ),
        "gates": {
            "active_k0_producer_verified": False,
            "sensor_physical_exposure_verified": False,
            "live_lighthouse_correction_allowed": False,
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--service", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = analyze(args.service)
    if args.output:
        args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"CameraImageListener jump table: {result['table_bytes_hex']}")
    for route in result["index_routes"]:
        print(
            f"source_index={route['frame_item_first_byte']} "
            f"jump={route['target_va']} -> {route['kind']} "
            f"camera_id={route['camera_id']}"
        )
    print("STATIC ONLY; live Lighthouse correction remains BLOCKED.")


if __name__ == "__main__":
    main()
