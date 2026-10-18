"""Small, offline contract model for the statically traced QuickCamera path.

This models field widths, array ordering, mapping bounds and claim gates. It
does not prove Qualcomm CSL's backing-store behavior or physical time semantics.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AbiLayout:
    native_info_size: int = 0x368
    native_ids_offset: int = 0x220
    native_metadata_size_offset: int = 0x320
    native_metadata_offset_offset: int = 0x324
    native_count_width_bits: int = 32
    native_buffer_id_width_bits: int = 32
    native_handle_fd_width_bits: int = 32
    native_pointer_width_bits: int = 64
    hidl_info_size: int = 0x58
    hidl_handles_offset: int = 0x20
    hidl_ids_offset: int = 0x30
    hidl_pointer_width_bits: int = 64
    hidl_vector_length_width_bits: int = 32
    hidl_metadata_width_bits: int = 32
    client_ids_offset: int = 0x60
    client_count_offset: int = 0x68
    client_metadata_size_offset: int = 0x70
    client_metadata_offset_offset: int = 0x74
    client_pointer_width_bits: int = 64
    client_count_width_bits: int = 32
    client_metadata_width_bits: int = 32
    pvr_buf_info_stride: int = 0x30
    pvr_buf_handle_offset: int = 0x18
    pvr_buf_base_offset: int = 0x20
    pvr_buf_metadata_offset_offset: int = 0x28
    pvr_buf_metadata_offset_width_bits: int = 32
    max_buffers: int = 64
    frame_metadata_size: int = 0x1C


ABI = AbiLayout()


@dataclass(frozen=True)
class BufferHandle:
    ordinal: int
    fd: int


@dataclass(frozen=True)
class BufferMapping:
    ordinal: int
    queue_id: int
    base: int
    length: int
    metadata_offset: int


@dataclass(frozen=True)
class ProvenanceModel:
    """One ordered transfer instance; values are supplied from reviewed evidence."""

    buffer_count: int
    image_size: int
    metadata_size: int
    metadata_offset: int
    producer_ids: tuple[int, ...]
    hidl_ids: tuple[int, ...]
    client_ids: tuple[int, ...]
    producer_handles: tuple[BufferHandle, ...]
    hidl_handles: tuple[BufferHandle, ...]
    pvr_handles: tuple[BufferHandle, ...]
    mappings: tuple[BufferMapping, ...]
    native_info_size: int = ABI.native_info_size
    hidl_info_size: int = ABI.hidl_info_size
    pvr_buf_info_stride: int = ABI.pvr_buf_info_stride

    def resolve_dequeued(self, queue_id: int) -> BufferMapping:
        """Resolve the queue key used by the PVR index-to-record lookup."""
        for mapping in self.mappings:
            if mapping.queue_id == queue_id:
                return mapping
        raise KeyError(queue_id)


def _is_u32(value: int) -> bool:
    return isinstance(value, int) and 0 <= value <= 0xFFFFFFFF


def _validate_handles(name: str, handles: tuple[BufferHandle, ...], count: int) -> list[str]:
    errors = []
    if len(handles) != count:
        errors.append(f'{name} count does not match buffer_count')
    for index, handle in enumerate(handles):
        if handle.ordinal != index:
            errors.append(f'{name}[{index}] is out of buffer order')
        if not isinstance(handle.fd, int) or not 0 <= handle.fd <= 0x7FFFFFFF:
            errors.append(f'{name}[{index}] has invalid fd')
    return errors


def validate_transfer(model: ProvenanceModel) -> list[str]:
    """Return structural violations without making runtime or physical claims."""
    errors: list[str] = []
    if model.native_info_size != ABI.native_info_size:
        errors.append('native QuickCameraBufInfo size mismatch')
    if model.hidl_info_size != ABI.hidl_info_size:
        errors.append('HIDL QuickCameraBufInfo size mismatch')
    if model.pvr_buf_info_stride != ABI.pvr_buf_info_stride:
        errors.append('PVR buf_info stride mismatch')
    if not isinstance(model.buffer_count, int) or not 1 <= model.buffer_count <= ABI.max_buffers:
        errors.append('buffer_count outside supported range')
        return errors

    for name, ids in (('producer_ids', model.producer_ids), ('hidl_ids', model.hidl_ids),
                      ('client_ids', model.client_ids)):
        if len(ids) != model.buffer_count:
            errors.append(f'{name} count does not match buffer_count')
        for index, value in enumerate(ids):
            if not _is_u32(value):
                errors.append(f'{name}[{index}] is not u32')
    if model.hidl_ids != model.producer_ids:
        errors.append('hidl_ids do not preserve producer order')
    if model.client_ids != model.producer_ids:
        errors.append('client_ids do not preserve producer order')

    errors.extend(_validate_handles('producer_handles', model.producer_handles, model.buffer_count))
    errors.extend(_validate_handles('hidl_handles', model.hidl_handles, model.buffer_count))
    errors.extend(_validate_handles('pvr_handles', model.pvr_handles, model.buffer_count))
    if len(model.mappings) != model.buffer_count:
        errors.append('mappings count does not match buffer_count')

    if not _is_u32(model.image_size):
        errors.append('image_size is not u32')
    if not _is_u32(model.metadata_size):
        errors.append('metadata_size is not u32')
    if not _is_u32(model.metadata_offset):
        errors.append('metadata_offset is not u32')
    if (_is_u32(model.image_size) and _is_u32(model.metadata_size)
            and model.image_size + model.metadata_size > 0xFFFFFFFF):
        errors.append('image plus metadata length overflows u32')
    if _is_u32(model.metadata_size) and model.metadata_size < ABI.frame_metadata_size:
        errors.append('metadata region is smaller than FrameMetaDate fields')
    if model.metadata_offset != model.image_size:
        errors.append('metadata_offset does not follow image region')

    seen_ids = set()
    for index, mapping in enumerate(model.mappings):
        if mapping.ordinal != index:
            errors.append(f'mappings[{index}] is out of buffer order')
        if not _is_u32(mapping.queue_id):
            errors.append(f'mappings[{index}].queue_id is not u32')
        elif mapping.queue_id in seen_ids:
            errors.append(f'mappings[{index}] duplicates queue_id')
        seen_ids.add(mapping.queue_id)
        if index < len(model.producer_ids) and mapping.queue_id != model.producer_ids[index]:
            errors.append(f'mappings[{index}] queue_id does not match buffer id')
        if not isinstance(mapping.base, int) or mapping.base < 0:
            errors.append(f'mappings[{index}] has invalid mapped base')
        if not isinstance(mapping.length, int) or mapping.length < 0:
            errors.append(f'mappings[{index}] has invalid mapped range')
        if not _is_u32(mapping.metadata_offset):
            errors.append(f'mappings[{index}].metadata_offset is not u32')
        if mapping.length != model.image_size + model.metadata_size:
            errors.append(f'mappings[{index}] length does not match image plus metadata')
        if mapping.metadata_offset != model.metadata_offset:
            errors.append(f'mappings[{index}] metadata offset differs from client scalar')
        if (_is_u32(mapping.metadata_offset) and _is_u32(model.metadata_size)
                and isinstance(mapping.length, int)
                and mapping.metadata_offset + model.metadata_size > mapping.length):
            errors.append(f'mappings[{index}] metadata region exceeds mapped range')
    return errors


@dataclass(frozen=True)
class TimestampEvidence:
    metadata_request_id: int | None = None
    timestamp_source_request_id: int | None = None
    fallback_used: bool = False
    qtimer_labeled_source: bool = False
    clock_conversion_verified: bool = False
    clocks_synchronized: bool = False
    physical_event: str | None = None
    shared_buffer_backing_store_verified: bool = False
    pose_verified: bool = False
    mapping_verified: bool = False

    @property
    def request_id_diverges(self) -> bool:
        return (self.metadata_request_id is not None
                and self.timestamp_source_request_id is not None
                and self.metadata_request_id != self.timestamp_source_request_id)

    @property
    def exact_time(self) -> bool:
        return (not self.fallback_used and not self.request_id_diverges
                and self.clock_conversion_verified and self.clocks_synchronized
                and self.physical_event is not None)


_CLAIM_REQUIREMENTS = {
    'clocks_synchronized': lambda e: e.clock_conversion_verified and e.clocks_synchronized,
    'exact_time': lambda e: e.exact_time,
    'physical_sof': lambda e: e.physical_event == 'sof',
    'qtimer_labeled_csl_message': lambda e: e.qtimer_labeled_source,
    'shared_buffer_backing_store': lambda e: e.shared_buffer_backing_store_verified,
    'live_lighthouse_correction': lambda e: (e.exact_time and e.pose_verified
                                               and e.mapping_verified
                                               and e.shared_buffer_backing_store_verified),
}


def unsupported_claims(evidence: TimestampEvidence, claims: set[str]) -> tuple[str, ...]:
    """Return timestamp/geometry claims not justified by this evidence record."""
    unsupported = [claim for claim in claims
                   if claim not in _CLAIM_REQUIREMENTS or not _CLAIM_REQUIREMENTS[claim](evidence)]
    return tuple(sorted(unsupported))
