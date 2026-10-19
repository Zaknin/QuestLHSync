import hashlib
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

from pico.tools import p3a_m28c_logcat as m


EVENT = (
    b"P3A28C\tEVENT\t412\t10-19\t18:52:31.754\t17\t25\t"
    b"1234567890123\t1234567890123\tCSLTimestampTypeQtimer\n"
)
PROCESS = b"P3A28C\tPROCESS\t412\tcom.pico.quickcamera:service\n"


def protocol(*records, end=b"P3A28C\tEND\tOK\n", filter_record=True):
    rows = [b"P3A28C\tBEGIN\t1\n"]
    if filter_record:
        rows.append(b"P3A28C\tFILTER\tpid-marker-numeric-v1\n")
    rows.extend(records)
    rows.append(end)
    return b"".join(rows)


class M28CLogcatParserTests(unittest.TestCase):
    def parse(self, stdout, *, stderr=b"", returncode=0):
        return m.parse_probe_result(stdout, stderr=stderr, returncode=returncode)

    def test_valid_protocol_keeps_only_allowlisted_numeric_fields(self):
        result = self.parse(protocol(PROCESS, EVENT))
        self.assertTrue(result["ok"])
        self.assertEqual(result["record_count"], 5)
        self.assertEqual(result["records"], [
            {"kind": "PROCESS", "pid": "412", "name": "com.pico.quickcamera:service"},
            {"kind": "EVENT", "pid": "412", "logcat_date": "10-19", "logcat_time": "18:52:31.754",
             "request_id": "17", "frame_count_label": "25",
             "timestamp": "1234567890123", "mono_timestamp_label": "1234567890123",
             "source_label": "CSLTimestampTypeQtimer"},
        ])

    def test_crlf_and_mixed_line_endings_are_normalized_at_line_boundaries(self):
        raw = protocol(PROCESS, EVENT).replace(b"\n", b"\r\n")
        result = self.parse(raw)
        self.assertTrue(result["ok"])
        self.assertEqual(result["records"][1]["request_id"], "17")

        mixed = b"P3A28C\tBEGIN\t1\r\nP3A28C\tFILTER\tpid-marker-numeric-v1\n" + PROCESS + EVENT + b"P3A28C\tEND\tOK\r\n"
        self.assertTrue(self.parse(mixed)["ok"])

    def test_standalone_cr_is_invalid_line_ending_without_raw_bytes(self):
        result = self.parse(protocol(PROCESS).replace(b"\tPROCESS\t", b"\rPROCESS\t", 1))
        self.assertEqual(result["error_code"], "INVALID_LINE_ENDING")
        self.assertNotIn("records", result)
        self.assertNotIn("PROCESS", str(result))

    def test_embedded_control_character_is_rejected_without_echo(self):
        raw_secret = b"P3A28C\tPROCESS\t412\tcom.pico.quickcamera\x1b[31msecret\n"
        result = self.parse(protocol(raw_secret))
        self.assertEqual(result["error_code"], "INVALID_CONTROL_CHARACTER")
        self.assertNotIn("secret", json.dumps(result))

    def test_missing_newline_and_missing_end_record_have_distinct_diagnostics(self):
        no_final_newline = protocol(PROCESS)[:-1]
        self.assertEqual(self.parse(no_final_newline)["error_code"], "MISSING_PROTOCOL_TERMINATOR")

        no_end = b"P3A28C\tBEGIN\t1\nP3A28C\tFILTER\tpid-marker-numeric-v1\n" + PROCESS
        self.assertEqual(self.parse(no_end)["error_code"], "MISSING_PROTOCOL_TERMINATOR")

    def test_malformed_protocol_record_is_rejected(self):
        malformed = b"P3A28C\tEVENT\t412\t17\t25\t123\t123\tCSLTimestampTypeQtimer\tEXTRA\n"
        result = self.parse(protocol(PROCESS, malformed))
        self.assertEqual(result["error_code"], "MALFORMED_PROTOCOL_RECORD")
        self.assertEqual(result["line_number"], 4)

    def test_missing_filter_attestation_is_not_accepted(self):
        result = self.parse(protocol(PROCESS, filter_record=False))
        self.assertEqual(result["error_code"], "REMOTE_FILTER_UNVERIFIED")

    def test_record_limit_counts_envelope_and_payload_records(self):
        many = [PROCESS] * 39
        result = self.parse(protocol(*many))
        self.assertEqual(result["error_code"], "OUTPUT_LINE_LIMIT")
        self.assertEqual(result["record_count"], 42)

    def test_64k_boundary_overflow_is_reported_as_truncation(self):
        raw = b"Z" * (64 * 1024 + 1)
        result = self.parse(raw)
        self.assertEqual(result["error_code"], "OUTPUT_TRUNCATED")
        self.assertEqual(result["byte_count"], len(raw))
        self.assertNotIn("Z", json.dumps(result))

    def test_remote_logcat_unsupported_option_status_is_safe(self):
        end = b"P3A28C\tEND\tERROR\tLOGCAT_UNSUPPORTED_OPTION\n"
        result = self.parse(protocol(end=end), returncode=1)
        self.assertEqual(result["error_code"], "LOGCAT_UNSUPPORTED_OPTION")

    def test_remote_command_failure_status_is_safe(self):
        end = b"P3A28C\tEND\tERROR\tREMOTE_COMMAND_FAILURE\n"
        result = self.parse(protocol(end=end), returncode=1)
        self.assertEqual(result["error_code"], "REMOTE_COMMAND_FAILURE")

    def test_nonempty_stderr_never_merges_into_stdout_or_result(self):
        result = self.parse(protocol(PROCESS, EVENT), stderr=b"PRIVATE-STDERR-MARKER\n")
        self.assertEqual(result["error_code"], "REMOTE_COMMAND_FAILURE")
        self.assertNotIn("PRIVATE-STDERR-MARKER", json.dumps(result))

    def test_unsupported_option_is_classified_from_separate_stderr(self):
        result = self.parse(
            b"P3A28C\tBEGIN\t1\nP3A28C\tFILTER\tpid-marker-numeric-v1\n"
            b"P3A28C\tEND\tERROR\tREMOTE_COMMAND_FAILURE\n",
            stderr=b"logcat: unrecognized option -- t\n",
            returncode=1,
        )
        self.assertEqual(result["error_code"], "LOGCAT_UNSUPPORTED_OPTION")
        self.assertNotIn("unrecognized option", json.dumps(result))

    def test_approximate_3540_byte_bad_response_returns_only_safe_metadata(self):
        prefix = b"P3A28C\tBEGIN\t1\nP3A28C\tFILTER\tpid-marker-numeric-v1\n" + PROCESS
        suffix = b"\nP3A28C\tEND\tOK\n"
        malformed = b"P3A28C\tPRIVATE-LOG-LINE\t" + b"x" * (3540 - len(prefix) - len(suffix) - len(b"P3A28C\tPRIVATE-LOG-LINE\t"))
        raw = prefix + malformed + suffix
        self.assertEqual(len(raw), 3540)
        result = self.parse(raw)
        self.assertEqual(result["byte_count"], 3540)
        self.assertEqual(result["error_code"], "MALFORMED_PROTOCOL_RECORD")
        self.assertNotIn("private-log-line", json.dumps(result))


class M28CProbeContractTests(unittest.TestCase):
    def test_reconstructed_probe_hash_and_exact_adb_shell_vector(self):
        actual_hash = hashlib.sha256(m._SCRIPT_PATH.read_bytes().replace(b"\\r\\n", b"\\n")).hexdigest()
        self.assertEqual(m.PROBE_SCRIPT_SHA256, actual_hash)
        self.assertEqual(m.PROBE_SCRIPT, m._SCRIPT_PATH.read_bytes().replace(b"\\r\\n", b"\\n").decode("ascii"))
        self.assertEqual(m.adb_shell_argv(), [
            "-s", "192.0.2.42:5555", "shell", "sh", "-c", m.PROBE_SCRIPT,
        ])
        self.assertEqual(m.adb_shell_argv()[-3:-1], ["sh", "-c"])

    @unittest.skipUnless(os.name == "nt", "Windows CreateProcess argument serialization check")
    def test_windows_argument_serialization_keeps_multiline_script_in_one_argument(self):
        argv = m.adb_shell_argv()
        serializer = Path(sys.executable)
        child = "import base64,json,sys; print(base64.b64encode(json.dumps(sys.argv[1:]).encode()).decode())"
        completed = subprocess.run(
            [str(serializer), "-c", child, *argv], check=True,
            capture_output=True, text=True,
        )
        decoded = json.loads(__import__("base64").b64decode(completed.stdout.strip()))
        self.assertEqual(decoded, argv)


if __name__ == "__main__":
    unittest.main()
