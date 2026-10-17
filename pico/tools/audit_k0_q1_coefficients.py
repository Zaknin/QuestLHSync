"""Source-backed, offline audit of CameraManager's K0 timing constants.

Native code loads 16 bytes (q1) from ELF VA 0x73170, saves q1 on
the stack, and writes it to the same seven 0x320-stride camera blocks
that onFrameAvailable uses for the +130 correction. This program
compares their *initializer* values to the owner's saved-frame delta.

Only reads the exact SHA-pinned private libpvrtrackingservice.so.
No runtime access, no device, no camera, no SteamVR modifications.
"""
import argparse
import json
import struct
from pathlib import Path

from pico.tools.audit_k0_listener_table import (
    SERVICE_HASH, read_elf_va,
)
import hashlib

Q1_VA = 0x73170
CAMERA_COUNT = 7
CAMERA_STRIDE = 0x320
OBSERVED_CORRECTION_NS = 225_997
FIXED_SUBTRACTION_NS = 52_000
E_FRAME_CODE = 4
I64_MASK = (1 << 64) - 1


def signed_64(n):
    """ARM64 64-bit arithmetic wraps modulo 2^64."""
    raw = n & I64_MASK
    return raw - (1 << 64) if raw & (1 << 63) else raw


def decode_q1(raw):
    if len(raw) != 16:
        raise ValueError("Expected exact 128-bit q1 initializer")
    b, a = struct.unpack("<qq", raw)
    return {"B_int64": b, "A_int64": a, "raw16_hex_le": raw.hex()}


def correction_ns(a, b, exposure_code=E_FRAME_CODE):
    """Emulates native MUL x10,x10,x8; ASR #1; sub in signed 64-bit."""
    if not (-(1 << 31) <= exposure_code < (1 << 31)):
        raise ValueError("Exposure code must fit signed int32")
    product = signed_64(b * exposure_code)
    half = product >> 1
    return signed_64(FIXED_SUBTRACTION_NS + a + half)


def field_offsets(index):
    if not 0 <= index < CAMERA_COUNT:
        raise ValueError("Invalid native camera block index")
    ctor_base = -0x2C0 + index * CAMERA_STRIDE
    return {
        "index": index,
        "ctor_q1_write_B_this_relative": ctor_base + 0x5F0,
        "ctor_q1_write_A_this_relative": ctor_base + 0x5F8,
        "callback_B_this_relative": index * CAMERA_STRIDE + 0x330,
        "callback_A_this_relative": index * CAMERA_STRIDE + 0x338,
    }


def inspect(path, observed_ns=OBSERVED_CORRECTION_NS):
    actual_sha = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    if actual_sha != SERVICE_HASH:
        raise ValueError("PVR service ELF SHA-256 mismatch: reject known address/ABI")
    literal = decode_q1(read_elf_va(path, Q1_VA, 16))
    b, a = literal["B_int64"], literal["A_int64"]
    predicted_ns = correction_ns(a, b)
    exact = predicted_ns == observed_ns
    layouts = [field_offsets(i) for i in range(CAMERA_COUNT)]
    for row in layouts:
        if (row["ctor_q1_write_B_this_relative"] != row["callback_B_this_relative"]
                or row["ctor_q1_write_A_this_relative"] != row["callback_A_this_relative"]):
            raise AssertionError("CameraManager constructor/callback offset mismatch")
    return {
        "status": ("INITIALIZER_MATCHES_RECORDED_K0_DELTA"
                   if exact else "INITIALIZER_DIFFERS_FROM_RECORDED_K0_DELTA"),
        "source_file_verified_sha256": actual_sha,
        "q1_literal_elf_va": hex(Q1_VA),
        "initializer": literal,
        "camera_block_count": CAMERA_COUNT,
        "camera_block_stride_bytes": CAMERA_STRIDE,
        "constructor_q1_destination_equals_callback_A_B_for_all_slots": True,
        "frame_exposure_code_observed": E_FRAME_CODE,
        "fixed_subtraction_ns": FIXED_SUBTRACTION_NS,
        "predicted_raw_minus_slot130_ns_from_INITIALIZERS": predicted_ns,
        "recorded_raw_minus_slot130_ns_1204_frames": observed_ns,
        "initializer_matches_recorded_sample": exact,
        "caveats": [
            "Initial q1 literal and field destinations are source-verified, "
            "but configuration could be mutated after CameraManager construction.",
            "Matching the recorded adjustment does not independently prove "
            "the original QTIMER event or physical exposure timing.",
            "The sampling reader accepted only E=4 frames; other exposure "
            "codes or firmware may produce a different correction.",
        ],
        "gates": {
            "runtime_coefficients_immutable_verified": False,
            "k0_sensor_exposure_timestamp_verified": False,
            "live_lighthouse_correction_allowed": False,
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--service", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--observed-ns", type=int, default=OBSERVED_CORRECTION_NS)
    args = parser.parse_args()
    result = inspect(args.service, args.observed_ns)
    if args.output:
        args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    a = result["initializer"]["A_int64"]
    b = result["initializer"]["B_int64"]
    print(f"status={result['status']}")
    print(f"ELF[0x73170..0x7317F] = {result['initializer']['raw16_hex_le']}")
    print(f"B={b} A={a} E=4, fixed=52000 ns")
    print("prediction = 52000 + A + ((B*4) arithmetic_shift_right 1)")
    print(f"predicted={result['predicted_raw_minus_slot130_ns_from_INITIALIZERS']} ns "
          f"observed={result['recorded_raw_minus_slot130_ns_1204_frames']} ns")
    print("Source field offsets: constructor == callback for 7 blocks.")
    print("OBSERVE ONLY: physical exposure, runtime immutability, and live corrections UNVERIFIED")


if __name__ == "__main__":
    main()
