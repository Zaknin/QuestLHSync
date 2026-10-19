import unittest
import json
import contextlib
import io
from datetime import datetime, timezone
from importlib import import_module
from pathlib import Path
from unittest.mock import patch


def _load_target(module_name, test_case):
    try:
        return import_module(module_name)
    except ModuleNotFoundError:
        test_case.fail(f'{module_name} must be implemented')


def synthetic_payload():
    fixture = Path(__file__).parent / 'fixtures' / 'P3-A6-synthetic-observations.json'
    return json.loads(fixture.read_text(encoding='utf-8'))


class TestP3A6SyntheticObservationAnalyzer(unittest.TestCase):
    def test_analyzer_is_synthetic_only_and_never_sets_runtime_gates(self):
        analyze_observations = _load_target('pico.tools.p3a6_observation_analyzer', self).analyze_observations
        result = analyze_observations(synthetic_payload())

        self.assertEqual(result['analysis_scope'], 'OFFLINE_SYNTHETIC_ONLY')
        self.assertEqual(result['experimental_verdict'], 'NOT_RUN')
        self.assertEqual(result['gates'], {
            'exact_time': False,
            'mapping_verified': False,
            'pose_verified': False,
            'shared_buffer_identity_verified': False,
            'frame_meta_bridge_verified': False,
            'live_lighthouse_correction_allowed': False,
            'physical_event_verified': False,
        })

    def test_queue_correlation_checks_sign_extended_qbuf_and_dequeue_lookup_key(self):
        analyze_observations = _load_target('pico.tools.p3a6_observation_analyzer', self).analyze_observations
        result = analyze_observations(synthetic_payload())['queue_id_correlation']

        self.assertEqual(result['paired_count'], 2)
        self.assertEqual(result['qbuf_encoding_mismatches'], 0)
        self.assertEqual(result['lookup_key_matches'], 1)
        self.assertEqual(result['lookup_key_mismatches'], 1)
        self.assertEqual(result['raw_u64_matches'], 1)
        self.assertEqual(result['status'], 'SYNTHETIC_FAIL')

    def test_sequence_gaps_are_reported_as_candidates_not_camera_drop_proof(self):
        analyze_observations = _load_target('pico.tools.p3a6_observation_analyzer', self).analyze_observations
        result = analyze_observations(synthetic_payload())['frame_sequence']

        self.assertEqual(result['gap_count'], 1)
        self.assertEqual(result['missing_sequence_values'], 1)
        self.assertEqual(result['drop_claim'], 'NOT_ESTABLISHED')
        self.assertEqual(result['interpretation'], 'candidate_sequence_gaps_only')

    def test_repeated_qtimer_values_are_counted_across_distinct_requests(self):
        analyze_observations = _load_target('pico.tools.p3a6_observation_analyzer', self).analyze_observations
        result = analyze_observations(synthetic_payload())['repeated_timestamps']

        self.assertEqual(result['repeated_value_count'], 1)
        self.assertEqual(result['repeated_observation_count'], 1)
        self.assertEqual(result['status'], 'SYNTHETIC_DETECTED')

    def test_fallback_markers_and_request_id_divergence_remain_separate(self):
        analyze_observations = _load_target('pico.tools.p3a6_observation_analyzer', self).analyze_observations
        result = analyze_observations(synthetic_payload())['fallback']

        self.assertEqual(result['marked_fallback_count'], 1)
        self.assertEqual(result['unknown_marker_count'], 1)
        self.assertEqual(result['request_id_divergence_count'], 3)
        self.assertEqual(result['unmarked_divergence_count'], 2)
        self.assertEqual(result['fallback_frequency_claim'], 'NOT_ESTABLISHED')

    def test_clock_fit_reports_synthetic_scale_and_calibrated_drift(self):
        analyze_observations = _load_target('pico.tools.p3a6_observation_analyzer', self).analyze_observations
        result = analyze_observations(synthetic_payload())['clock_relation']

        fit = result['qtimer_to_observer_mono']
        self.assertEqual(fit['sample_count'], 4)
        self.assertAlmostEqual(fit['observed_ns_per_qtimer_unit'], 1.0001, places=7)
        self.assertAlmostEqual(result['drift_ppm'], 100.0, places=5)
        self.assertEqual(result['drift_status'], 'SYNTHETIC_ESTIMATE')
        self.assertEqual(result['physical_event_semantics'], 'UNPROVEN')

    def test_missing_qtimer_scale_blocks_ppm_but_keeps_observed_relation(self):
        analyze_observations = _load_target('pico.tools.p3a6_observation_analyzer', self).analyze_observations
        payload = synthetic_payload()
        payload.pop('expected_qtimer_ns_per_unit')

        result = analyze_observations(payload)['clock_relation']

        self.assertIsNotNone(result['qtimer_to_observer_mono']['observed_ns_per_qtimer_unit'])
        self.assertIsNone(result['drift_ppm'])
        self.assertEqual(result['drift_status'], 'BLOCKED_NO_CALIBRATED_QTIMER_SCALE')

    def test_counter_wrap_or_reset_prevents_a_single_affine_drift_fit(self):
        analyze_observations = _load_target('pico.tools.p3a6_observation_analyzer', self).analyze_observations
        payload = synthetic_payload()
        payload['observations'][2]['qtimer_value'] = 500_000_000

        result = analyze_observations(payload)['clock_relation']

        self.assertEqual(result['qtimer_to_observer_mono']['status'], 'INSUFFICIENT_DATA')
        self.assertEqual(result['qtimer_to_observer_mono']['reason'], 'NON_MONOTONIC_INPUT')
        self.assertEqual(result['drift_status'], 'INSUFFICIENT_DATA')

    def test_observation_count_is_bounded(self):
        module = _load_target('pico.tools.p3a6_observation_analyzer', self)
        payload = synthetic_payload()
        payload['observations'] = payload['observations'] * 2501

        with self.assertRaises(module.ObservationInputError):
            module.analyze_observations(payload)

    def test_real_or_untyped_datasets_are_rejected_without_claims(self):
        module = _load_target('pico.tools.p3a6_observation_analyzer', self)
        payload = synthetic_payload()
        payload['dataset_kind'] = 'experimental'

        with self.assertRaises(module.ObservationInputError):
            module.analyze_observations(payload)

    def test_empty_synthetic_dataset_is_not_a_runtime_pass(self):
        analyze_observations = _load_target('pico.tools.p3a6_observation_analyzer', self).analyze_observations
        payload = synthetic_payload()
        payload['observations'] = []
        result = analyze_observations(payload)

        self.assertEqual(result['experimental_verdict'], 'NOT_RUN')
        self.assertEqual(result['queue_id_correlation']['status'], 'INSUFFICIENT_DATA')
        self.assertEqual(result['clock_relation']['drift_status'], 'INSUFFICIENT_DATA')
        self.assertTrue(all(value is False for value in result['gates'].values()))

    def test_omitted_optional_fallback_marker_is_treated_as_unknown(self):
        analyze_observations = _load_target('pico.tools.p3a6_observation_analyzer', self).analyze_observations
        payload = {
            'schema': 'p3a6.synthetic_observations.v1',
            'dataset_kind': 'synthetic',
            'observations': [{}],
        }

        result = analyze_observations(payload)

        self.assertEqual(result['fallback']['unknown_marker_count'], 1)
        self.assertEqual(result['fallback']['marked_fallback_count'], 0)

    def test_rejects_invalid_timestamp_brackets(self):
        module = _load_target('pico.tools.p3a6_observation_analyzer', self)
        payload = synthetic_payload()
        payload['observations'][0]['android_mono_before_ns'] = 50
        payload['observations'][0]['android_mono_after_ns'] = 49

        with self.assertRaises(module.ObservationInputError):
            module.analyze_observations(payload)

    def test_cli_writes_a_synthetic_report_without_runtime_verdict(self):
        import tempfile

        module = _load_target('pico.tools.p3a6_observation_analyzer', self)
        fixture = Path(__file__).parent / 'fixtures' / 'P3-A6-synthetic-observations.json'
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / 'report.json'
            self.assertEqual(module.main([str(fixture), '--output', str(output)]), 0)
            report = json.loads(output.read_text(encoding='utf-8'))
        self.assertEqual(report['experimental_verdict'], 'NOT_RUN')
        self.assertEqual(report['analysis_scope'], 'OFFLINE_SYNTHETIC_ONLY')

    def test_cli_rejects_oversized_input_before_json_parse(self):
        module = _load_target('pico.tools.p3a6_observation_analyzer', self)
        fixture = Path(__file__).parent / 'fixtures' / 'P3-A6-synthetic-observations.json'
        stderr = io.StringIO()
        with patch.object(module, 'MAX_INPUT_BYTES', 1, create=True):
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(stderr):
                status = module.main([str(fixture)])

        self.assertEqual(status, 2)
        self.assertIn('exceeds maximum input size', stderr.getvalue())


class TestP3A6HardwareExecutionGate(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)
        self.approval = {
            'schema': 'p3a6.hardware_approval.v1',
            'approval_id': 'run-2026-10-18-01',
            'device': 'Pico 4 Pro',
            'approved_actions': ['read-only-inventory'],
            'max_duration_seconds': 60,
            'max_observations': 300,
            'issued_at_utc': '2026-10-18T11:00:00Z',
            'expires_at_utc': '2026-10-18T13:00:00Z',
        }

    def test_missing_receipt_or_confirmation_fails_closed(self):
        check_hardware_execution_gate = _load_target('pico.tools.p3a6_execution_gate', self).check_hardware_execution_gate
        self.assertFalse(check_hardware_execution_gate(None, 'read-only-inventory', None, self.now).allowed)
        self.assertFalse(check_hardware_execution_gate(self.approval, 'read-only-inventory', None, self.now).allowed)

    def test_exact_explicit_approval_is_scoped_to_device_action_and_expiry(self):
        check_hardware_execution_gate = _load_target('pico.tools.p3a6_execution_gate', self).check_hardware_execution_gate
        phrase = 'P3-A6 APPROVE run-2026-10-18-01 read-only-inventory'
        decision = check_hardware_execution_gate(
            self.approval, 'read-only-inventory', phrase, self.now,
        )
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.status, 'APPROVED_FOR_SCOPED_ACTION')

        self.assertFalse(check_hardware_execution_gate(
            self.approval, 'ptrace', phrase, self.now,
        ).allowed)
        self.assertFalse(check_hardware_execution_gate(
            self.approval, 'read-only-inventory', 'approve', self.now,
        ).allowed)
        self.assertFalse(check_hardware_execution_gate(
            self.approval, 'read-only-inventory', phrase,
            datetime(2026, 10, 18, 14, 0, tzinfo=timezone.utc),
        ).allowed)

    def test_simple_yes_and_rejected_responses_are_not_shared_gate_tokens(self):
        check_hardware_execution_gate = _load_target('pico.tools.p3a6_execution_gate', self).check_hardware_execution_gate
        for response in ('yes', 'no', '', 'YES', 'confirm', None):
            with self.subTest(response=response):
                decision = check_hardware_execution_gate(
                    self.approval, 'read-only-inventory', response, self.now,
                )
                self.assertFalse(decision.allowed)
                self.assertEqual(decision.status, 'BLOCKED_CONFIRMATION_REQUIRED')

    def test_unbounded_or_overlong_approval_is_rejected(self):
        check_hardware_execution_gate = _load_target('pico.tools.p3a6_execution_gate', self).check_hardware_execution_gate
        phrase = 'P3-A6 APPROVE run-2026-10-18-01 read-only-inventory'
        unbounded = dict(self.approval)
        unbounded.pop('max_duration_seconds')
        self.assertFalse(check_hardware_execution_gate(
            unbounded, 'read-only-inventory', phrase, self.now,
        ).allowed)

        overlong = dict(self.approval, max_duration_seconds=601)
        self.assertFalse(check_hardware_execution_gate(
            overlong, 'read-only-inventory', phrase, self.now,
        ).allowed)

    def test_one_approval_cannot_authorize_multiple_methods(self):
        check_hardware_execution_gate = _load_target('pico.tools.p3a6_execution_gate', self).check_hardware_execution_gate
        broad = dict(self.approval, approved_actions=['read-only-inventory', 'ptrace-ioctl-observer'])
        phrase = 'P3-A6 APPROVE run-2026-10-18-01 read-only-inventory'

        self.assertFalse(check_hardware_execution_gate(
            broad, 'read-only-inventory', phrase, self.now,
        ).allowed)


if __name__ == '__main__':
    unittest.main()
