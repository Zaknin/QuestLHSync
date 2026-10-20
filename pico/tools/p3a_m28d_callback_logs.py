"""M2.8D: bounded, filtered callback-log snapshot for one owner-bound Pico.

Default execution is device-free. The explicit owner-authorized mode uses the
pinned SDK ADB executable and `shell -T sh -s` with fixed bytes on stdin. Raw
logcat stdout/stderr are consumed on-device and never saved or returned.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
from typing import Any, Callable
from uuid import uuid4

if __package__:
    from . import p3a_m27b_camx_provider as m27b
    from .p3a_collect_producers import canonical_commit
    from .p3a_quickcamera_inventory import ROOT
else:
    import p3a_m27b_camx_provider as m27b
    from p3a_collect_producers import canonical_commit
    from p3a_quickcamera_inventory import ROOT


ACTION = "read-only-callback-log-snapshot"
SCHEMA = "p3a.m28d.callback_logs.v1"
COLLECTOR_REVISION = "P3-A6-M2.8D-v1"
TARGET_DEVICE = "Pico 4 Pro"
TARGET_SERIAL_ENV = m27b.TARGET_SERIAL_ENV
TARGET_FINGERPRINT = m27b.TARGET_FINGERPRINT
TARGET_ABI = m27b.TARGET_ABI
MAX_DURATION_SECONDS = 15
MAX_COMMAND_SECONDS = 5
MAX_ADB_COMMANDS = 6
MAX_OUTPUT_BYTES = 64 * 1024
MAX_RECORDS = 40
MAX_PROCESSES = 16
FILTER_VERSION = "pid-marker-numeric-v1"
SOURCE_LABEL = "CSLTimestampTypeQtimer"
SAFETY = {
    "observe_only": True,
    "exact_time": False,
    "mapping_verified": False,
    "pose_verified": False,
    "shared_buffer_identity_verified": False,
    "frame_meta_bridge_verified": False,
    "physical_event_verified": False,
    "live_lighthouse_correction_allowed": False,
}
_SCRIPT_DIR = Path(__file__).resolve().parent


def _fixed_script(filename: str) -> bytes:
    raw = (_SCRIPT_DIR / filename).read_bytes()
    normalized = raw.replace(b"\r\n", b"\n")
    if b"\r" in normalized:
        raise RuntimeError("FIXED_PROBE_HAS_STANDALONE_CR")
    normalized.decode("ascii", errors="strict")
    return normalized


SHELL_V2_SCRIPT_BYTES = _fixed_script("p3a_m28d_shell_v2.sh")
CAPABILITY_SCRIPT_BYTES = _fixed_script("p3a_m28d_logcat_capability.sh")
PROBE_SCRIPT_BYTES = _fixed_script("p3a_m28d_callback_probe.sh")
SHELL_V2_SHA256 = hashlib.sha256(SHELL_V2_SCRIPT_BYTES).hexdigest()
CAPABILITY_SHA256 = hashlib.sha256(CAPABILITY_SCRIPT_BYTES).hexdigest()
PROBE_SHA256 = hashlib.sha256(PROBE_SCRIPT_BYTES).hexdigest()
_PROCESS_NAME = re.compile(r"[A-Za-z0-9_.:@-]{1,256}\Z", re.ASCII)
_PROCESS_MATCH = re.compile(r"(?:quickcamera|pvr|camera.*hidl|hidl.*camera)", re.IGNORECASE | re.ASCII)
_PID = re.compile(r"[0-9]{1,10}\Z", re.ASCII)
_DATE = re.compile(r"[0-9]{2}-[0-9]{2}\Z", re.ASCII)
_TIME = re.compile(r"[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{3}\Z", re.ASCII)
_SIGNED_I64 = re.compile(r"-?(?:0|[1-9][0-9]*)\Z", re.ASCII)
_ERROR_CODES = frozenset({
    "OUTPUT_LINE_LIMIT", "OUTPUT_TRUNCATED", "REMOTE_FILTER_UNVERIFIED",
    "REMOTE_COMMAND_FAILURE", "MALFORMED_PROTOCOL_RECORD",
})


class ProcessOutputLimitError(RuntimeError):
    pass


class RunnerStop(RuntimeError):
    def __init__(self, status: str, code: str):
        super().__init__(code)
        self.status = status
        self.code = code


def _valid_target(target: str) -> bool:
    return (isinstance(target, str)
            and hashlib.sha256(target.encode("utf-8")).hexdigest() == m27b.TARGET_SERIAL_SHA256)


def owner_authorized_target_serial() -> str:
    target = m27b.owner_authorized_target_serial()
    if not _valid_target(target):
        raise ValueError("TARGET_BINDING_MISMATCH")
    return target


def adb_shell_argv(target: str | None = None) -> list[str]:
    target = owner_authorized_target_serial() if target is None else target
    if not _valid_target(target):
        raise ValueError("TARGET_BINDING_MISMATCH")
    return ["-s", target, "shell", "-T", "sh", "-s"]


def allowed_adb_arguments(arguments: list[str] | tuple[str, ...],
                           selector: list[str] | tuple[str, ...], *,
                           stdin_bytes: bytes | None = None) -> bool:
    try:
        target = owner_authorized_target_serial()
    except (ValueError, OSError):
        return False
    if list(selector) != ["-s", target]:
        return False
    argv = list(arguments)
    if argv == ["-s", target, "get-state"] and stdin_bytes is None:
        return True
    if (argv in (
            ["-s", target, "shell", "getprop", "ro.build.fingerprint"],
            ["-s", target, "shell", "getprop", "ro.product.cpu.abi"],
        ) and stdin_bytes is None):
        return True
    if argv == ["-s", target, "shell", "-T", "sh", "-s"]:
        return stdin_bytes in (SHELL_V2_SCRIPT_BYTES, CAPABILITY_SCRIPT_BYTES, PROBE_SCRIPT_BYTES)
    return False


def _i64(value: str) -> bool:
    if not _SIGNED_I64.fullmatch(value):
        return False
    try:
        number = int(value, 10)
    except ValueError:
        return False
    return -(1 << 63) <= number <= (1 << 63) - 1


def _safe_failure(code: str, byte_count: int, record_count: int,
                  *, line_number: int | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "ok": False, "status": _status_for_error(code), "error_code": code, "byte_count": byte_count,
        "record_count": record_count,
    }
    if line_number is not None:
        result["line_number"] = line_number
    return result


def _decode_protocol(stdout: bytes) -> tuple[list[str] | None, dict[str, Any] | None]:
    if not isinstance(stdout, bytes):
        return None, _safe_failure("MALFORMED_PROTOCOL_RECORD", 0, 0)
    byte_count = len(stdout)
    record_count = stdout.count(b"\n")
    if byte_count > MAX_OUTPUT_BYTES:
        return None, _safe_failure("OUTPUT_TRUNCATED", byte_count, record_count)
    if record_count > MAX_RECORDS:
        return None, _safe_failure("OUTPUT_LINE_LIMIT", byte_count, record_count)
    if not stdout:
        return None, _safe_failure("MISSING_PROTOCOL_TERMINATOR", 0, 0)
    if not stdout.endswith(b"\n"):
        return None, _safe_failure("MISSING_PROTOCOL_TERMINATOR", byte_count, record_count,
                                   line_number=record_count + 1)
    lines: list[str] = []
    for line_number, raw in enumerate(stdout.split(b"\n")[:-1], start=1):
        line = raw[:-1] if raw.endswith(b"\r") else raw
        if b"\r" in line:
            return None, _safe_failure("INVALID_LINE_ENDING", byte_count, record_count,
                                       line_number=line_number)
        if any((byte < 0x20 and byte != 0x09) or byte > 0x7e for byte in line):
            return None, _safe_failure("INVALID_CONTROL_CHARACTER", byte_count, record_count,
                                       line_number=line_number)
        try:
            lines.append(line.decode("ascii"))
        except UnicodeDecodeError:
            return None, _safe_failure("MALFORMED_PROTOCOL_RECORD", byte_count, record_count,
                                       line_number=line_number)
    return lines, None


def _status_for_error(code: str) -> str:
    if code in ("OUTPUT_LINE_LIMIT", "OUTPUT_TRUNCATED", "MALFORMED_PROTOCOL_RECORD",
                "INVALID_LINE_ENDING", "INVALID_CONTROL_CHARACTER", "MISSING_PROTOCOL_TERMINATOR"):
        return "OUTPUT_FRAMING_BLOCKED"
    return "REMOTE_FILTER_BLOCKED"


def parse_probe_result(stdout: bytes, *, returncode: int = 0,
                       stderr_byte_count: int = 0) -> dict[str, Any]:
    """Parse only allowlisted protocol fields; never echo malformed bytes."""
    lines, failure = _decode_protocol(stdout)
    byte_count = len(stdout) if isinstance(stdout, bytes) else 0
    record_count = stdout.count(b"\n") if isinstance(stdout, bytes) else 0
    if failure is not None:
        return failure
    assert lines is not None
    if stderr_byte_count:
        return _safe_failure("REMOTE_FILTER_BLOCKED", byte_count + stderr_byte_count, record_count)
    if len(lines) < 3 or lines[0] != "P3A28D\tBEGIN\t1" or lines[1] != f"P3A28D\tFILTER\t{FILTER_VERSION}":
        return _safe_failure("MALFORMED_PROTOCOL_RECORD", byte_count, record_count, line_number=1)
    if lines[-1] == "P3A28D\tEND\tNO_TARGET_PROCESSES":
        if len(lines) != 3 or returncode != 0:
            return _safe_failure("MALFORMED_PROTOCOL_RECORD", byte_count, record_count,
                                 line_number=len(lines))
        return {"ok": True, "status": "NO_MATCHING_LOG_RECORDS_OBSERVED",
                "reason": "NO_TARGET_PROCESSES", "logcat_read": False,
                "records": [], "byte_count": byte_count, "record_count": record_count}

    records: list[dict[str, str]] = []
    processes: dict[str, str] = {}
    events_started = False
    end_fields: list[str] | None = None
    for line_number, line in enumerate(lines[2:], start=3):
        fields = line.split("\t")
        if fields[:2] != ["P3A28D", "PROCESS"] and fields[:2] != ["P3A28D", "EVENT"] and fields[:2] != ["P3A28D", "END"]:
            return _safe_failure("MALFORMED_PROTOCOL_RECORD", byte_count, record_count,
                                 line_number=line_number)
        kind = fields[1] if len(fields) > 1 else ""
        if kind == "PROCESS":
            if events_started or len(fields) != 4:
                return _safe_failure("MALFORMED_PROTOCOL_RECORD", byte_count, record_count,
                                     line_number=line_number)
            _, _, pid, name = fields
            if (not _PID.fullmatch(pid) or not _PROCESS_NAME.fullmatch(name)
                    or not _PROCESS_MATCH.search(name) or pid in processes
                    or len(processes) >= MAX_PROCESSES):
                return _safe_failure("MALFORMED_PROTOCOL_RECORD", byte_count, record_count,
                                     line_number=line_number)
            processes[pid] = name
            records.append({"kind": "PROCESS", "pid": pid, "name": name})
            continue
        if kind == "EVENT":
            events_started = True
            if len(fields) != 10:
                return _safe_failure("MALFORMED_PROTOCOL_RECORD", byte_count, record_count,
                                     line_number=line_number)
            _, _, pid, date, clock, request_id, frame_count, timestamp, mono_timestamp, source = fields
            if (not _PID.fullmatch(pid) or pid not in processes or not _DATE.fullmatch(date)
                    or not _TIME.fullmatch(clock) or not _i64(request_id) or not _i64(frame_count)
                    or not _i64(timestamp) or not _i64(mono_timestamp) or source != SOURCE_LABEL):
                return _safe_failure("MALFORMED_PROTOCOL_RECORD", byte_count, record_count,
                                     line_number=line_number)
            records.append({
                "kind": "EVENT", "pid": pid, "logcat_date": date, "logcat_time": clock,
                "request_id": request_id, "frame_count_label": frame_count,
                "timestamp": timestamp, "mono_timestamp_label": mono_timestamp,
                "source_label": source,
            })
            continue
        if line_number != len(lines):
            return _safe_failure("MALFORMED_PROTOCOL_RECORD", byte_count, record_count,
                                 line_number=line_number)
        end_fields = fields

    if end_fields is None:
        return _safe_failure("MISSING_PROTOCOL_TERMINATOR", byte_count, record_count,
                             line_number=len(lines))
    if len(end_fields) == 4 and end_fields[:3] == ["P3A28D", "END", "ERROR"]:
        code = end_fields[3]
        if code not in _ERROR_CODES or returncode == 0:
            return _safe_failure("MALFORMED_PROTOCOL_RECORD", byte_count, record_count,
                                 line_number=len(lines))
        return {"ok": False, "status": _status_for_error(code), "error_code": code,
                "byte_count": byte_count, "record_count": record_count}
    if end_fields != ["P3A28D", "END", "OK"] or returncode != 0 or not processes:
        return _safe_failure("REMOTE_COMMAND_FAILURE", byte_count, record_count,
                             line_number=len(lines))
    status = "CALLBACK_LOG_OBSERVED" if any(row["kind"] == "EVENT" for row in records) else "NO_MATCHING_LOG_RECORDS_OBSERVED"
    return {"ok": True, "status": status, "reason": None if status == "CALLBACK_LOG_OBSERVED" else "NO_MATCHING_CALLBACK_ROWS",
            "logcat_read": True, "records": records,
            "byte_count": byte_count, "record_count": record_count}


def parse_logcat_capability(stdout: bytes, returncode: int) -> str:
    lines, failure = _decode_protocol(stdout)
    if failure is not None or returncode != 0 or lines is None:
        return "OUTPUT_FRAMING_BLOCKED" if failure is not None else "LOGCAT_CAPABILITY_BLOCKED"
    if lines == ["P3A28D\tCAPABILITY\tLOGCAT\tOPTIONS_OK"]:
        return "READY"
    if lines == ["P3A28D\tCAPABILITY\tLOGCAT\tOPTIONS_UNSUPPORTED"]:
        return "LOGCAT_CAPABILITY_BLOCKED"
    return "OUTPUT_FRAMING_BLOCKED"


def validate_shell_v2_result(stdout: bytes, returncode: int, stderr_byte_count: int) -> bool:
    if not isinstance(stdout, bytes):
        return False
    normalized = stdout.replace(b"\r\n", b"\n")
    return (b"\r" not in normalized and normalized == b"P3A28D\tSHELL_V2\tOK\n"
            and returncode == 23 and stderr_byte_count == 0)


def _single_line(stdout: bytes) -> str:
    if not isinstance(stdout, bytes) or len(stdout) > 512:
        raise ValueError("IDENTITY_OUTPUT_INVALID")
    normalized = stdout.replace(b"\r\n", b"\n")
    if b"\r" in normalized or not normalized.endswith(b"\n"):
        raise ValueError("IDENTITY_OUTPUT_INVALID")
    lines = normalized[:-1].split(b"\n")
    if len(lines) != 1 or any(byte < 0x20 or byte > 0x7e for byte in lines[0]):
        raise ValueError("IDENTITY_OUTPUT_INVALID")
    return lines[0].decode("ascii")


def run_bounded_process(arguments: list[str], *, stdin_bytes: bytes | None,
                        timeout: float, max_output_bytes: int) -> tuple[int, bytes, int]:
    """Run a native process with separate bounded channels and closed stdin."""
    process = subprocess.Popen(
        arguments, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        shell=False, bufsize=0,
    )
    stdout_parts: list[bytes] = []
    counts = {"stdout": 0, "stderr": 0}
    lock = threading.Lock()
    overflow = threading.Event()
    read_errors: list[Exception] = []

    def kill() -> None:
        try:
            process.kill()
        except OSError:
            pass

    def drain(stream, key: str, keep: bool) -> None:
        try:
            while True:
                chunk = stream.read(8192)
                if not chunk:
                    return
                with lock:
                    counts[key] += len(chunk)
                    total = counts["stdout"] + counts["stderr"]
                    if total > max_output_bytes:
                        overflow.set()
                        kill()
                        return
                    if keep:
                        stdout_parts.append(chunk)
        except Exception as exc:
            read_errors.append(exc)
            kill()

    readers = [
        threading.Thread(target=drain, args=(process.stdout, "stdout", True), daemon=True),
        threading.Thread(target=drain, args=(process.stderr, "stderr", False), daemon=True),
    ]
    for reader in readers:
        reader.start()

    def feed_stdin() -> None:
        try:
            if stdin_bytes is not None:
                process.stdin.write(stdin_bytes)
                process.stdin.flush()
        except (BrokenPipeError, OSError):
            pass
        finally:
            try:
                process.stdin.close()
            except OSError:
                pass

    writer = threading.Thread(target=feed_stdin, daemon=True)
    writer.start()
    try:
        returncode = process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        kill()
        process.wait()
        writer.join(timeout=1)
        for reader in readers:
            reader.join(timeout=1)
        for stream in (process.stdin, process.stdout, process.stderr):
            try:
                stream.close()
            except OSError:
                pass
        raise subprocess.TimeoutExpired(arguments, timeout)
    writer.join(timeout=1)
    for reader in readers:
        reader.join(timeout=1)
    for stream in (process.stdin, process.stdout, process.stderr):
        try:
            stream.close()
        except OSError:
            pass
    if any(reader.is_alive() for reader in readers) or writer.is_alive():
        kill()
        raise OSError("BOUNDED_PROCESS_DRAIN_FAILED")
    if overflow.is_set():
        raise ProcessOutputLimitError("NATIVE_OUTPUT_LIMIT")
    if read_errors:
        raise OSError("NATIVE_PIPE_READ_FAILED") from read_errors[0]
    return returncode, b"".join(stdout_parts), counts["stderr"]


def native_adb_executor(executable: Path, target: str) -> Callable[..., tuple[int, bytes, int]]:
    selector = ["-s", target]

    def execute(arguments: list[str], *, stdin_bytes: bytes | None,
                timeout: float) -> tuple[int, bytes, int]:
        if timeout <= 0 or timeout > MAX_DURATION_SECONDS:
            raise RunnerStop("ADB_TRANSPORT_BLOCKED", "INVALID_COMMAND_TIMEOUT")
        if not allowed_adb_arguments(arguments, selector, stdin_bytes=stdin_bytes):
            raise RunnerStop("REMOTE_FILTER_BLOCKED", "COMMAND_NOT_ALLOWLISTED")
        try:
            return run_bounded_process(
                [str(executable), *arguments], stdin_bytes=stdin_bytes,
                timeout=min(timeout, MAX_COMMAND_SECONDS), max_output_bytes=MAX_OUTPUT_BYTES,
            )
        except subprocess.TimeoutExpired as exc:
            raise RunnerStop("ADB_TRANSPORT_BLOCKED", "ADB_TIMEOUT") from exc
        except ProcessOutputLimitError as exc:
            raise RunnerStop("OUTPUT_FRAMING_BLOCKED", "ADB_OUTPUT_LIMIT") from exc
        except OSError as exc:
            raise RunnerStop("ADB_TRANSPORT_BLOCKED", "ADB_EXECUTION_ERROR") from exc
    return execute


def resolve_adb_executable() -> Path:
    return m27b.resolve_adb_executable()


def _base_report(target: str | None) -> dict[str, Any]:
    return {
        "schema": SCHEMA, "collector_revision": COLLECTOR_REVISION,
        "action": ACTION, "device": TARGET_DEVICE,
        "authorization_mode": "OWNER_AUTHORIZED_DIRECT_INSTRUCTION",
        "approval_record_created": False,
        "target_binding_sha256": hashlib.sha256(target.encode("utf-8")).hexdigest() if target else None,
        "status": "ADB_TRANSPORT_BLOCKED", "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "started_at_utc": None, "finished_at_utc": None, "duration_seconds": None,
        "limits": {"max_duration_seconds": MAX_DURATION_SECONDS,
                   "max_records": MAX_RECORDS, "max_processes": MAX_PROCESSES,
                   "max_adb_commands": MAX_ADB_COMMANDS,
                   "max_output_bytes": MAX_OUTPUT_BYTES},
        "methods": {"adb_transport": "shell -T sh -s; fixed checked-in scripts on stdin; stdin closed",
                    "raw_logcat_stdout_saved": False, "raw_logcat_stderr_saved": False,
                    "raw_adb_output_saved": False, "camera_started": False,
                    "process_memory_read": False},
        "build_identity": {"fingerprint": {"status": "NOT_OBSERVED", "value": None},
                           "abi": {"status": "NOT_OBSERVED", "value": None}},
        "shell_protocol_v2": "NOT_OBSERVED",
        "shell_v2_probe": {"status": "NOT_OBSERVED", "returncode": None,
                            "stdout_byte_count": 0, "stderr_byte_count": 0},
        "logcat_capability": "NOT_OBSERVED",
        "logcat_snapshot_attempted": False, "logcat_read": False,
        "observation_window_utc": None, "records": [], "normalized_record_count": 0,
        "adb_command_count": 0, "adb_output_bytes": 0,
        "probe_sha256": PROBE_SHA256, "capability_script_sha256": CAPABILITY_SHA256,
        "shell_v2_script_sha256": SHELL_V2_SHA256,
        "diagnostics": [], "safety": dict(SAFETY),
    }


def collect(target: str, *, executor: Callable[..., tuple[int, bytes, int]],
            owner_authorized: bool, monotonic_fn: Callable[[], float] = time.monotonic) -> dict[str, Any]:
    report = _base_report(target if _valid_target(target) else None)
    if owner_authorized is not True:
        report["diagnostics"].append({"code": "OWNER_AUTHORIZATION_REQUIRED"})
        return report
    if not _valid_target(target):
        report["diagnostics"].append({"code": "TARGET_BINDING_MISMATCH"})
        return report
    selector = ["-s", target]
    started = monotonic_fn()
    report["started_at_utc"] = datetime.now(timezone.utc).isoformat()

    def call(args: list[str], script: bytes | None = None,
             expected_rc: tuple[int, ...] = (0,)) -> tuple[bytes, int, int]:
        if report["adb_command_count"] >= MAX_ADB_COMMANDS:
            raise RunnerStop("ADB_TRANSPORT_BLOCKED", "ADB_COMMAND_LIMIT")
        if not allowed_adb_arguments(args, selector, stdin_bytes=script):
            raise RunnerStop("REMOTE_FILTER_BLOCKED", "COMMAND_NOT_ALLOWLISTED")
        remaining = MAX_DURATION_SECONDS - (monotonic_fn() - started)
        if remaining <= 0:
            raise RunnerStop("ADB_TRANSPORT_BLOCKED", "DURATION_LIMIT")
        report["adb_command_count"] += 1
        try:
            rc, stdout, stderr_count = executor(
                args, stdin_bytes=script, timeout=min(remaining, MAX_COMMAND_SECONDS),
            )
        except RunnerStop:
            raise
        except subprocess.TimeoutExpired as exc:
            raise RunnerStop("ADB_TRANSPORT_BLOCKED", "ADB_TIMEOUT") from exc
        except Exception as exc:
            raise RunnerStop("ADB_TRANSPORT_BLOCKED", "ADB_EXECUTION_ERROR") from exc
        if not isinstance(stdout, bytes) or not isinstance(stderr_count, int) or stderr_count < 0:
            raise RunnerStop("ADB_TRANSPORT_BLOCKED", "ADB_EXECUTOR_CONTRACT_FAILURE")
        report["adb_output_bytes"] += len(stdout) + stderr_count
        if report["adb_output_bytes"] > MAX_OUTPUT_BYTES:
            raise RunnerStop("OUTPUT_FRAMING_BLOCKED", "ADB_OUTPUT_LIMIT")
        if rc not in expected_rc or stderr_count:
            raise RunnerStop("ADB_TRANSPORT_BLOCKED", "ADB_NONZERO_OR_STDERR")
        return stdout, rc, stderr_count

    try:
        state_raw, _, _ = call([*selector, "get-state"])
        if _single_line(state_raw) != "device":
            raise RunnerStop("ADB_TRANSPORT_BLOCKED", "TARGET_NOT_READY")
        fingerprint_raw, _, _ = call([*selector, "shell", "getprop", "ro.build.fingerprint"])
        fingerprint = _single_line(fingerprint_raw)
        if fingerprint != TARGET_FINGERPRINT:
            report["build_identity"]["fingerprint"] = {"status": "MISMATCH", "value": None}
            raise RunnerStop("ADB_TRANSPORT_BLOCKED", "FINGERPRINT_MISMATCH")
        report["build_identity"]["fingerprint"] = {"status": "OBSERVED", "value": fingerprint}
        abi_raw, _, _ = call([*selector, "shell", "getprop", "ro.product.cpu.abi"])
        abi = _single_line(abi_raw)
        if abi != TARGET_ABI:
            report["build_identity"]["abi"] = {"status": "MISMATCH", "value": None}
            raise RunnerStop("ADB_TRANSPORT_BLOCKED", "ABI_MISMATCH")
        report["build_identity"]["abi"] = {"status": "OBSERVED", "value": abi}

        shell_out, shell_rc, shell_stderr = call(
            [*selector, "shell", "-T", "sh", "-s"], SHELL_V2_SCRIPT_BYTES, (23,),
        )
        report["shell_v2_probe"] = {
            "status": "MARKER_MATCHED" if validate_shell_v2_result(shell_out, shell_rc, shell_stderr)
                     else "MARKER_MISMATCH",
            "returncode": shell_rc, "stdout_byte_count": len(shell_out),
            "stderr_byte_count": shell_stderr,
        }
        if not validate_shell_v2_result(shell_out, shell_rc, shell_stderr):
            report["shell_protocol_v2"] = "EXIT_STATUS_23_OBSERVED_MARKER_UNVERIFIED"
            raise RunnerStop("OUTPUT_FRAMING_BLOCKED", "SHELL_V2_MARKER_MISMATCH")
        report["shell_protocol_v2"] = "VERIFIED_EXIT_STATUS_23"

        cap_args = [*selector, "shell", "-T", "sh", "-s"]
        cap_out, cap_rc, _ = call(cap_args, CAPABILITY_SCRIPT_BYTES)
        capability = parse_logcat_capability(cap_out, cap_rc)
        report["logcat_capability"] = capability
        if capability != "READY":
            raise RunnerStop(capability, "LOGCAT_OPTIONS_UNVERIFIED")

        probe_start = datetime.now(timezone.utc).isoformat()
        report["logcat_snapshot_attempted"] = True
        probe_out, probe_rc, _ = call(cap_args, PROBE_SCRIPT_BYTES, (0, 1))
        probe_finish = datetime.now(timezone.utc).isoformat()
        parsed = parse_probe_result(probe_out, returncode=probe_rc)
        report["observation_window_utc"] = {"started_at": probe_start, "finished_at": probe_finish,
                                            "meaning": "host bounds for a fixed existing-log snapshot"}
        report["logcat_read"] = parsed.get("logcat_read", False)
        if not parsed.get("ok"):
            raise RunnerStop(parsed.get("status", "OUTPUT_FRAMING_BLOCKED"),
                             parsed.get("error_code", "OUTPUT_FRAMING_BLOCKED"))
        report["records"] = parsed["records"]
        report["normalized_record_count"] = parsed["record_count"]
        report["status"] = parsed["status"]
        if parsed.get("reason"):
            report["diagnostics"].append({"code": parsed["reason"]})
    except RunnerStop as exc:
        report["status"] = exc.status
        report["diagnostics"].append({"code": exc.code})
    except ValueError:
        report["status"] = "OUTPUT_FRAMING_BLOCKED"
        report["diagnostics"].append({"code": "IDENTITY_OUTPUT_INVALID"})
    finally:
        report["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
        report["duration_seconds"] = round(max(0.0, monotonic_fn() - started), 6)
    if report["duration_seconds"] > MAX_DURATION_SECONDS:
        report["status"] = "ADB_TRANSPORT_BLOCKED"
        report["diagnostics"].append({"code": "DURATION_LIMIT"})
        report["records"] = []
        report["normalized_record_count"] = 0
    return report


def build_evidence_package(report: dict[str, Any]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        archive.writestr("manifest.json", json.dumps(report, indent=2, ensure_ascii=True) + "\n")
    return output.getvalue()


def dry_run_plan() -> dict[str, Any]:
    return {
        "action": ACTION, "device": TARGET_DEVICE,
        "target_binding": "digest-pinned owner endpoint; no device enumeration",
        "max_duration_seconds": MAX_DURATION_SECONDS, "max_records": MAX_RECORDS,
        "max_processes": MAX_PROCESSES, "max_adb_commands": MAX_ADB_COMMANDS,
        "transport": "adb -s <fixed-target> shell -T sh -s; fixed script stdin; stdin closed",
        "allowed_commands": ["get-state", "getprop ro.build.fingerprint",
                             "getprop ro.product.cpu.abi", "fixed shell scripts"],
        "probe_sha256": PROBE_SHA256, "capability_sha256": CAPABILITY_SHA256,
        "shell_v2_sha256": SHELL_V2_SHA256,
        "device_facing_calls_performed": False, "approval_record_created": False,
        "status": "DRY_RUN_ONLY", "safety": dict(SAFETY),
    }


def _preflight_report(code: str) -> dict[str, Any]:
    report = _base_report(None)
    report["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
    report["diagnostics"].append({"code": code})
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--dry-run", action="store_true")
    modes.add_argument("--owner-authorized-run", action="store_true",
                       help="run only under the direct owner authorization in this task")
    args = parser.parse_args(argv)
    if args.dry_run:
        print(json.dumps(dry_run_plan(), separators=(",", ":")))
        return 0
    if not args.owner_authorized_run:
        print("BLOCKED: explicit --owner-authorized-run mode is required", file=sys.stderr)
        return 2

    try:
        target = owner_authorized_target_serial()
        executable = resolve_adb_executable()
    except (ValueError, OSError):
        report = _preflight_report("TARGET_BINDING_OR_PINNED_ADB_UNAVAILABLE")
    else:
        with tempfile.TemporaryDirectory(prefix="p3a-m28d-private-"):
            report = collect(target, executor=native_adb_executor(executable, target),
                             owner_authorized=True)
    run_name = datetime.now(timezone.utc).strftime("p3a-m28d-callback-logs-%Y%m%dT%H%M%SZ-") + uuid4().hex[:8]
    try:
        package = build_evidence_package(report)
        receipt = canonical_commit(Path(ROOT), run_name, report, package)
    except Exception:
        print("PUBLICATION_BLOCKED: canonical SMB commit/readback failed", file=sys.stderr)
        return 3
    print(json.dumps(receipt, separators=(",", ":")))
    return 0 if report["status"] in ("CALLBACK_LOG_OBSERVED", "NO_MATCHING_LOG_RECORDS_OBSERVED") else 1


if __name__ == "__main__":
    raise SystemExit(main())
