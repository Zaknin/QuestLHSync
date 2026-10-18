"""Small stdin-only bridge from PowerShell 7 to the shared P3-A6 gate."""
from __future__ import annotations

import json
import sys
from typing import Any

from .p3a6_execution_gate import check_hardware_execution_gate


MAX_REQUEST_BYTES = 64 * 1024


def main() -> int:
    raw = sys.stdin.buffer.read(MAX_REQUEST_BYTES + 1)
    if len(raw) > MAX_REQUEST_BYTES:
        sys.stdout.write(json.dumps({"allowed": False, "status": "BLOCKED_INVALID_APPROVAL", "reason": "Gate request exceeds limit"}))
        return 4
    try:
        payload: Any = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError):
        sys.stdout.write(json.dumps({"allowed": False, "status": "BLOCKED_INVALID_APPROVAL", "reason": "Gate request is invalid"}))
        return 4
    if not isinstance(payload, dict) or set(payload) != {"approval", "action", "owner_confirmation"}:
        sys.stdout.write(json.dumps({"allowed": False, "status": "BLOCKED_INVALID_APPROVAL", "reason": "Gate request fields are invalid"}))
        return 4

    decision = check_hardware_execution_gate(
        payload["approval"],
        payload["action"],
        payload["owner_confirmation"],
    )
    sys.stdout.write(json.dumps({
        "allowed": decision.allowed,
        "status": decision.status,
        "reason": decision.reason,
        "approval_id": decision.approval_id,
    }, separators=(",", ":")))
    return 0 if decision.allowed else 3


if __name__ == "__main__":
    raise SystemExit(main())
