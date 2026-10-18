"""Offline ABI and dataflow contracts for the static QuickCamera study."""
from dataclasses import replace
import unittest

from pico.tools.p3a4_provenance_model import (
    BufferHandle,
    BufferMapping,
    ProvenanceModel,
    TimestampEvidence,
    unsupported_claims,
    validate_transfer,
)


def valid_transfer():
    return ProvenanceModel(
        buffer_count=2,
        image_size=0x1000,
        metadata_size=0x100,
        metadata_offset=0x1000,
        producer_ids=(0xA1, 0xB2),
        hidl_ids=(0xA1, 0xB2),
        client_ids=(0xA1, 0xB2),
        producer_handles=(BufferHandle(0, 12), BufferHandle(1, 13)),
        hidl_handles=(BufferHandle(0, 22), BufferHandle(1, 23)),
        pvr_handles=(BufferHandle(0, 32), BufferHandle(1, 33)),
        mappings=(
            BufferMapping(0, 0xA1, 0x100000, 0x1100, 0x1000),
            BufferMapping(1, 0xB2, 0x200000, 0x1100, 0x1000),
        ),
    )


class TestAbiAndBufferTransfer(unittest.TestCase):
    def test_layout_constants_match_observed_native_hidl_and_pvr_abis(self):
        from pico.tools.p3a4_provenance_model import ABI

        self.assertEqual(ABI.native_info_size, 0x368)
        self.assertEqual(ABI.hidl_info_size, 0x58)
        self.assertEqual(ABI.pvr_buf_info_stride, 0x30)
        self.assertEqual(ABI.native_ids_offset, 0x220)
        self.assertEqual(ABI.native_metadata_size_offset, 0x320)
        self.assertEqual(ABI.native_metadata_offset_offset, 0x324)
        self.assertEqual(ABI.native_count_width_bits, 32)
        self.assertEqual(ABI.native_pointer_width_bits, 64)
        self.assertEqual(ABI.hidl_pointer_width_bits, 64)
        self.assertEqual(ABI.hidl_vector_length_width_bits, 32)
        self.assertEqual(ABI.client_count_width_bits, 32)
        self.assertEqual(ABI.client_metadata_width_bits, 32)
        self.assertEqual(ABI.client_ids_offset, 0x60)
        self.assertEqual(ABI.client_count_offset, 0x68)
        self.assertEqual(ABI.client_metadata_size_offset, 0x70)
        self.assertEqual(ABI.client_metadata_offset_offset, 0x74)
        self.assertEqual(ABI.pvr_buf_metadata_offset_offset, 0x28)

    def test_valid_transfer_preserves_count_order_and_distinct_offset(self):
        model = valid_transfer()

        self.assertEqual(validate_transfer(model), [])
        self.assertEqual(model.mappings[1].queue_id, model.client_ids[1])
        self.assertNotEqual(model.client_ids[0], model.metadata_offset)

    def test_rejects_32_bit_identifier_overflow(self):
        model = valid_transfer()
        model = model.__class__(**{**model.__dict__, 'hidl_ids': (0xA1, 1 << 32)})

        self.assertIn('hidl_ids[1] is not u32', validate_transfer(model))

    def test_rejects_structure_size_mismatch(self):
        model = replace(valid_transfer(), native_info_size=0x360)

        self.assertIn('native QuickCameraBufInfo size mismatch', validate_transfer(model))

    def test_rejects_count_and_per_buffer_order_mismatch(self):
        model = replace(valid_transfer(), mappings=valid_transfer().mappings[:1])

        self.assertIn('mappings count does not match buffer_count', validate_transfer(model))

    def test_rejects_hidl_vector_count_mismatch(self):
        model = replace(valid_transfer(), hidl_ids=(0xA1,))

        self.assertIn('hidl_ids count does not match buffer_count', validate_transfer(model))

    def test_rejects_identifier_order_mismatch(self):
        model = replace(valid_transfer(), hidl_ids=(0xB2, 0xA1))

        errors = validate_transfer(model)
        self.assertIn('hidl_ids do not preserve producer order', errors)

    def test_rejects_reordered_hidl_handles(self):
        model = replace(valid_transfer(), hidl_handles=(BufferHandle(1, 23), BufferHandle(0, 22)))

        self.assertIn('hidl_handles[0] is out of buffer order', validate_transfer(model))

    def test_rejects_metadata_region_missing_or_outside_mapping(self):
        model = replace(valid_transfer(), metadata_size=0)

        self.assertIn('metadata region is smaller than FrameMetaDate fields', validate_transfer(model))

    def test_rejects_metadata_region_past_mapping_end(self):
        model = valid_transfer()
        mappings = (replace(model.mappings[0], length=0x1080), model.mappings[1])
        model = replace(model, mappings=mappings)

        errors = validate_transfer(model)
        self.assertIn('mappings[0] length does not match image plus metadata', errors)
        self.assertIn('mappings[0] metadata region exceeds mapped range', errors)

    def test_rejects_u32_mmap_length_overflow(self):
        model = replace(valid_transfer(), image_size=0xFFFFFF00, metadata_size=0x200)

        self.assertIn('image plus metadata length overflows u32', validate_transfer(model))

    def test_queue_key_resolves_the_same_ordered_mapping(self):
        model = valid_transfer()

        self.assertEqual(model.resolve_dequeued(0xB2).ordinal, 1)
        with self.assertRaises(KeyError):
            model.resolve_dequeued(0xCC)


class TestTimestampEvidence(unittest.TestCase):
    def test_fallback_can_pair_current_request_id_with_prior_timestamp_id(self):
        evidence = TimestampEvidence(
            metadata_request_id=40,
            timestamp_source_request_id=39,
            fallback_used=True,
            qtimer_labeled_source=True,
        )

        self.assertTrue(evidence.request_id_diverges)
        self.assertFalse(evidence.exact_time)
        self.assertEqual(unsupported_claims(evidence, {'exact_time'}), ('exact_time',))

    def test_rejects_sof_clock_sync_and_exact_time_claims_without_evidence(self):
        evidence = TimestampEvidence()

        self.assertEqual(
            unsupported_claims(evidence, {'exact_time', 'physical_sof', 'clocks_synchronized'}),
            ('clocks_synchronized', 'exact_time', 'physical_sof'),
        )

    def test_rejects_shared_backing_store_claim_without_csl_contract(self):
        evidence = TimestampEvidence()

        self.assertEqual(
            unsupported_claims(evidence, {'shared_buffer_backing_store'}),
            ('shared_buffer_backing_store',),
        )

    def test_rejects_live_correction_and_unknown_claims_without_all_gates(self):
        evidence = TimestampEvidence()

        self.assertEqual(
            unsupported_claims(evidence, {'live_lighthouse_correction', 'clock_is_monotonic'}),
            ('clock_is_monotonic', 'live_lighthouse_correction'),
        )


if __name__ == '__main__':
    unittest.main()
