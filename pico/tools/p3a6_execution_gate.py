"""Fail-closed authorization check for a future, separately approved P3-A6 run.

This module validates an approval record. It contains no ADB, shell, network,
or device-execution code and does not start an experiment.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping


APPROVAL_SCHEMA = 'p3a6.hardware_approval.v1'
TARGET_DEVICE = 'Pico 4 Pro'


@dataclass(frozen=True)
class GateDecision:
    allowed: bool
    status: str
    reason: str
    approval_id: str | None = None


def _parse_utc(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        return None
    return parsed.astimezone(timezone.utc)


def check_hardware_execution_gate(
    approval: Mapping[str, Any] | None,
    action: str,
    owner_confirmation: str | None,
    now_utc: datetime | None = None,
) -> GateDecision:
    """Check a run-specific user approval; never performs the approved action.

    A future device runner must call this gate immediately before its first
    device-facing operation and must still require a direct user instruction.
    The textual confirmation is an accident-prevention token, not a security
    boundary or proof of who supplied it.
    """
    if approval is None:
        return GateDecision(False, 'BLOCKED_NO_APPROVAL', 'No approval record supplied')
    if not isinstance(approval, Mapping):
        return GateDecision(False, 'BLOCKED_INVALID_APPROVAL', 'Approval record must be an object')
    if approval.get('schema') != APPROVAL_SCHEMA:
        return GateDecision(False, 'BLOCKED_INVALID_APPROVAL', 'Approval schema is missing or unsupported')

    approval_id = approval.get('approval_id')
    if not isinstance(approval_id, str) or not approval_id.strip():
        return GateDecision(False, 'BLOCKED_INVALID_APPROVAL', 'Approval ID is required')
    if approval.get('device') != TARGET_DEVICE:
        return GateDecision(False, 'BLOCKED_SCOPE_MISMATCH', 'Approval must name Pico 4 Pro')
    actions = approval.get('approved_actions')
    if (not isinstance(actions, list) or len(actions) != 1
            or any(not isinstance(item, str) or not item for item in actions)):
        return GateDecision(False, 'BLOCKED_INVALID_APPROVAL', 'Exactly one approved action is required per record', approval_id)
    if not isinstance(action, str) or action != actions[0]:
        return GateDecision(False, 'BLOCKED_SCOPE_MISMATCH', 'Requested action is outside the approval scope', approval_id)
    duration = approval.get('max_duration_seconds')
    observations = approval.get('max_observations')
    if (type(duration) is not int or not 1 <= duration <= 600
            or type(observations) is not int or not 1 <= observations <= 10_000):
        return GateDecision(
            False,
            'BLOCKED_UNBOUNDED_APPROVAL',
            'Approval must bound duration to 1..600 seconds and observations to 1..10000',
            approval_id,
        )

    issued = _parse_utc(approval.get('issued_at_utc'))
    expires = _parse_utc(approval.get('expires_at_utc'))
    now = now_utc if now_utc is not None else datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() != timezone.utc.utcoffset(now):
        return GateDecision(False, 'BLOCKED_INVALID_CLOCK', 'Gate clock must be timezone-aware UTC', approval_id)
    now = now.astimezone(timezone.utc)
    if issued is None or expires is None or expires <= issued:
        return GateDecision(False, 'BLOCKED_INVALID_APPROVAL', 'Approval requires valid UTC issue and expiry times', approval_id)
    if expires - issued > timedelta(hours=24):
        return GateDecision(False, 'BLOCKED_INVALID_APPROVAL', 'Approval validity cannot exceed 24 hours', approval_id)
    if now < issued:
        return GateDecision(False, 'BLOCKED_NOT_YET_VALID', 'Approval issue time is in the future', approval_id)
    if now >= expires:
        return GateDecision(False, 'BLOCKED_EXPIRED', 'Approval has expired', approval_id)

    expected_confirmation = f'P3-A6 APPROVE {approval_id} {action}'
    if owner_confirmation != expected_confirmation:
        return GateDecision(False, 'BLOCKED_CONFIRMATION_REQUIRED', 'Direct, exact run confirmation is required', approval_id)
    return GateDecision(True, 'APPROVED_FOR_SCOPED_ACTION', 'Approval is scoped and currently valid', approval_id)
