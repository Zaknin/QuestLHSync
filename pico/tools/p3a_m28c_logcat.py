"""Offline parser and argument contract for the reconstructed M2.8C probe.

The original M2.8C collector was not recovered. This module deliberately has
no native ADB executor; its shell vector is inspectable and the probe is only
run against synthetic local POSIX fixtures by the integration harness.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any


# Documentation/test-only RFC 5737 address; this module has no ADB executor.
TARGET_SERIAL = "192.0.2.42:5555"
MAX_BYTES = 64 * 1024
MAX_RECORDS = 40
FILTER_VERSION = "pid-marker-numeric-v1"
SOURCE_LABEL = "CSLTimestampTypeQtimer"
ERROR_CODES = frozenset({
    "OUTPUT_LINE_LIMIT",
    "INVALID_CONTROL_CHARACTER",
    "INVALID_LINE_ENDING",
    "MALFORMED_PROTOCOL_RECORD",
    "MISSING_PROTOCOL_TERMINATOR",
    "OUTPUT_TRUNCATED",
    "REMOTE_FILTER_UNVERIFIED",
    "LOGCAT_UNSUPPORTED_OPTION",
    "REMOTE_COMMAND_FAILURE",
})

_SCRIPT_PATH = Path(__file__).with_name("p3a_m28c_logcat_probe.sh")
_script_bytes = _SCRIPT_PATH.read_bytes().replace(b"\r\n", b"\n")
if b"\r" in _script_bytes:
    raise RuntimeError("M2.8C fixed probe has a standalone CR byte")
PROBE_SCRIPT = _script_bytes.decode("ascii")
PROBE_SCRIPT_SHA256 = hashlib.sha256(_script_bytes).hexdigest()

_PROCESS_NAME = re.compile(r"[A-Za-z0-9_.:@-]{1,256}\Z", re.ASCII)
_PROCESS_MATCH = re.compile(r"(?:quickcamera|pvr|camera.*hidl|hidl.*camera)", re.IGNORECASE | re.ASCII)
_PID = re.compile(r"[0-9]{1,10}\Z", re.ASCII)
_SIGNED_I64 = re.compile(r"-?(?:0|[1-9][0-9]*)\Z", re.ASCII)
_UNSIGNED_U32 = re.compile(r"(?:0|[1-9][0-9]*)\Z", re.ASCII)
_DATE = re.compile(r"[0-9]{2}-[0-9]{2}\Z", re.ASCII)
_TIME = re.compile(r"[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{3}\Z", re.ASCII)
_UNSUPPORTED = (b"unknown option", b"unrecognized option", b"invalid option")


def adb_shell_argv() -> list[str]:
    """Return the exact target-bound remote shell vector; never execute it."""
    return ["-s", TARGET_SERIAL, "shell", "sh", "-c", PROBE_SCRIPT]


def _line_count(data: bytes) -> int:
    return data.count(b"\n")


def _failure(
    code: str,
    byte_count: int,
    record_count: int,
    *,
    line_number: int | None = None,
    offset: int | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "ok": False,
        "error_code": code,
        "byte_count": byte_count,
        "record_count": record_count,
    }
    if line_number is not None:
        result["line_number"] = line_number
    if offset is not None:
        result["offset"] = offset
    return result


def _i64(value: str) -> bool:
    if not _SIGNED_I64.fullmatch(value):
        return False
    try:
        number = int(value, 10)
    except ValueError:
        return False
    return -(1 << 63) <= number <= (1 << 63) - 1


def _u32(value: str) -> bool:
    if not _UNSIGNED_U32.fullmatch(value):
        return False
    return int(value, 10) <= (1 << 32) - 1


def _safe_stderr_error(stderr: bytes) -> str | None:
    lowered = stderr.lower()
    if any(pattern in lowered for pattern in _UNSUPPORTED):
        return "LOGCAT_UNSUPPORTED_OPTION"
    if stderr:
        return "REMOTE_COMMAND_FAILURE"
    return None


def parse_probe_result(
    stdout: bytes,
    *,
    stderr: bytes = b"",
    returncode: int = 0,
) -> dict[str, Any]:
    """Parse only normalized P3A28C records and emit metadata-only failures."""
    if not isinstance(stdout, bytes) or not isinstance(stderr, bytes):
        return _failure("REMOTE_COMMAND_FAILURE", 0, 0)

    byte_count = len(stdout) + len(stderr)
    record_count = _line_count(stdout)
    if len(stdout) > MAX_BYTES or (len(stdout) == MAX_BYTES and not stdout.endswith(b"\n")):
        return _failure("OUTPUT_TRUNCATED", byte_count, record_count)
    if record_count > MAX_RECORDS:
        return _failure("OUTPUT_LINE_LIMIT", byte_count, record_count)

    stderr_error = _safe_stderr_error(stderr)
    if stderr_error is not None:
        return _failure(stderr_error, byte_count, record_count)
    if not stdout:
        if returncode:
            return _failure("REMOTE_COMMAND_FAILURE", byte_count, record_count)
        return _failure("MISSING_PROTOCOL_TERMINATOR", byte_count, record_count)
    if not stdout.endswith(b"\n"):
        return _failure("MISSING_PROTOCOL_TERMINATOR", byte_count, record_count, offset=len(stdout))

    raw_lines = stdout.split(b"\n")[:-1]
    lines: list[str] = []
    offset = 0
    for line_number, raw_line in enumerate(raw_lines, start=1):
        line = raw_line
        if line.endswith(b"\r"):
            line = line[:-1]
        if b"\r" in line:
            return _failure("INVALID_LINE_ENDING", byte_count, record_count,
                            line_number=line_number, offset=offset + line.index(b"\r"))
        for index, byte in enumerate(line):
            if (byte < 0x20 and byte != 0x09) or byte == 0x7F:
                return _failure("INVALID_CONTROL_CHARACTER", byte_count, record_count,
                                line_number=line_number, offset=offset + index)
        try:
            decoded = line.decode("ascii")
        except UnicodeDecodeError as exc:
            return _failure("MALFORMED_PROTOCOL_RECORD", byte_count, record_count,
                            line_number=line_number, offset=offset + exc.start)
        lines.append(decoded)
        offset += len(raw_line) + 1

    if not lines or not lines[-1].startswith("P3A28C\tEND\t"):
        return _failure("MISSING_PROTOCOL_TERMINATOR", byte_count, record_count,
                        line_number=len(lines) or 1, offset=len(stdout))
    if lines[0].split("\t") != ["P3A28C", "BEGIN", "1"]:
        return _failure("MALFORMED_PROTOCOL_RECORD", byte_count, record_count, line_number=1, offset=0)
    if len(lines) < 3:
        return _failure("REMOTE_FILTER_UNVERIFIED", byte_count, record_count, line_number=2, offset=0)

    filter_fields = lines[1].split("\t")
    if filter_fields != ["P3A28C", "FILTER", FILTER_VERSION]:
        if len(filter_fields) >= 2 and filter_fields[:2] == ["P3A28C", "FILTER"]:
            return _failure("REMOTE_FILTER_UNVERIFIED", byte_count, record_count, line_number=2, offset=0)
        return _failure("REMOTE_FILTER_UNVERIFIED", byte_count, record_count, line_number=2, offset=0)

    records: list[dict[str, str]] = []
    processes: dict[str, str] = {}
    saw_event = False
    end_fields: list[str] | None = None
    for line_number, line in enumerate(lines[2:], start=3):
        fields = line.split("\t")
        if fields[0] != "P3A28C":
            return _failure("MALFORMED_PROTOCOL_RECORD", byte_count, record_count, line_number=line_number)
        kind = fields[1] if len(fields) > 1 else ""
        if kind == "PROCESS":
            if saw_event or len(fields) != 4:
                return _failure("MALFORMED_PROTOCOL_RECORD", byte_count, record_count, line_number=line_number)
            _, _, pid, name = fields
            if not _PID.fullmatch(pid) or not _PROCESS_NAME.fullmatch(name) or not _PROCESS_MATCH.search(name) or pid in processes:
                return _failure("MALFORMED_PROTOCOL_RECORD", byte_count, record_count, line_number=line_number)
            processes[pid] = name
            records.append({"kind": "PROCESS", "pid": pid, "name": name})
            continue
        if kind == "EVENT":
            saw_event = True
            if len(fields) != 10:
                return _failure("MALFORMED_PROTOCOL_RECORD", byte_count, record_count, line_number=line_number)
            _, _, pid, date, time, request_id, frame_count, timestamp, mono_timestamp, source = fields
            if (
                not _PID.fullmatch(pid)
                or pid not in processes
                or not _DATE.fullmatch(date)
                or not _TIME.fullmatch(time)
                or not _i64(request_id)
                or not _u32(frame_count)
                or not _i64(timestamp)
                or not _i64(mono_timestamp)
                or source != SOURCE_LABEL
            ):
                return _failure("MALFORMED_PROTOCOL_RECORD", byte_count, record_count, line_number=line_number)
            records.append({
                "kind": "EVENT", "pid": pid, "logcat_date": date, "logcat_time": time,
                "request_id": request_id, "frame_count_label": frame_count,
                "timestamp": timestamp, "mono_timestamp_label": mono_timestamp,
                "source_label": source,
            })
            continue
        if kind == "END":
            if line_number != len(lines):
                return _failure("MALFORMED_PROTOCOL_RECORD", byte_count, record_count, line_number=line_number)
            end_fields = fields
            break
        return _failure("MALFORMED_PROTOCOL_RECORD", byte_count, record_count, line_number=line_number)

    if end_fields is None:
        return _failure("MISSING_PROTOCOL_TERMINATOR", byte_count, record_count, line_number=len(lines), offset=len(stdout))

    if end_fields == ["P3A28C", "END", "NOT_OBSERVED", "NO_TARGET_PROCESSES"]:
        if processes or records or returncode != 0:
            return _failure("MALFORMED_PROTOCOL_RECORD", byte_count, record_count, line_number=len(lines))
        return {"ok": True, "status": "NOT_OBSERVED", "byte_count": byte_count,
                "record_count": record_count, "records": []}

    if len(end_fields) == 4 and end_fields[:3] == ["P3A28C", "END", "ERROR"]:
        code = end_fields[3]
        if code not in ERROR_CODES:
            return _failure("MALFORMED_PROTOCOL_RECORD", byte_count, record_count, line_number=len(lines))
        if returncode == 0:
            return _failure("REMOTE_COMMAND_FAILURE", byte_count, record_count)
        return _failure(code, byte_count, record_count)

    if end_fields != ["P3A28C", "END", "OK"]:
        return _failure("MALFORMED_PROTOCOL_RECORD", byte_count, record_count, line_number=len(lines))
    if returncode != 0:
        return _failure("REMOTE_COMMAND_FAILURE", byte_count, record_count)
    return {"ok": True, "status": "OK", "byte_count": byte_count,
            "record_count": record_count, "records": records}
