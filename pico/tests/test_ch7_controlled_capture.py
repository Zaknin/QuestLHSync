import csv
import importlib.util
import json
import math
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "pico" / "tools" / "analyze_ch7_controlled.py"
SPEC = importlib.util.spec_from_file_location("analyze_ch7_controlled", MODULE_PATH)
analyzer = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = analyzer
SPEC.loader.exec_module(analyzer)


BASE_NS = 100_000_000_000
MARKERS = [
    ("BASELINE_READY", 1),
    ("OFF", 25),
    ("OFF_READY", 26),
    ("ON", 50),
    ("ON_READY", 51),
    ("SPINUP_DONE", 76),
    ("PASS_DONE", 100),
]


def p_record(t_ns, x=0.0, y=0.0, z=0.0, yaw=0.0):
    c, s = math.cos(yaw), math.sin(yaw)
    matrix = (c, 0, s, x, 0, 1, 0, y, -s, 0, c, z)
    return f"{t_ns} P 0 " + " ".join(f"{v:.9f}" for v in matrix) + "\n"


def s_record(t_ns):
    return f"{t_ns} S SYNTHETIC-PRIVATE-ID 7 0 0 5 1 0 0 0\n"


def f_record(t_ns, camera, sequence, blobs):
    fields = ["F", str(camera), str(sequence), str(t_ns), "80", str(len(blobs))]
    for x, y, peak in blobs:
        fields.extend((str(round(x * 10)), str(round(y * 10)), "4", str(peak)))
    return f"{t_ns} U " + " ".join(fields) + "\n"


def write_markers(path, markers=MARKERS):
    fields = ("Seq", "Action", "Channel", "QpcNs", "Utc")
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for index, (action, seconds) in enumerate(markers, 1):
            writer.writerow({"Seq": index, "Action": action, "Channel": 7,
                             "QpcNs": BASE_NS + seconds * 1_000_000_000,
                             "Utc": "2026-10-22T00:00:00.0000000+00:00"})


def write_calibration(path):
    cams = []
    rotations = {
        0: [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1],
        1: [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1],
        2: [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1],
        3: [-1, 0, 0, 0, 0, 1, 0, 0, 0, 0, -1, 0, 0, 0, 0, 1],
    }
    for camera_id, factory_id in ((0, 0), (3, 1), (4, 2), (5, 3)):
        cams.append({
            "id": camera_id,
            "factory_camera": factory_id,
            "size": [640, 480],
            "T_BS": rotations[factory_id],
            "intrinsics": [0.0, 200.0, 200.0, 320.0, 240.0],
            "distortion": [0.0, 0.0, 0.0, 0.0],
        })
    path.write_text(json.dumps({"cameras": cams, "mapping_verified": False,
                                "pose_verified": False}, separators=(",", ":")), encoding="utf-8")


def make_fixture(root, *, stable=True, add_baseline_signal=True, include_frames=True,
                 missing_camera_phase=None, malformed_baseline=False):
    recording = root / "synthetic.txt"
    markers = root / "markers.csv"
    calibration = root / "private-calibration.json"
    write_markers(markers)
    write_calibration(calibration)
    lines = []
    # Raw ch7 station pose; private serial token must never be copied into analysis output.
    for tick in range(300, 2300, 10):
        lines.append(s_record(BASE_NS + tick * 10_000_000))
    # Stable viewpoint or deliberately non-overlapping OFF viewpoint.
    for tick in range(0, 1001):
        t = tick / 10.0
        x = 0.0 if stable or not (26.0 <= t < 50.0) else 0.3
        yaw = 0.0 if stable or not (26.0 <= t < 50.0) else 0.3
        lines.append(p_record(BASE_NS + round(t * 1e9), x=x, yaw=yaw))
    if include_frames:
        sequence = 0
        for tick in range(0, 2500):  # 25 Hz over 100 seconds.
            t = tick / 25.0
            if not ((3.0 <= t < 23.0) or (28.0 <= t < 48.0) or (78.0 <= t < 98.0)):
                continue
            phase = "baseline" if t < 24 else ("off" if t < 49 else "restored")
            for camera in (0, 3, 4, 5):
                if missing_camera_phase == (phase, camera):
                    continue
                blobs = []
                if add_baseline_signal:
                    blobs.append((100.0, 100.0, 150))  # ON-selected, OFF-persistent negative control.
                    if phase in ("baseline", "restored") and camera in (4, 5):
                        blobs.append((320.0, 240.0, 180))
                if phase == "off" and camera in (4, 5):
                    blobs.append((500.0, 300.0, 220))  # must not be selected from OFF.
                lines.append(f_record(BASE_NS + round(t * 1e9), camera, sequence, blobs))
                sequence += 1
    if malformed_baseline:
        lines.append(f"{BASE_NS + 4 * 1_000_000_000} U F 4 999 1 80 2 3200 2400 3 150\n")
    # Sort exactly as QuestLHSync recordings are written.
    lines.sort(key=lambda line: int(line.split(" ", 1)[0]))
    recording.write_text("".join(lines), encoding="ascii", newline="")
    return recording, markers, calibration


class Ch7ControlledCaptureTests(unittest.TestCase):
    def test_positive_freezes_baseline_rois_and_finds_on_off_on_candidate(self):
        with tempfile.TemporaryDirectory() as td:
            recording, markers, calibration = make_fixture(Path(td))
            result = analyzer.analyze_capture(recording, markers, calibration)
            self.assertEqual(result["capture_quality"], "CAPTURE_QUALITY_PASS")
            self.assertGreaterEqual(result["pose_overlap"]["baseline_off"]["coverage_5cm_5deg"], 0.7)
            for camera in ("C4", "C5"):
                rows = result["rois"][camera]
                signal = next(row for row in rows if row["center_px"] == [320.0, 240.0])
                self.assertEqual(signal["selected_from"], "BASELINE_ON_ONLY")
                self.assertEqual(signal["classification"], "ON_OFF_ON_CANDIDATE")
                self.assertEqual(signal["matched"]["baseline_off"]["off"]["eligible_frames"],
                                 result["matched_camera_frames"][camera]["baseline_off"]["off"])
                control = next(row for row in rows if row["center_px"] == [100.0, 100.0])
                self.assertEqual(control["classification"], "REJECT_OFF_PERSISTENT")
                self.assertNotIn([500.0, 300.0], [row["center_px"] for row in rows])
            geom = result["geometry_fov"]
            self.assertGreater(geom["candidate"]["C4"]["baseline"]["eligible_samples"], 0)
            self.assertEqual(geom["candidate"]["C4"]["baseline"]["in_fov_samples"],
                             geom["placement_guess"]["C5"]["baseline"]["in_fov_samples"])

    def test_pose_mismatch_blocks_quality_even_when_each_phase_has_data(self):
        with tempfile.TemporaryDirectory() as td:
            recording, markers, calibration = make_fixture(Path(td), stable=False)
            result = analyzer.analyze_capture(recording, markers, calibration)
            self.assertEqual(result["capture_quality"], "CAPTURE_QUALITY_INSUFFICIENT")
            self.assertLess(result["pose_overlap"]["baseline_off"]["coverage_5cm_5deg"], 0.7)
            for camera in ("C0", "C3", "C4", "C5"):
                self.assertGreater(result["phases"]["off"]["camera_frames"][camera], 200)

    def test_no_baseline_roi_is_explicit_and_off_only_points_are_not_selected(self):
        with tempfile.TemporaryDirectory() as td:
            recording, markers, calibration = make_fixture(Path(td), add_baseline_signal=False)
            result = analyzer.analyze_capture(recording, markers, calibration)
            for camera in ("C4", "C5"):
                self.assertEqual(result["rois"][camera], [])
                self.assertEqual(result["roi_status"][camera], "NO_BASELINE_ROI_FROZEN")

    def test_short_phase_and_missing_camera_are_quality_failures(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            short_markers = list(MARKERS)
            short_markers[1] = ("OFF", 15)
            recording, markers, calibration = make_fixture(root)
            write_markers(markers, short_markers)
            result = analyzer.analyze_capture(recording, markers, calibration)
            self.assertEqual(result["capture_quality"], "CAPTURE_QUALITY_INSUFFICIENT")
            self.assertTrue(any("baseline hold" in error.lower() for error in result["quality_errors"]))

        with tempfile.TemporaryDirectory() as td:
            recording, markers, calibration = make_fixture(Path(td), missing_camera_phase=("off", 5))
            result = analyzer.analyze_capture(recording, markers, calibration)
            self.assertEqual(result["capture_quality"], "CAPTURE_QUALITY_INSUFFICIENT")
            self.assertTrue(any("fewer than" in error.lower() and "c5" in error.lower()
                                for error in result["quality_errors"]))

    def test_malformed_camera_record_blocks_capture_quality(self):
        with tempfile.TemporaryDirectory() as td:
            recording, markers, calibration = make_fixture(Path(td), malformed_baseline=True)
            result = analyzer.analyze_capture(recording, markers, calibration)
            self.assertEqual(result["capture_quality"], "CAPTURE_QUALITY_INSUFFICIENT")
            self.assertEqual(result["phases"]["baseline"]["malformed_records"], 1)

    def test_malformed_marker_sequence_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            recording, markers, calibration = make_fixture(Path(td))
            write_markers(markers, list(reversed(MARKERS)))
            with self.assertRaisesRegex(ValueError, "marker|sequence|monotonic"):
                analyzer.analyze_capture(recording, markers, calibration)

    def test_recording_and_marker_hashes_are_reported_without_private_ids(self):
        with tempfile.TemporaryDirectory() as td:
            recording, markers, calibration = make_fixture(Path(td))
            result = analyzer.analyze_capture(recording, markers, calibration)
            self.assertEqual(len(result["inputs"]["recording_sha256"]), 64)
            self.assertEqual(len(result["inputs"]["markers_sha256"]), 64)
            serialized = json.dumps(result)
            self.assertNotIn("SYNTHETIC-PRIVATE-ID", serialized)
            self.assertNotIn("0 0 5", serialized)

    def test_cli_writes_private_summary_without_overwriting_existing_output(self):
        with tempfile.TemporaryDirectory() as td:
            recording, markers, calibration = make_fixture(Path(td))
            output = Path(td) / "private-result.json"
            command = [sys.executable, str(MODULE_PATH), str(recording), str(markers),
                       "--calibration", str(calibration), "--output", str(output)]
            result = subprocess.run(command, text=True, capture_output=True, check=False)
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            saved = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(saved["capture_quality"], "CAPTURE_QUALITY_PASS")
            before = output.read_bytes()
            blocked = subprocess.run(command, text=True, capture_output=True, check=False)
            self.assertEqual(blocked.returncode, 2)
            self.assertIn("already exists", blocked.stdout)
            self.assertEqual(output.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
