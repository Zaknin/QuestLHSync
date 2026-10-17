"""P3-B passive Windows QPC/OpenVR pose diagnostic; never a sensor timestamp."""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import math
import os
from pathlib import Path
import statistics
import sys
import time
from datetime import datetime, timezone
from uuid import uuid4

SCHEMA = "p3b.openvr_qpc.v1"
DEFAULT_ROOT = r"\\192.168.23.63\Torrents\Codex\PicoLHSync\P3-B"
SAFETY = {
    "observe_only": True,
    "exact_time": False,
    "live_lighthouse_correction_allowed": False,
    "mapping_verified": False,
    "pose_verified": False,
}
IDENTITY_PROPS = ("Prop_ModelNumber_String", "Prop_ManufacturerName_String",
                  "Prop_TrackingSystemName_String")


class WindowsQPC:
    def __init__(self):
        if sys.platform != "win32":
            raise OSError("Windows QPC requires Windows")
        dll = ctypes.WinDLL("kernel32", use_last_error=True)
        self._counter = dll.QueryPerformanceCounter
        self._frequency = dll.QueryPerformanceFrequency
        for fn in (self._counter, self._frequency):
            fn.argtypes = [ctypes.POINTER(ctypes.c_int64)]
            fn.restype = ctypes.c_int
        frequency = ctypes.c_int64()
        if not self._frequency(ctypes.byref(frequency)) or frequency.value <= 0:
            raise OSError("QueryPerformanceFrequency failed")
        self.frequency = frequency.value

    def ticks(self):
        value = ctypes.c_int64()
        if not self._counter(ctypes.byref(value)):
            raise OSError("QueryPerformanceCounter failed")
        return value.value


def identity_snapshot(vr, api, device_count):
    """No serial number is read or persisted."""
    result = {}
    for i in range(device_count):
        try:
            klass = int(vr.getTrackedDeviceClass(i))
        except Exception:
            klass = -1
        props = {}
        if klass > 0:
            for name in IDENTITY_PROPS:
                prop = getattr(api, name, None)
                if prop is not None:
                    try:
                        val = vr.getStringTrackedDeviceProperty(i, prop)
                        if isinstance(val, bytes):
                            val = val.decode("utf-8", "replace")
                        props[name] = str(val)[:256]
                    except Exception:
                        props[name] = None
        result[str(i)] = {"device_class": klass, "properties": props}
    return result


def vector3(v):
    return [float(v.v[i]) for i in range(3)]


def encode_pose(p, index):
    connected = bool(p.bDeviceIsConnected)
    valid = bool(p.bPoseIsValid)
    item = {
        "device_index": index,
        "connected": connected,
        "pose_valid": valid,
        "tracking_result": int(p.eTrackingResult),
        "matrix_3x4": None,
        "velocity_m_s": None,
        "angular_velocity_rad_s": None,
    }
    # OpenVR documents matrix/velocity as usable only for a valid pose.
    if connected and valid:
        matrix = [[float(p.mDeviceToAbsoluteTracking.m[r][c]) for c in range(4)]
                  for r in range(3)]
        velocity = vector3(p.vVelocity)
        angular = vector3(p.vAngularVelocity)
        vals = [x for row in matrix for x in row] + velocity + angular
        if not all(math.isfinite(x) for x in vals):
            raise ValueError(f"non-finite pose data for device {index}")
        item.update(matrix_3x4=matrix, velocity_m_s=velocity,
                    angular_velocity_rad_s=angular)
    return item


def collect_one(vr, clock, *, origin, count, index):
    before = clock.ticks()
    try:
        poses = vr.getDeviceToAbsoluteTrackingPose(origin, 0.0, count)
        error = None
    except Exception as exc:
        poses = None
        error = f"{type(exc).__name__}: {str(exc)[:300]}"
    after = clock.ticks()
    row = {
        "record_type": "sample", "sample_index": index,
        "qpc_before_tick": before, "qpc_after_tick": after,
        "qpc_duration_ticks": after - before, "qpc_frequency_hz": clock.frequency,
        "prediction_seconds": 0.0, "origin": origin,
        "devices": [], "error": error,
    }
    if after < before:
        row["error"] = "QPC_REVERSED"
    elif poses is not None:
        try:
            if len(poses) != count:
                raise ValueError(f"pose count {len(poses)} != requested {count}")
            row["devices"] = [encode_pose(p, i) for i, p in enumerate(poses)]
        except (ValueError, TypeError, IndexError, AttributeError) as exc:
            row["devices"] = []
            row["error"] = f"INVALID_POSE: {str(exc)[:300]}"
    return row


def latency_stats(rows, frequency):
    durations = sorted(r["qpc_duration_ticks"] for r in rows
                       if r["error"] is None and r["qpc_duration_ticks"] >= 0)
    if not durations:
        return None
    to_us = lambda n: n * 1_000_000 / frequency
    return {"count": len(durations), "min_us": to_us(durations[0]),
            "median_us": to_us(statistics.median(durations)),
            "p95_nearest_rank_us": to_us(durations[math.ceil(.95 * len(durations)) - 1]),
            "max_us": to_us(durations[-1])}


def run_samples(vr, clock, *, origin, count, seconds, hz, sleeper=time.sleep,
                monotonic=time.monotonic, rows=None):
    if rows is None:
        rows = []
    start = monotonic()
    total = math.ceil(seconds * hz)
    last_after = None
    for i in range(total):
        delay = start + i / hz - monotonic()
        if delay > 0:
            sleeper(delay)
        row = collect_one(vr, clock, origin=origin, count=count, index=i)
        if last_after is not None and row["qpc_before_tick"] < last_after:
            row["error"] = "QPC_NONMONOTONIC_ACROSS_SAMPLES"
            row["devices"] = []
        last_after = row["qpc_after_tick"]
        rows.append(row)
    return rows


def finish(rows, frequency):
    success = [r for r in rows if r["error"] is None]
    hmd_valid = any(r["devices"] and r["devices"][0]["connected"]
                    and r["devices"][0]["pose_valid"] for r in success)
    errors = sum(r["error"] is not None for r in rows)
    status = "PASS_HOST_QUERY" if success and hmd_valid and not errors else (
        "PARTIAL" if success and (errors or not hmd_valid) else "BLOCKED")
    return {"record_type": "summary", "status": status,
            "samples_requested_or_attempted": len(rows), "successful_calls": len(success),
            "error_calls": errors, "valid_hmd_pose_seen": hmd_valid,
            "api_call_bracket_latency": latency_stats(rows, frequency),
            "sensor_timestamp_proven": False, "pico_host_clock_mapping_proven": False,
            "note": "QPC bounds API call only; prediction=0 is not physical sensor time."}


def execute(api, clock, *, seconds=10, hz=20, origin_name="standing",
            sleeper=time.sleep, monotonic=time.monotonic):
    """Injected API/clock permit strict mock tests without Windows or SteamVR."""
    origins = {"standing": api.TrackingUniverseStanding,
               "seated": api.TrackingUniverseSeated}
    origin = int(origins[origin_name])
    header = {"record_type": "header", "schema": SCHEMA,
              "utc_started": datetime.now(timezone.utc).isoformat(),
              "host": "Windows", "qpc_frequency_hz": clock.frequency,
              "origin_name": origin_name, "origin": origin,
              "prediction_seconds": 0.0, "safety": SAFETY,
              "timestamp_semantics": "API call QPC bracket only, NOT optical/sensor timestamp"}
    records = [header]
    rows = []
    initialized = False
    try:
        vr = api.init(api.VRApplication_Background)
        initialized = True
        count = int(api.k_unMaxTrackedDeviceCount)
        if not 1 <= count <= 256:
            raise ValueError("invalid max tracked device count")
        records.append({"record_type": "device_identity_snapshot",
                        "identities": identity_snapshot(vr, api, count),
                        "serial_number_collected": False})
        rows = run_samples(vr, clock, origin=origin, count=count, seconds=seconds,
                           hz=hz, sleeper=sleeper, monotonic=monotonic, rows=rows)
    except (Exception, KeyboardInterrupt) as exc:
        records.append({"record_type": "diagnostic_error",
                        "error_type": type(exc).__name__, "detail": str(exc)[:300]})
    finally:
        if initialized:
            try:
                api.shutdown()
            except Exception as exc:
                records.append({"record_type": "diagnostic_error", "error_type": "shutdown",
                                "detail": str(exc)[:300]})
    records.extend(rows)
    summary = finish(rows, clock.frequency)
    if any(r["record_type"] == "diagnostic_error" for r in records):
        summary["status"] = "PARTIAL" if rows else "BLOCKED"
    records.append(summary)
    return records


def publish(records, root=DEFAULT_ROOT, *, readback=None):
    """SMB .part -> independent SHA-256 readback -> rename -> manifest -> .sha256 last."""
    base = Path(root)
    base.mkdir(parents=True, exist_ok=True)
    name = f"p3b-openvr-qpc-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{uuid4().hex[:8]}"
    blob = ("\n".join(json.dumps(r, ensure_ascii=False, allow_nan=False,
                                   separators=(",", ":")) for r in records) + "\n").encode("utf-8")
    data = base / (name + ".jsonl")
    part = base / (name + ".jsonl.part")
    digest = hashlib.sha256(blob).hexdigest()
    part.write_bytes(blob)
    get_bytes = readback or (lambda path: path.read_bytes())
    if hashlib.sha256(get_bytes(part)).hexdigest() != digest:
        raise IOError("SMB .part independent SHA-256 readback mismatch; NOT COMMITTED")
    os.replace(part, data)
    if hashlib.sha256(get_bytes(data)).hexdigest() != digest:
        raise IOError("SMB committed file readback mismatch; no .sha256 sidecar")
    manifest = base / (name + ".manifest.json")
    summary = records[-1]
    metadata = {"schema": SCHEMA, "status": summary["status"], "evidence": data.name,
                "evidence_sha256": digest, "safety": SAFETY,
                "sensor_timestamp_proven": False, "hardware_validation": False}
    manifest_blob = (json.dumps(metadata, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    manifest_part = base / (name + ".manifest.json.part")
    manifest_part.write_bytes(manifest_blob)
    manifest_hash = hashlib.sha256(manifest_blob).hexdigest()
    if hashlib.sha256(get_bytes(manifest_part)).hexdigest() != manifest_hash:
        raise IOError("SMB manifest readback mismatch; no .sha256 sidecar")
    os.replace(manifest_part, manifest)
    if hashlib.sha256(get_bytes(manifest)).hexdigest() != manifest_hash:
        raise IOError("SMB committed manifest readback mismatch; no .sha256 sidecar")
    sidecar = base / (name + ".sha256")
    sidecar_part = base / (name + ".sha256.part")
    sidecar_part.write_text(f"{digest}  {data.name}\n{manifest_hash}  {manifest.name}\n", encoding="ascii")
    sidecar_hash = hashlib.sha256(sidecar_part.read_bytes()).hexdigest()
    if hashlib.sha256(get_bytes(sidecar_part)).hexdigest() != sidecar_hash:
        raise IOError("SMB sidecar readback mismatch; NOT COMMITTED")
    os.replace(sidecar_part, sidecar)  # commit indicator: published LAST
    if hashlib.sha256(get_bytes(sidecar)).hexdigest() != sidecar_hash:
        raise IOError("SMB sidecar readback mismatch after rename")
    return {"evidence": str(data), "manifest": str(manifest), "sha256": str(sidecar),
            "digest": digest, "status": summary["status"]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=float, default=10)
    parser.add_argument("--hz", type=int, default=20)
    parser.add_argument("--origin", choices=("standing", "seated"), default="standing")
    parser.add_argument("--output-root", default=DEFAULT_ROOT,
                        help="Canonical SMB by default; custom root requires explicit override")
    args = parser.parse_args(argv)
    if not math.isfinite(args.seconds) or not 1 <= args.seconds <= 60 or not 1 <= args.hz <= 60:
        parser.error("seconds must be 1..60 and hz 1..60")
    try:
        clock = WindowsQPC()
    except Exception as exc:
        print(f"QPC unavailable: {exc}", file=sys.stderr)
        return 2
    try:
        import openvr
    except ImportError:
        print("Missing Python OpenVR binding: python -m pip install openvr", file=sys.stderr)
        return 2
    records = execute(openvr, clock, seconds=args.seconds, hz=args.hz,
                      origin_name=args.origin)
    try:
        result = publish(records, args.output_root)
    except Exception as exc:
        print(f"CANONICAL SMB PUBLICATION FAILED (no fallback): {exc}", file=sys.stderr)
        return 3
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] == "PASS_HOST_QUERY" else 1


if __name__ == "__main__":
    sys.exit(main())
