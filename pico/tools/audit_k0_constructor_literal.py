"""Inspect only SHA-pinned PVR ELF constructor literals and *offset algebra*.

On Pico OS 5.11.2, constructor x20=this, x28=this+0x40,
x23=x28-0x300=this-0x2c0; an i=0..6 loop advances x23 by 0x320.
A/B read in onFrameAvailable are based on x19+cam_idx*0x320,
not necessarily the same pointer as constructor x20. Never unify
without tracing x19 to its source. No headset/ADB/SLAM access.
"""
import argparse
import hashlib
import json
import math
import struct
from pathlib import Path

from pico.tools.audit_k0_listener_table import read_elf_va, SERVICE_HASH

CONSTANTS = {
    "ctor_d8_0x736b0": 0x736B0,
    "ctor_d9_0x73748": 0x73748,
    "ctor_d10_0x73738": 0x73738,
}
STRIDE = 0x320
NUM_SLOTS = 7
OBSERVED_DELTA_NS = 225997


def decode_literal(raw):
    if len(raw) != 8:
        raise ValueError("Expected exact 8 bytes")
    unsigned = int.from_bytes(raw, "little", signed=False)
    signed = int.from_bytes(raw, "little", signed=True)
    as_double = struct.unpack("<d", raw)[0]
    return {
        "hex_le": raw.hex(), "u64_bits": unsigned, "i64_bits": signed,
        "f64_interpretation": str(as_double) if not math.isfinite(as_double)
                                  else repr(as_double),
    }


def offset_layout():
    slots = []
    for i in range(NUM_SLOTS):
        ctor_b = -0x2C0 + STRIDE * i + 0x330
        ctor_a = -0x2C0 + STRIDE * i + 0x338
        reader_b_if_x19_this = 0x330 + STRIDE * i
        reader_a_if_x19_this = 0x338 + STRIDE * i
        slots.append({
            "constructor_iteration": i,
            "ctor_store_x20_this_relative_B": f"0x{ctor_b:x}",
            "ctor_store_x20_this_relative_A": f"0x{ctor_a:x}",
            "reader_x19_relative_B": f"0x{reader_b_if_x19_this:x}",
            "reader_x19_relative_A": f"0x{reader_a_if_x19_this:x}",
            "base_delta_required_for_same_fields": -0x2C0,
        })
    return slots


def inspect(path):
    data = Path(path).read_bytes()
    if hashlib.sha256(data).hexdigest() != SERVICE_HASH:
        raise ValueError("Unexpected firmware hash; unsafe to interpret fixed ELF VAs")
    constants = {
        name: decode_literal(read_elf_va(path, va, 8))
        for name, va in CONSTANTS.items()
    }
    return {
        "status": "PVR_CTOR_LITERALS_AND_BASE_RELATION_STATIC_UNVERIFIED",
        "constants": constants,
        "constructor_x20_this_relative_offset_B_A": offset_layout(),
        "frame_time_formula": "T130 = T122 - 52000 - A - ((B * E) ASR 1)",
        "observed_E": 4,
        "observed_delta_ns": OBSERVED_DELTA_NS,
        "constraint_if_same_frame_fields": (
            "A + 2*B = 173997 ns for 1204 accepted frames; "
            "A/B individually unknown"
        ),
        "warnings": [
            "An ARM64 d-register load/store transfers raw 64-bit bits; "
            "do not assume the literal is floating point.",
            "Constructor uses x20=this and x23=this-0x2c0; "
            "onFrame uses x19+cam_idx*0x320. Need x19 provenance "
            "before equating constructor and reader fields.",
            "No actual physical exposure-event or hardware camera "
            "clock timestamp provenance has been verified.",
        ],
        "gates": {"runtime_A_B_values_verified": False,
                  "sensor_physical_exposure_verified": False,
                  "live_lighthouse_correction_allowed": False},
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--service", type=Path, required=True)
    p.add_argument("--output", type=Path)
    args = p.parse_args()
    result = inspect(args.service)
    if args.output:
        args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(result["status"])
    for name, record in result["constants"].items():
        print(f"{name}: hexLE={record['hex_le']} i64={record['i64_bits']} "
              f"f64_bits={record['f64_interpretation']}")
    print("constructor slots: 7 at stride 0x320; x20-relative B starts +0x70")
    print("reader x19-relative B starts +0x330; bases not assumed equal")
    print("OBSERVE ONLY; individual A/B values and exposure semantics UNVERIFIED")


if __name__ == "__main__":
    main()
