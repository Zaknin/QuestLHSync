"""Analyze synthetic P3-A6 queue and timestamp observations offline only.

The input schema rejects experimental records. This analyzer has no device,
ADB, process-memory, network, or camera-control capability.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Mapping


SCHEMA = 'p3a6.synthetic_observations.v1'
MAX_OBSERVATIONS = 10_000
MAX_INPUT_BYTES = 16 * 1024 * 1024
_TOP_LEVEL_FIELDS = {'schema', 'dataset_kind', 'expected_qtimer_ns_per_unit', 'observations'}
_ROW_FIELDS = {
    'frame_sequence',
    'qbuf_id_u32',
    'qbuf_userptr_u64',
    'dqbuf_userptr_u64',
    'request_id',
    'timestamp_source_request_id',
    'fallback_marker',
    'qtimer_value',
    'android_mono_before_ns',
    'android_mono_after_ns',
    'observer_delivery_mono_ns',
}
_U32_MAX = (1 << 32) - 1
_U64_MAX = (1 << 64) - 1


class ObservationInputError(ValueError):
    """Raised when input is outside the explicitly synthetic schema."""


def _unsigned(value: Any, maximum: int, field: str, row_index: int | None = None) -> int | None:
    if value is None:
        return None
    location = f'observations[{row_index}].{field}' if row_index is not None else field
    if type(value) is not int or not 0 <= value <= maximum:
        raise ObservationInputError(f'{location} must be an unsigned integer <= {maximum}')
    return value


def _validate(payload: Mapping[str, Any]) -> tuple[list[dict[str, Any]], float | None]:
    if not isinstance(payload, Mapping):
        raise ObservationInputError('input must be a JSON object')
    if payload.get('schema') != SCHEMA:
        raise ObservationInputError(f'unsupported schema; expected {SCHEMA}')
    if payload.get('dataset_kind') != 'synthetic':
        raise ObservationInputError('only dataset_kind="synthetic" is accepted; experimental data is not scored')
    extra_fields = set(payload) - _TOP_LEVEL_FIELDS
    if extra_fields:
        raise ObservationInputError(f'unknown top-level fields: {sorted(extra_fields)}')

    scale_value = payload.get('expected_qtimer_ns_per_unit')
    if scale_value is None:
        expected_scale = None
    elif (isinstance(scale_value, bool) or not isinstance(scale_value, (int, float))
          or not math.isfinite(scale_value) or scale_value <= 0):
        raise ObservationInputError('expected_qtimer_ns_per_unit must be a finite positive number')
    else:
        expected_scale = float(scale_value)

    observations = payload.get('observations')
    if not isinstance(observations, list):
        raise ObservationInputError('observations must be an array')
    if len(observations) > MAX_OBSERVATIONS:
        raise ObservationInputError(f'observations cannot exceed {MAX_OBSERVATIONS} rows')
    rows: list[dict[str, Any]] = []
    for index, item in enumerate(observations):
        if not isinstance(item, Mapping):
            raise ObservationInputError(f'observations[{index}] must be an object')
        extra_row_fields = set(item) - _ROW_FIELDS
        if extra_row_fields:
            raise ObservationInputError(f'observations[{index}] has unknown fields: {sorted(extra_row_fields)}')
        row = dict(item)
        for field in ('frame_sequence', 'request_id', 'timestamp_source_request_id', 'qtimer_value'):
            row[field] = _unsigned(row.get(field), _U64_MAX, field, index)
        row['qbuf_id_u32'] = _unsigned(row.get('qbuf_id_u32'), _U32_MAX, 'qbuf_id_u32', index)
        for field in ('qbuf_userptr_u64', 'dqbuf_userptr_u64'):
            row[field] = _unsigned(row.get(field), _U64_MAX, field, index)
        for field in ('android_mono_before_ns', 'android_mono_after_ns', 'observer_delivery_mono_ns'):
            row[field] = _unsigned(row.get(field), (1 << 63) - 1, field, index)
        marker = row.get('fallback_marker')
        if marker is not None and type(marker) is not bool:
            raise ObservationInputError(f'observations[{index}].fallback_marker must be boolean or null')
        row['fallback_marker'] = marker
        before = row['android_mono_before_ns']
        after = row['android_mono_after_ns']
        if (before is None) != (after is None):
            raise ObservationInputError(f'observations[{index}] must provide both monotonic bracket endpoints')
        if before is not None and after < before:
            raise ObservationInputError(f'observations[{index}] has an inverted monotonic bracket')
        rows.append(row)
    return rows, expected_scale


def _sign_extend_u32(value: int) -> int:
    return value if value < (1 << 31) else (0xFFFFFFFF00000000 | value)


def _queue_id_correlation(rows: list[dict[str, Any]]) -> dict[str, Any]:
    qbuf_rows = [row for row in rows if row['qbuf_id_u32'] is not None]
    paired = [row for row in qbuf_rows if row['dqbuf_userptr_u64'] is not None]
    encoding_checked = [row for row in qbuf_rows if row['qbuf_userptr_u64'] is not None]
    encoding_mismatches = sum(
        row['qbuf_userptr_u64'] != _sign_extend_u32(row['qbuf_id_u32'])
        for row in encoding_checked
    )
    key_matches = sum((row['dqbuf_userptr_u64'] & _U32_MAX) == row['qbuf_id_u32'] for row in paired)
    raw_checked = [row for row in paired if row['qbuf_userptr_u64'] is not None]
    raw_matches = sum(row['qbuf_userptr_u64'] == row['dqbuf_userptr_u64'] for row in raw_checked)
    key_mismatches = len(paired) - key_matches
    if not qbuf_rows or not paired:
        status = 'INSUFFICIENT_DATA'
    elif encoding_mismatches or key_mismatches:
        status = 'SYNTHETIC_FAIL'
    elif len(paired) != len(qbuf_rows) or len(encoding_checked) != len(qbuf_rows):
        status = 'INSUFFICIENT_DATA'
    else:
        status = 'SYNTHETIC_PASS'
    return {
        'status': status,
        'qbuf_id_count': len(qbuf_rows),
        'paired_count': len(paired),
        'unpaired_count': len(qbuf_rows) - len(paired),
        'qbuf_encoding_checked': len(encoding_checked),
        'qbuf_encoding_mismatches': encoding_mismatches,
        'lookup_key_matches': key_matches,
        'lookup_key_mismatches': key_mismatches,
        'raw_u64_checked': len(raw_checked),
        'raw_u64_matches': raw_matches,
        'interpretation': 'synthetic m.userptr values only; no kernel guarantee established',
    }


def _frame_sequence(rows: list[dict[str, Any]]) -> dict[str, Any]:
    values = [row['frame_sequence'] for row in rows if row['frame_sequence'] is not None]
    gaps = 0
    missing = 0
    duplicates = 0
    resets = 0
    for previous, current in zip(values, values[1:]):
        if current == previous:
            duplicates += 1
        elif current < previous:
            resets += 1
        elif current > previous + 1:
            gaps += 1
            missing += current - previous - 1
    status = 'INSUFFICIENT_DATA' if len(values) < 2 else (
        'SYNTHETIC_GAPS_DETECTED' if gaps else 'SYNTHETIC_NO_GAPS'
    )
    return {
        'status': status,
        'observed_sequence_count': len(values),
        'gap_count': gaps,
        'missing_sequence_values': missing,
        'duplicate_sequence_count': duplicates,
        'sequence_reset_count': resets,
        'drop_claim': 'NOT_ESTABLISHED',
        'interpretation': 'candidate_sequence_gaps_only',
    }


def _repeated_timestamps(rows: list[dict[str, Any]]) -> dict[str, Any]:
    values = [row['qtimer_value'] for row in rows if row['qtimer_value'] is not None]
    counts = Counter(values)
    repeated = {value: count for value, count in counts.items() if count > 1}
    return {
        'status': 'INSUFFICIENT_DATA' if not values else ('SYNTHETIC_DETECTED' if repeated else 'SYNTHETIC_NOT_DETECTED'),
        'observed_timestamp_count': len(values),
        'repeated_value_count': len(repeated),
        'repeated_observation_count': sum(count - 1 for count in repeated.values()),
        'repeated_values': [{'value': value, 'count': repeated[value]} for value in sorted(repeated)],
        'interpretation': 'synthetic QTIMER field-value repetition; unit and event semantics remain external',
    }


def _fallback(rows: list[dict[str, Any]]) -> dict[str, Any]:
    marked = sum(row['fallback_marker'] is True for row in rows)
    unknown = sum(row.get('fallback_marker') is None for row in rows)
    divergences = [
        row for row in rows
        if row['request_id'] is not None
        and row['timestamp_source_request_id'] is not None
        and row['request_id'] != row['timestamp_source_request_id']
    ]
    return {
        'status': 'SYNTHETIC_ANALYSIS',
        'marked_fallback_count': marked,
        'unknown_marker_count': unknown,
        'request_id_divergence_count': len(divergences),
        'unmarked_divergence_count': sum(row['fallback_marker'] is not True for row in divergences),
        'fallback_frequency_claim': 'NOT_ESTABLISHED',
        'interpretation': 'request ID divergence is a candidate only; it does not prove fallback',
    }


def _linear_fit(points: list[tuple[int, int]]) -> dict[str, Any]:
    unique_x = {x for x, _ in points}
    if len(points) < 3 or len(unique_x) < 2:
        return {
            'status': 'INSUFFICIENT_DATA',
            'reason': 'TOO_FEW_PAIRED_SAMPLES',
            'sample_count': len(points),
            'observed_ns_per_qtimer_unit': None,
            'offset_ns': None,
            'rms_residual_ns': None,
            'r_squared': None,
        }
    if any(current_x < previous_x for (previous_x, _), (current_x, _) in zip(points, points[1:])):
        return {
            'status': 'INSUFFICIENT_DATA',
            'reason': 'NON_MONOTONIC_INPUT',
            'sample_count': len(points),
            'observed_ns_per_qtimer_unit': None,
            'offset_ns': None,
            'rms_residual_ns': None,
            'r_squared': None,
        }
    if any(current_y < previous_y for (_, previous_y), (_, current_y) in zip(points, points[1:])):
        return {
            'status': 'INSUFFICIENT_DATA',
            'reason': 'NON_MONOTONIC_ANDROID_MONO',
            'sample_count': len(points),
            'observed_ns_per_qtimer_unit': None,
            'offset_ns': None,
            'rms_residual_ns': None,
            'r_squared': None,
        }
    x_origin, y_origin = points[0]
    xs = [float(x - x_origin) for x, _ in points]
    ys = [float(y - y_origin) for _, y in points]
    x_mean = math.fsum(xs) / len(xs)
    y_mean = math.fsum(ys) / len(ys)
    denominator = math.fsum((x - x_mean) ** 2 for x in xs)
    if denominator == 0:
        return {
            'status': 'INSUFFICIENT_DATA',
            'reason': 'NO_QTIMER_VARIATION',
            'sample_count': len(points),
            'observed_ns_per_qtimer_unit': None,
            'offset_ns': None,
            'rms_residual_ns': None,
            'r_squared': None,
        }
    slope = math.fsum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys)) / denominator
    relative_intercept = y_mean - slope * x_mean
    residuals = [y - (relative_intercept + slope * x) for x, y in zip(xs, ys)]
    residual_sum = math.fsum(residual * residual for residual in residuals)
    total_sum = math.fsum((y - y_mean) ** 2 for y in ys)
    r_squared = 1.0 - residual_sum / total_sum if total_sum else 1.0
    return {
        'status': 'SYNTHETIC_ESTIMATE',
        'reason': None,
        'sample_count': len(points),
        'observed_ns_per_qtimer_unit': slope,
        'offset_ns': y_origin + relative_intercept - slope * x_origin,
        'rms_residual_ns': math.sqrt(residual_sum / len(points)),
        'r_squared': r_squared,
    }


def _clock_relation(rows: list[dict[str, Any]], expected_scale: float | None) -> dict[str, Any]:
    observer_points = []
    delivery_points = []
    for row in rows:
        qtimer = row['qtimer_value']
        before = row['android_mono_before_ns']
        after = row['android_mono_after_ns']
        if qtimer is None:
            continue
        if before is not None and after is not None:
            midpoint = before + (after - before) // 2
            observer_points.append((qtimer, midpoint))
        delivery = row['observer_delivery_mono_ns']
        if delivery is not None:
            delivery_points.append((qtimer, delivery))
    observer_fit = _linear_fit(observer_points)
    delivery_fit = _linear_fit(delivery_points)
    bracket_widths = [
        row['android_mono_after_ns'] - row['android_mono_before_ns']
        for row in rows if row['android_mono_before_ns'] is not None
    ]
    if observer_fit['status'] != 'SYNTHETIC_ESTIMATE':
        ppm = None
        drift_status = 'INSUFFICIENT_DATA'
    elif expected_scale is None:
        ppm = None
        drift_status = 'BLOCKED_NO_CALIBRATED_QTIMER_SCALE'
    else:
        ppm = (observer_fit['observed_ns_per_qtimer_unit'] / expected_scale - 1.0) * 1_000_000
        drift_status = 'SYNTHETIC_ESTIMATE'
    return {
        'status': 'SYNTHETIC_ANALYSIS',
        'qtimer_to_observer_mono': observer_fit,
        'qtimer_to_delivery_mono': delivery_fit,
        'expected_qtimer_ns_per_unit': expected_scale,
        'observer_bracket_count': len(bracket_widths),
        'observer_bracket_mean_width_ns': (math.fsum(bracket_widths) / len(bracket_widths)
                                           if bracket_widths else None),
        'observer_bracket_max_width_ns': max(bracket_widths) if bracket_widths else None,
        'drift_ppm': ppm,
        'drift_status': drift_status,
        'physical_event_semantics': 'UNPROVEN',
        'interpretation': 'affine field-to-observation relationship; not SOF, exposure, or exact frame age',
    }


def analyze_observations(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and summarize a synthetic dataset without promoting it to runtime evidence."""
    rows, expected_scale = _validate(payload)
    return {
        'schema': 'p3a6.synthetic_analysis_report.v1',
        'analysis_scope': 'OFFLINE_SYNTHETIC_ONLY',
        'experimental_verdict': 'NOT_RUN',
        'observation_count': len(rows),
        'queue_id_correlation': _queue_id_correlation(rows),
        'frame_sequence': _frame_sequence(rows),
        'repeated_timestamps': _repeated_timestamps(rows),
        'fallback': _fallback(rows),
        'clock_relation': _clock_relation(rows, expected_scale),
        'gates': {
            'exact_time': False,
            'mapping_verified': False,
            'pose_verified': False,
            'shared_buffer_identity_verified': False,
            'frame_meta_bridge_verified': False,
            'live_lighthouse_correction_allowed': False,
            'physical_event_verified': False,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Analyze synthetic P3-A6 observations offline')
    parser.add_argument('input', type=Path, help='synthetic JSON input matching p3a6.synthetic_observations.v1')
    parser.add_argument('--output', type=Path, help='optional JSON report path')
    args = parser.parse_args(argv)
    try:
        with args.input.open('rb') as source:
            encoded = source.read(MAX_INPUT_BYTES + 1)
        if len(encoded) > MAX_INPUT_BYTES:
            raise ObservationInputError(f'input exceeds maximum input size of {MAX_INPUT_BYTES} bytes')
        payload = json.loads(encoded)
        result = analyze_observations(payload)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ObservationInputError) as exc:
        print(f'p3a6 analyzer: {exc}', file=sys.stderr)
        return 2
    rendered = json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + '\n'
    if args.output:
        try:
            args.output.write_text(rendered, encoding='utf-8')
        except OSError as exc:
            print(f'p3a6 analyzer: {exc}', file=sys.stderr)
            return 2
    else:
        print(rendered, end='')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
