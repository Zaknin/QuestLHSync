import base64
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pico.tools import p3a_m27b_camx_provider as m27b
from pico.tools import p3a_m28d_callback_logs as m


TARGET = "m28d-test.invalid:5555"
TARGET_ENV = m27b.TARGET_SERIAL_ENV
ENV = {TARGET_ENV: TARGET}


def protocol(*rows, end=b"P3A28D\tEND\tOK\n"):
    return (b"P3A28D\tBEGIN\t1\nP3A28D\tFILTER\tpid-marker-numeric-v1\n"
            + b"".join(rows) + end)


PROCESS = b"P3A28D\tPROCESS\t412\tcom.pico.quickcamera:service\n"
EVENT = (
    b"P3A28D\tEVENT\t412\t10-19\t18:52:31.754\t17\t25\t"
    b"1234567890123\t1234567890123\tCSLTimestampTypeQtimer\n"
)


class M28DProtocolTests(unittest.TestCase):
    def setUp(self):
        self.target_hash = patch.object(
            m27b, "TARGET_SERIAL_SHA256", hashlib.sha256(TARGET.encode("utf-8")).hexdigest(),
        )
        self.target_hash.start()

    def tearDown(self):
        self.target_hash.stop()

    def test_callback_record_accepts_signed_64_bit_frame_count(self):
        for value in ("-9223372036854775808", "9223372036854775807"):
            event = EVENT.replace(b"\t25\t", f"\t{value}\t".encode())
            result = m.parse_probe_result(protocol(PROCESS, event))
            self.assertEqual(result["status"], "CALLBACK_LOG_OBSERVED")
            self.assertEqual(result["records"][1]["frame_count_label"], value)

    def test_frame_count_outside_signed_64_bit_is_rejected_without_raw_text(self):
        for value in ("9223372036854775808", "-9223372036854775809"):
            event = EVENT.replace(b"\t25\t", f"\t{value}\t".encode())
            result = m.parse_probe_result(protocol(PROCESS, event))
            self.assertEqual(result["error_code"], "MALFORMED_PROTOCOL_RECORD")
            self.assertNotIn(value, json.dumps(result))

    def test_no_matching_callback_record_is_distinct_from_observed_callback(self):
        result = m.parse_probe_result(protocol(PROCESS))
        self.assertEqual(result["status"], "NO_MATCHING_LOG_RECORDS_OBSERVED")
        self.assertEqual(result["records"], [{"kind": "PROCESS", "pid": "412",
                                               "name": "com.pico.quickcamera:service"}])

    def test_crlf_is_normalized_only_at_line_boundary(self):
        raw = protocol(PROCESS, EVENT).replace(b"\n", b"\r\n")
        self.assertEqual(m.parse_probe_result(raw)["status"], "CALLBACK_LOG_OBSERVED")
        bad = protocol(PROCESS.replace(b"\tPROCESS\t", b"\rPROCESS\t"))
        self.assertEqual(m.parse_probe_result(bad)["error_code"], "INVALID_LINE_ENDING")

    def test_malformed_records_and_missing_terminator_fail_closed(self):
        malformed = protocol(b"P3A28D\tEVENT\t412\tINJECTED\n")
        self.assertEqual(m.parse_probe_result(malformed)["error_code"], "MALFORMED_PROTOCOL_RECORD")
        self.assertEqual(m.parse_probe_result(protocol(PROCESS)[:-1])["error_code"],
                         "MISSING_PROTOCOL_TERMINATOR")

    def test_line_and_byte_caps_are_enforced(self):
        too_many = protocol(*(PROCESS for _ in range(39)))
        self.assertEqual(m.parse_probe_result(too_many)["error_code"], "OUTPUT_LINE_LIMIT")
        too_large = b"X" * (m.MAX_OUTPUT_BYTES + 1)
        self.assertEqual(m.parse_probe_result(too_large)["error_code"], "OUTPUT_TRUNCATED")

    def test_capability_statuses_are_specific_and_safe(self):
        ok = b"P3A28D\tCAPABILITY\tLOGCAT\tOPTIONS_OK\n"
        bad = b"P3A28D\tCAPABILITY\tLOGCAT\tOPTIONS_UNSUPPORTED\n"
        self.assertEqual(m.parse_logcat_capability(ok, 0), "READY")
        self.assertEqual(m.parse_logcat_capability(bad, 0), "LOGCAT_CAPABILITY_BLOCKED")
        self.assertEqual(m.parse_logcat_capability(b"raw private diagnostic\n", 0),
                         "OUTPUT_FRAMING_BLOCKED")

    def test_shell_v2_capability_requires_exact_marker_and_exit_status(self):
        marker = b"P3A28D\tSHELL_V2\tOK\n"
        self.assertTrue(m.validate_shell_v2_result(marker, 23, 0))
        self.assertTrue(m.validate_shell_v2_result(marker.replace(b"\n", b"\r\n"), 23, 0))
        self.assertFalse(m.validate_shell_v2_result(marker.replace(b"\n", b"\r"), 23, 0))
        self.assertFalse(m.validate_shell_v2_result(b"P3A28D\tSHELL_V2\r\tOK\n", 23, 0))
        self.assertFalse(m.validate_shell_v2_result(marker, 0, 0))
        self.assertFalse(m.validate_shell_v2_result(marker + b"extra\n", 23, 0))
        self.assertFalse(m.validate_shell_v2_result(marker, 23, 1))

    def test_adb_allowlist_requires_exact_target_and_fixed_stdin_script(self):
        selector = ["-s", TARGET]
        with patch.dict(os.environ, ENV, clear=False):
            self.assertTrue(m.allowed_adb_arguments([*selector, "get-state"], selector))
            self.assertTrue(m.allowed_adb_arguments(
                [*selector, "shell", "-T", "sh", "-s"], selector,
                stdin_bytes=m.PROBE_SCRIPT_BYTES))
            self.assertFalse(m.allowed_adb_arguments(
                [*selector, "shell", "-T", "sh", "-s"], selector,
                stdin_bytes=b"echo arbitrary"))
            self.assertFalse(m.allowed_adb_arguments(
                ["-s", "other-device", "get-state"], selector))
            self.assertFalse(m.allowed_adb_arguments(
                [*selector, "shell", "-c", "cat /proc/1/maps"], selector))

    def test_script_hashes_are_exact_and_stable(self):
        self.assertEqual(m.PROBE_SHA256, hashlib.sha256(m.PROBE_SCRIPT_BYTES).hexdigest())
        self.assertEqual(m.CAPABILITY_SHA256, hashlib.sha256(m.CAPABILITY_SCRIPT_BYTES).hexdigest())
        self.assertEqual(m.SHELL_V2_SHA256, hashlib.sha256(m.SHELL_V2_SCRIPT_BYTES).hexdigest())
        self.assertNotIn(b"logcat", m.SHELL_V2_SCRIPT_BYTES)

    def test_adb_transport_uses_stdin_and_shell_without_pty(self):
        with patch.dict(os.environ, ENV, clear=False):
            argv = m.adb_shell_argv(TARGET)
        self.assertEqual(argv, ["-s", TARGET, "shell", "-T", "sh", "-s"])
        self.assertEqual(argv[-3:], ["-T", "sh", "-s"])
        child = (
            "import base64,json,sys; "
            "print(json.dumps({'argv':sys.argv[1:],'stdin':base64.b64encode(sys.stdin.buffer.read()).decode()}))"
        )
        complete = subprocess.run(
            [sys.executable, "-c", child, *argv], input=m.PROBE_SCRIPT_BYTES,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5, check=True,
        )
        decoded = json.loads(complete.stdout)
        self.assertEqual(decoded["argv"], argv)
        self.assertEqual(base64.b64decode(decoded["stdin"]), m.PROBE_SCRIPT_BYTES)
        self.assertEqual(complete.stderr, b"")

    def test_bounded_process_preserves_separate_channels_and_exit_code(self):
        child = "import sys; d=sys.stdin.buffer.read(); sys.stdout.buffer.write(d); sys.stderr.write('private'); sys.exit(23)"
        code, stdout, stderr_count = m.run_bounded_process(
            [sys.executable, "-c", child], stdin_bytes=b"fixed-script", timeout=5,
            max_output_bytes=1024,
        )
        self.assertEqual((code, stdout, stderr_count), (23, b"fixed-script", 7))

    def test_bounded_process_stops_on_timeout_and_aggregate_output_limit(self):
        sleeper = "import time; time.sleep(5)"
        with self.assertRaises(subprocess.TimeoutExpired):
            m.run_bounded_process([sys.executable, "-c", sleeper], stdin_bytes=None,
                                  timeout=0.1, max_output_bytes=1024)
        chatter = "import sys; sys.stdout.write('x'*2000); sys.stderr.write('y'*2000)"
        with self.assertRaises(m.ProcessOutputLimitError):
            m.run_bounded_process([sys.executable, "-c", chatter], stdin_bytes=None,
                                  timeout=5, max_output_bytes=1024)

    def test_synthetic_collector_passes_only_exact_allowlisted_commands(self):
        calls = []

        def responder(argv, *, stdin_bytes, timeout):
            calls.append((list(argv), stdin_bytes, timeout))
            if argv == ["-s", TARGET, "get-state"]:
                return 0, b"device\n", 0
            if argv == ["-s", TARGET, "shell", "getprop", "ro.build.fingerprint"]:
                return 0, (m.TARGET_FINGERPRINT + "\n").encode(), 0
            if argv == ["-s", TARGET, "shell", "getprop", "ro.product.cpu.abi"]:
                return 0, b"arm64-v8a\n", 0
            if argv == ["-s", TARGET, "shell", "-T", "sh", "-s"]:
                if stdin_bytes == m.SHELL_V2_SCRIPT_BYTES:
                    return 23, b"P3A28D\tSHELL_V2\tOK\n", 0
                if stdin_bytes == m.CAPABILITY_SCRIPT_BYTES:
                    return 0, b"P3A28D\tCAPABILITY\tLOGCAT\tOPTIONS_OK\n", 0
                if stdin_bytes == m.PROBE_SCRIPT_BYTES:
                    return 0, protocol(PROCESS, EVENT), 0
            raise AssertionError("collector attempted an unexpected ADB vector or script")

        with patch.dict(os.environ, ENV, clear=False):
            result = m.collect(TARGET, executor=responder, owner_authorized=True)
        self.assertEqual(result["status"], "CALLBACK_LOG_OBSERVED")
        self.assertEqual(result["adb_command_count"], 6)
        self.assertEqual(result["normalized_record_count"], 5)
        self.assertTrue(result["logcat_snapshot_attempted"])
        self.assertFalse(result["methods"]["raw_logcat_stdout_saved"])
        self.assertEqual([row[0] for row in calls[:3]], [
            ["-s", TARGET, "get-state"],
            ["-s", TARGET, "shell", "getprop", "ro.build.fingerprint"],
            ["-s", TARGET, "shell", "getprop", "ro.product.cpu.abi"],
        ])
        self.assertEqual([row[1] for row in calls[3:]], [
            m.SHELL_V2_SCRIPT_BYTES, m.CAPABILITY_SCRIPT_BYTES, m.PROBE_SCRIPT_BYTES,
        ])
        self.assertTrue(all(row[2] <= m.MAX_COMMAND_SECONDS for row in calls))

    def test_capability_failure_stops_before_snapshot(self):
        calls = []

        def responder(argv, *, stdin_bytes, timeout):
            calls.append((argv, stdin_bytes))
            if argv[-1:] == ["get-state"]:
                return 0, b"device\n", 0
            if argv[-2:] == ["getprop", "ro.build.fingerprint"]:
                return 0, (m.TARGET_FINGERPRINT + "\n").encode(), 0
            if argv[-2:] == ["getprop", "ro.product.cpu.abi"]:
                return 0, b"arm64-v8a\n", 0
            if stdin_bytes == m.SHELL_V2_SCRIPT_BYTES:
                return 23, b"P3A28D\tSHELL_V2\tOK\n", 0
            if stdin_bytes == m.CAPABILITY_SCRIPT_BYTES:
                return 0, b"P3A28D\tCAPABILITY\tLOGCAT\tOPTIONS_UNSUPPORTED\n", 0
            raise AssertionError("snapshot must not be called after capability failure")

        with patch.dict(os.environ, ENV, clear=False):
            report = m.collect(TARGET, executor=responder, owner_authorized=True)
        self.assertEqual(report["status"], "LOGCAT_CAPABILITY_BLOCKED")
        self.assertFalse(report["logcat_snapshot_attempted"])
        self.assertEqual(len(calls), 5)

    def test_wrong_fingerprint_stops_before_any_remote_script(self):
        calls = []

        def responder(argv, *, stdin_bytes, timeout):
            calls.append(argv)
            if argv[-1:] == ["get-state"]:
                return 0, b"device\n", 0
            return 0, b"different-build\n", 0

        with patch.dict(os.environ, ENV, clear=False):
            report = m.collect(TARGET, executor=responder, owner_authorized=True)
        self.assertEqual(report["status"], "ADB_TRANSPORT_BLOCKED")
        self.assertEqual(report["diagnostics"][-1]["code"], "FINGERPRINT_MISMATCH")
        self.assertEqual(len(calls), 2)
        self.assertTrue(all("-T" not in call for call in calls))

    def test_shell_v2_marker_mismatch_is_framing_failure_after_exit_status_23(self):
        def responder(argv, *, stdin_bytes, timeout):
            if argv[-1:] == ["get-state"]:
                return 0, b"device\n", 0
            if argv[-2:] == ["getprop", "ro.build.fingerprint"]:
                return 0, (m.TARGET_FINGERPRINT + "\n").encode(), 0
            if argv[-2:] == ["getprop", "ro.product.cpu.abi"]:
                return 0, b"arm64-v8a\n", 0
            if stdin_bytes == m.SHELL_V2_SCRIPT_BYTES:
                return 23, b"P3A28D\tSHELL_V2\tEXTRA\n", 0
            raise AssertionError("collection must stop at a malformed capability marker")

        with patch.dict(os.environ, ENV, clear=False):
            report = m.collect(TARGET, executor=responder, owner_authorized=True)
        self.assertEqual(report["status"], "OUTPUT_FRAMING_BLOCKED")
        self.assertEqual(report["diagnostics"][-1]["code"], "SHELL_V2_MARKER_MISMATCH")
        self.assertFalse(report["logcat_snapshot_attempted"])

    def test_crlf_shell_v2_marker_round_trip_reaches_logcat_probe(self):
        calls = []

        def responder(argv, *, stdin_bytes, timeout):
            calls.append(stdin_bytes)
            if argv[-1:] == ["get-state"]:
                return 0, b"device\n", 0
            if argv[-2:] == ["getprop", "ro.build.fingerprint"]:
                return 0, (m.TARGET_FINGERPRINT + "\n").encode(), 0
            if argv[-2:] == ["getprop", "ro.product.cpu.abi"]:
                return 0, b"arm64-v8a\n", 0
            if stdin_bytes == m.SHELL_V2_SCRIPT_BYTES:
                return 23, b"P3A28D\tSHELL_V2\tOK\r\n", 0
            if stdin_bytes == m.CAPABILITY_SCRIPT_BYTES:
                return 0, b"P3A28D\tCAPABILITY\tLOGCAT\tOPTIONS_OK\n", 0
            if stdin_bytes == m.PROBE_SCRIPT_BYTES:
                return 0, protocol(PROCESS), 0
            raise AssertionError("unexpected fixed script")

        with patch.dict(os.environ, ENV, clear=False):
            report = m.collect(TARGET, executor=responder, owner_authorized=True)
        self.assertEqual(report["status"], "NO_MATCHING_LOG_RECORDS_OBSERVED")
        self.assertTrue(report["logcat_snapshot_attempted"])
        self.assertEqual(calls[3:], [m.SHELL_V2_SCRIPT_BYTES, m.CAPABILITY_SCRIPT_BYTES, m.PROBE_SCRIPT_BYTES])

    def test_dry_run_is_device_free_and_keeps_all_safety_gates_false(self):
        plan = m.dry_run_plan()
        self.assertEqual(plan["status"], "DRY_RUN_ONLY")
        self.assertFalse(plan["device_facing_calls_performed"])
        for key in ("exact_time", "mapping_verified", "pose_verified",
                    "shared_buffer_identity_verified", "frame_meta_bridge_verified",
                    "physical_event_verified", "live_lighthouse_correction_allowed"):
            self.assertFalse(plan["safety"][key])


if __name__ == "__main__":
    unittest.main()
