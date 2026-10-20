import json
import math
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
REPLAY = Path(os.environ.get("QLHS_REPLAY_EXE", ROOT / "out" / "qlhs_replay.exe"))


def pico_calibration(mapping=((0, 0), (3, 1), (4, 2), (5, 3))):
    cameras = []
    offsets = {0: (-0.05, 0.0, 0.0), 3: (0.05, 0.0, 0.0),
               4: (0.0, 0.05, 0.0), 5: (0.0, -0.05, 0.0)}
    for camera_id, factory_id in mapping:
        x, y, z = offsets[camera_id]
        cameras.append({
            "id": camera_id,
            "factory_camera": factory_id,
            "size": [640, 480],
            "T_BS": [1, 0, 0, x, 0, 1, 0, y, 0, 0, 1, z, 0, 0, 0, 1],
            "intrinsics": [0, 200, 200, 320, 240],
            "distortion": [0, 0, 0, 0],
        })
    return {"kind": "pico", "device": "synthetic", "mapping_verified": False,
            "pose_verified": False, "HeadFromBody": None, "cameras": cameras}


def non_pico_calibration():
    return {"CameraCalibration": [{
        "Id": "0", "ImageSize": [640, 480],
        "DeviceFromCamera": [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1],
        "Projection": {"Coefficients": [200, 320, 240]},
        "Distortion": {"Coefficients": [0, 0, 0, 0, 0, 0, 0, 0]},
    }]}


def p_record(pc_ns, x, y, z, yaw=0.0):
    c, s = math.cos(yaw), math.sin(yaw)
    return (f"{pc_ns} P 0 {c:.9f} 0 {s:.9f} {x:.9f} "
            f"0 1 0 {y:.9f} {-s:.9f} 0 {c:.9f} {z:.9f}\n")


def station_record(pc_ns, serial, x, y, z, channel):
    return pico_recorded_station(pc_ns, serial, channel, x, y, z, qz=0.0)


def pico_recorded_station(pc_ns, serial, channel, x, y, z, qw=1.0, qx=0.0, qy=0.0, qz=0.25):
    """Pico recording writer contract: channel precedes position and quaternion."""
    return (f"{pc_ns} S {serial} {channel} {x:.6f} {y:.6f} {z:.6f} "
            f"{qw:.6f} {qx:.6f} {qy:.6f} {qz:.6f}\n")


def legacy_station_record(pc_ns, serial, x, y, z, channel):
    return f"{pc_ns} S {serial} {x:.6f} {y:.6f} {z:.6f} 1 0 0 0 {channel}\n"


def q_record(pc_ns, hs_seconds):
    pc = pc_ns / 1e9
    return f"{pc_ns} Q {pc - 0.002:.9f} {pc + 0.002:.9f} {hs_seconds:.9f}\n"


def make_parser_fixture(path):
    base_ns = 10_000_000_000_000
    lines = [f"{base_ns} I pico-replay-test\n"]
    for cam, seq in ((0, 17), (3, 23), (4, 29), (5, 31)):
        pc_ns = base_ns + (seq * 1_000_000)
        # Keep every field distinct so the audit catches field loss or reordering.
        fline = f"F {cam} {seq} {1_000_000 + seq} 77 1 {1234 + seq} {2345 + seq} 3 {250 + seq}"
        lines.append(f"{pc_ns} U {fline}\n")
    path.write_text("".join(lines), encoding="ascii", newline="")
    return lines


def write_json(path, value):
    path.write_text(json.dumps(value, separators=(",", ":")), encoding="ascii")


def make_synthetic_scene(path, duration=14.0):
    """Generate known station rays, moving HMD poses and QPC/monotonic pairs."""
    base_ns = 10_000_000_000_000
    clock_offset = 900.0
    stations = [(-1.8, 1.5, 3.2), (0.0, 1.5, 2.8), (1.8, 1.5, 3.2)]
    cam_offsets = {0: (-0.05, 0.0, 0.0), 3: (0.05, 0.0, 0.0),
                   4: (0.0, 0.05, 0.0), 5: (0.0, -0.05, 0.0)}
    records = []
    for second in range(int(duration) + 1):
        t = float(second)
        pc_ns = base_ns + round(t * 1e9)
        records.append(q_record(pc_ns, clock_offset + t))
        for i, (sx, sy, sz) in enumerate(stations):
            records.append(station_record(pc_ns, f"SYNTH-{i}", sx, sy, sz, (1, 7, 10)[i]))
    # SteamVR pose samples at 100 Hz.
    for i in range(int(duration * 100) + 2):
        t = i / 100.0
        pc_ns = base_ns + round(t * 1e9)
        x = 0.18 * math.sin(0.8 * t)
        y = 1.5 + 0.02 * math.sin(0.7 * t)
        z = 0.10 * math.sin(0.6 * t)
        yaw = 0.12 * math.sin(0.65 * t)
        records.append(p_record(pc_ns, x, y, z, yaw))
    # Each camera runs at 25 Hz. Spot coordinates are the projection of the known station centers.
    for frame in range(int(duration * 25)):
        t = frame / 25.0
        xh = 0.18 * math.sin(0.8 * t)
        yh = 1.5 + 0.02 * math.sin(0.7 * t)
        zh = 0.10 * math.sin(0.6 * t)
        yaw = 0.12 * math.sin(0.65 * t)
        c, s = math.cos(yaw), math.sin(yaw)
        hs = clock_offset + t
        for cam, (cx, cy, cz) in cam_offsets.items():
            # HMD pose rotation is yaw about +Y; camera orientations are identity in this fixture.
            ox, oy, oz = xh + c * cx + s * cz, yh + cy, zh - s * cx + c * cz
            spots = []
            for sx, sy, sz in stations:
                dx, dy, dz = sx - ox, sy - oy, sz - oz
                lx, lz = c * dx - s * dz, s * dx + c * dz
                if lz <= 0.25:
                    continue
                px, py = 200.0 * lx / lz + 320.0, 200.0 * dy / lz + 240.0
                if 2 <= px < 638 and 2 <= py < 478:
                    spots.extend((round((px + 0.5) * 10), round((py + 0.5) * 10), 1, 255))
            pc_ns = base_ns + round((t + 0.001 * cam) * 1e9)
            fline = f"F {cam} {frame} {round(hs * 1e6)} 100 {len(spots) // 4}"
            if spots:
                fline += " " + " ".join(str(v) for v in spots)
            records.append(f"{pc_ns} U {fline}\n")
    records.sort(key=lambda s: int(s.split(" ", 1)[0]))
    path.write_text("".join(records), encoding="ascii", newline="")


class PicoNativeReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not REPLAY.is_file():
            raise RuntimeError(f"build replay first: {REPLAY}")

    def run_replay(self, log_path, calib_path, state_dir, *args):
        return subprocess.run(
            [str(REPLAY), str(log_path), "--calib", str(calib_path), "--dir", str(state_dir), *args],
            text=True, capture_output=True, check=False,
        )

    def test_pico_record_audit_preserves_qpc_and_all_f_fields(self):
        with tempfile.TemporaryDirectory(prefix="p3c-parser-") as td:
            root = Path(td)
            log_path, calib_path, audit_path = root / "input.txt", root / "calib.json", root / "audit.txt"
            source = make_parser_fixture(log_path)
            write_json(calib_path, pico_calibration())
            source_calibration = calib_path.read_bytes()
            result = self.run_replay(log_path, calib_path, root / "state", "--pico-offline",
                                     "--pico-identity-control", "--pico-cameras", "all",
                                     "--pico-audit", audit_path)
            self.assertEqual(result.returncode, 0, result.stderr)
            expected = []
            for line in source:
                q = line.split()
                if len(q) > 3 and q[1:3] == ["U", "F"]:
                    expected.append(q[0] + "\t" + " ".join(q[2:]) + "\n")
            self.assertEqual(audit_path.read_text(encoding="ascii"), "".join(expected))
            self.assertIn("first_pc_qpc_ns=10000017000000", result.stdout)
            self.assertIn("frames_submitted=4", result.stdout)
            self.assertEqual(calib_path.read_bytes(), source_calibration)

    def test_pico_upper_mode_excludes_lower_cameras_without_rewriting_frames(self):
        with tempfile.TemporaryDirectory(prefix="p3c-upper-") as td:
            root = Path(td)
            log_path, calib_path, audit_path = root / "input.txt", root / "calib.json", root / "audit.txt"
            make_parser_fixture(log_path)
            write_json(calib_path, pico_calibration())
            result = self.run_replay(log_path, calib_path, root / "state", "--pico-offline",
                                     "--pico-identity-control", "--pico-cameras", "upper",
                                     "--pico-audit", audit_path)
            self.assertEqual(result.returncode, 0, result.stderr)
            audit = audit_path.read_text(encoding="ascii")
            self.assertEqual(len(audit.splitlines()), 2)
            self.assertIn("\tF 0 17 ", audit)
            self.assertIn("\tF 3 23 ", audit)
            self.assertNotIn("F 4 ", audit)
            self.assertNotIn("F 5 ", audit)

    def test_malformed_pico_record_fails_without_echoing_raw_fields(self):
        with tempfile.TemporaryDirectory(prefix="p3c-malformed-") as td:
            root = Path(td)
            log_path, calib_path = root / "input.txt", root / "calib.json"
            log_path.write_text("10000000000 U F 0 1 2 3 1 SECRET_RAW_VALUE\n", encoding="ascii")
            write_json(calib_path, pico_calibration())
            result = self.run_replay(log_path, calib_path, root / "state", "--pico-offline",
                                     "--pico-identity-control")
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn("SECRET_RAW_VALUE", result.stdout + result.stderr)
            self.assertIn("MALFORMED_PICO_FRAME", result.stderr)

    def test_pico_lab_mode_requires_explicit_transform_or_identity_control(self):
        with tempfile.TemporaryDirectory(prefix="p3c-gate-") as td:
            root = Path(td)
            log_path, calib_path = root / "input.txt", root / "calib.json"
            log_path.write_text("10000000000 I test\n", encoding="ascii")
            write_json(calib_path, pico_calibration())
            result = self.run_replay(log_path, calib_path, root / "state", "--pico-offline")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("explicit", result.stderr.lower())

    def test_production_pico_calibration_still_rejects_false_flags(self):
        with tempfile.TemporaryDirectory(prefix="p3c-prod-gate-") as td:
            root = Path(td)
            log_path, calib_path = root / "input.txt", root / "calib.json"
            log_path.write_text("10000000000 I test\n", encoding="ascii")
            write_json(calib_path, pico_calibration())
            result = self.run_replay(log_path, calib_path, root / "state")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("not been validated", result.stderr)

    def test_non_rigid_head_from_body_hypothesis_is_rejected(self):
        with tempfile.TemporaryDirectory(prefix="p3c-bad-transform-") as td:
            root = Path(td)
            log_path, calib_path, transform_path = root / "input.txt", root / "calib.json", root / "transform.json"
            log_path.write_text("10000000000 I test\n", encoding="ascii")
            write_json(calib_path, pico_calibration())
            write_json(transform_path, [2, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1])
            result = self.run_replay(log_path, calib_path, root / "state", "--pico-offline",
                                     "--pico-head-from-body", transform_path)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("PICO_TRANSFORM_REJECTED", result.stderr)

    def test_alternate_camera_mapping_requires_explicit_offline_selection(self):
        with tempfile.TemporaryDirectory(prefix="p3c-map-hypothesis-") as td:
            root = Path(td)
            log_path, calib_path = root / "input.txt", root / "calib.json"
            log_path.write_text("10000000000 I test\n", encoding="ascii")
            write_json(calib_path, pico_calibration(((0, 0), (3, 1), (4, 3), (5, 2))))
            rejected = self.run_replay(log_path, calib_path, root / "state-rejected", "--pico-offline",
                                       "--pico-identity-control")
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn("mapping hypothesis", rejected.stderr.lower())
            accepted = self.run_replay(log_path, calib_path, root / "state-placement", "--pico-offline",
                                       "--pico-identity-control", "--pico-camera-mapping", "placement-guess")
            self.assertEqual(accepted.returncode, 0, accepted.stderr)
            self.assertIn("camera_mapping=placement-guess", accepted.stdout)
            self.assertEqual(json.loads(calib_path.read_text(encoding="ascii"))["mapping_verified"], False)

    def test_non_integer_camera_mapping_fields_fail_closed(self):
        with tempfile.TemporaryDirectory(prefix="p3c-map-malformed-") as td:
            root = Path(td)
            log_path, calib_path = root / "input.txt", root / "calib.json"
            log_path.write_text("10000000000 I test\n", encoding="ascii")
            calibration = pico_calibration()
            calibration["cameras"][0]["id"] = 0.25
            write_json(calib_path, calibration)
            result = self.run_replay(log_path, calib_path, root / "state", "--pico-offline",
                                     "--pico-identity-control")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("integer camera", result.stderr.lower())

    def test_non_pico_mode_ignores_pico_u_records_and_keeps_normal_calibration(self):
        with tempfile.TemporaryDirectory(prefix="p3c-compat-") as td:
            root = Path(td)
            log_path, calib_path = root / "input.txt", root / "calib.json"
            records = make_parser_fixture(log_path)
            base_ns = 10_000_000_000_000
            records.extend([
                p_record(base_ns + 2_000_000, 0.1, 1.5, 0.2),
                legacy_station_record(base_ns + 3_000_000, "LEGACY-STATION", 0.0, 1.5, 2.0, 7),
                q_record(base_ns + 4_000_000, base_ns / 1e9 + 0.004),
                f"{base_ns + 5_000_000} B 0 0.1 0.2 0.3\n",
            ])
            records.sort(key=lambda line: int(line.split(" ", 1)[0]))
            log_path.write_text("".join(records), encoding="ascii", newline="")
            write_json(calib_path, non_pico_calibration())
            result = self.run_replay(log_path, calib_path, root / "state")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn("PICO_OFFLINE", result.stdout)

    def test_pico_station_records_use_channel_first_contract_and_stable_private_aliases(self):
        with tempfile.TemporaryDirectory(prefix="p3c-stations-") as td:
            root = Path(td)
            log_path, calib_path = root / "input.txt", root / "calib.json"
            lines = [
                pico_recorded_station(10_000_000_000, "PRIVATE-STATION-A", 7, -1.25, 1.5, 2.75),
                pico_recorded_station(11_000_000_000, "PRIVATE-STATION-A", 7, -1.20, 1.5, 2.70),
                pico_recorded_station(12_000_000_000, "PRIVATE-STATION-B", 1, 1.25, 1.5, 2.75),
                pico_recorded_station(13_000_000_000, "PRIVATE-STATION-A", 7, -1.15, 1.5, 2.65),
            ]
            log_path.write_text("".join(lines), encoding="ascii", newline="")
            write_json(calib_path, pico_calibration())
            result = self.run_replay(log_path, calib_path, root / "state", "--pico-offline",
                                     "--pico-identity-control")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn("PRIVATE-STATION", result.stdout + result.stderr)
            self.assertIn("support_ch=7:0,1:0", result.stdout)
            self.assertNotIn("P3C-CHANNEL-", result.stdout)
            self.assertIn("stations=2", result.stdout)

    def test_synthetic_known_geometry_reaches_original_native_solver(self):
        with tempfile.TemporaryDirectory(prefix="p3c-synthetic-") as td:
            root = Path(td)
            log_path, calib_path = root / "known-scene.txt", root / "calib.json"
            write_json(calib_path, pico_calibration())
            make_synthetic_scene(log_path)
            isolated_state = root / "isolated-state"
            real_station_path = Path.home() / "AppData" / "Local" / "QuestLHSync" / "stations.json"
            real_station_before = real_station_path.read_bytes() if real_station_path.exists() else None
            result = self.run_replay(log_path, calib_path, root / "isolated-state", "--pico-offline",
                                     "--pico-identity-control", "--pico-cameras", "all", "--pings",
                                     )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("PICO_NATIVE acquire_candidate_successes=", result.stdout)
            self.assertRegex(result.stdout, r"PICO_NATIVE acquire_candidate_successes=[1-9]\d*")
            self.assertRegex(result.stdout, r"PICO_NATIVE .* accepted_alignments=[1-9]\d*")
            self.assertRegex(result.stdout, r"PICO_NATIVE .* final_locked=true")
            self.assertIn("PICO_STATUS", result.stdout)
            self.assertIn("condition=true", result.stdout)
            self.assertNotIn("SYNTH-0", result.stdout)
            for item in isolated_state.glob("**/*"):
                self.assertTrue(item.resolve().is_relative_to(isolated_state.resolve()))
            if real_station_path.exists():
                self.assertEqual(real_station_path.read_bytes(), real_station_before)


if __name__ == "__main__":
    unittest.main()
