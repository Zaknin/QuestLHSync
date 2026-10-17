"""Synthetic P3-B tests. No OpenVR runtime, Windows, or hardware needed."""
import json
import math
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from pico.tools.openvr_qpc_probe import (SAFETY, collect_one, encode_pose, execute,
                                          finish, publish, run_samples)


def pose(valid=True, connected=True, nonfinite=False):
    matrix = [[float(r == c) for c in range(4)] for r in range(3)]
    if nonfinite:
        matrix[0][0] = math.nan
    return SimpleNamespace(bDeviceIsConnected=connected, bPoseIsValid=valid,
                           eTrackingResult=200 if valid else 1,
                           mDeviceToAbsoluteTracking=SimpleNamespace(m=matrix),
                           vVelocity=SimpleNamespace(v=(.1, .2, .3)),
                           vAngularVelocity=SimpleNamespace(v=(.4, .5, .6)))


class Clock:
    frequency = 10_000_000

    def __init__(self, ticks=None):
        self.values = iter(ticks or [100, 200])

    def ticks(self):
        return next(self.values)


class FakeVR:
    def __init__(self, output=None):
        self.output = output or [pose()]
        self.calls = []

    def getDeviceToAbsoluteTrackingPose(self, origin, prediction, count):
        self.calls.append((origin, prediction, count))
        return self.output

    def getTrackedDeviceClass(self, i):
        return 1

    def getStringTrackedDeviceProperty(self, i, prop):
        return "Synthetic HMD"


class FakeAPI:
    TrackingUniverseStanding = 1
    TrackingUniverseSeated = 0
    VRApplication_Background = 3
    k_unMaxTrackedDeviceCount = 1
    Prop_ModelNumber_String = 1001

    def __init__(self, vr=None, fail=False):
        self.vr = vr or FakeVR()
        self.fail = fail
        self.started = self.shutdown_count = 0

    def init(self, mode):
        if self.fail:
            raise RuntimeError("SteamVR unavailable")
        self.started += 1
        assert mode == self.VRApplication_Background
        return self.vr

    def shutdown(self):
        self.shutdown_count += 1


class ProbeTests(unittest.TestCase):
    def test_valid_bracket_and_no_mutating_calls(self):
        vr = FakeVR()
        row = collect_one(vr, Clock(), origin=1, count=1, index=0)
        self.assertEqual(vr.calls, [(1, 0.0, 1)])
        self.assertEqual((row["qpc_before_tick"], row["qpc_after_tick"]), (100, 200))
        self.assertEqual(row["qpc_duration_ticks"], 100)
        self.assertEqual(row["devices"][0]["matrix_3x4"][1][1], 1.0)
        self.assertNotIn("sensor_timestamp", row)

    def test_invalid_and_disconnected_are_not_exported_as_poses(self):
        for p in (pose(valid=False), pose(connected=False)):
            item = encode_pose(p, 0)
            self.assertIsNone(item["matrix_3x4"])
            self.assertIsNone(item["velocity_m_s"])

    def test_nonfinite_is_fail_closed(self):
        row = collect_one(FakeVR([pose(nonfinite=True)]), Clock(), origin=1, count=1, index=0)
        self.assertTrue(row["error"].startswith("INVALID_POSE:"))
        self.assertFalse(row["devices"])
        self.assertEqual(finish([row], Clock.frequency)["status"], "BLOCKED")

    def test_reversed_qpc_is_fail_closed(self):
        row = collect_one(FakeVR(), Clock([200, 100]), origin=1, count=1, index=0)
        self.assertEqual(row["error"], "QPC_REVERSED")
        self.assertEqual(finish([row], Clock.frequency)["status"], "BLOCKED")

    def test_shutdown_called_once_on_normal_run(self):
        api = FakeAPI()
        records = execute(api, Clock(), seconds=1, hz=1, sleeper=lambda _: None,
                          monotonic=lambda: 0)
        self.assertEqual(api.shutdown_count, 1)
        self.assertEqual(records[-1]["status"], "PASS_HOST_QUERY")
        self.assertFalse(records[-1]["sensor_timestamp_proven"])
        self.assertFalse(records[0]["safety"]["exact_time"])

    def test_init_failure_is_published_as_blocked(self):
        api = FakeAPI(fail=True)
        records = execute(api, Clock(), seconds=1, hz=1)
        self.assertEqual(api.shutdown_count, 0)
        self.assertEqual(records[-1]["status"], "BLOCKED")
        self.assertEqual(records[1]["record_type"], "diagnostic_error")

    def test_inter_sample_clock_regression(self):
        rows = run_samples(FakeVR(), Clock([100, 200, 150, 250]),
                           origin=1, count=1, seconds=2, hz=1,
                           sleeper=lambda _: None, monotonic=lambda: 0)
        self.assertEqual(rows[1]["error"], "QPC_NONMONOTONIC_ACROSS_SAMPLES")
        self.assertFalse(rows[1]["devices"])

    def test_openvr_call_exception_keeps_bracket(self):
        class FailingVR(FakeVR):
            def getDeviceToAbsoluteTrackingPose(self, origin, prediction, count):
                raise RuntimeError("API failure")
        row = collect_one(FailingVR(), Clock(), origin=1, count=1, index=0)
        self.assertIn("API failure", row["error"])
        self.assertEqual(row["qpc_duration_ticks"], 100)

    def test_part_verified_manifest_and_sidecar_last(self):
        rows = [{"record_type": "header", "safety": SAFETY},
                {"record_type": "summary", "status": "BLOCKED"}]
        with tempfile.TemporaryDirectory() as tmp:
            result = publish(rows, tmp)
            self.assertTrue(Path(result["sha256"]).is_file())
            self.assertEqual(json.loads(Path(result["manifest"]).read_text())["status"], "BLOCKED")
            self.assertEqual(list(Path(tmp).glob("*.part")), [])
            self.assertIn(result["digest"], Path(result["sha256"]).read_text())

    def test_corrupt_smb_readback_never_commits(self):
        rows = [{"record_type": "summary", "status": "BLOCKED"}]
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(IOError, "mismatch"):
                publish(rows, tmp, readback=lambda _: b"tampered")
            self.assertFalse(list(Path(tmp).glob("*.sha256")))
            self.assertFalse(list(Path(tmp).glob("*.jsonl")))


if __name__ == "__main__":
    unittest.main()
