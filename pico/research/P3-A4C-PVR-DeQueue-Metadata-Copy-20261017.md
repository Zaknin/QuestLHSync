# P3-A4C — SHA-verified PVR DeQueueFrame buffer-to-FrameMetaDate copy

Date: 2026-10-17. Owner Win11 P3-A4B run `TRACE_CAPTURED_NOT_PROVEN`, 8/8 mock tests PASS, 15 windows, 22 PVR symbols. Verified canonical private evidence: `p3a4-bridge-20261017T190059Z-2cfc1c9e.zip` in `PicoLHSync/P3-A`, independently retrieved from Google Drive mirror and verified against `.sha256` sidecar.

| Evidence artifact | SHA-256 |
|---|---|
| private bridge ZIP | `0956792fc7f7e5c6d018c937a9af0d200e95b0ec0de3af5859c3e09f948f6f5e` |
| separate manifest JSON | `c766b8a20f045e5d12ce5674e65ac32290bf9a56dc10b1528128ffb8b0228caa` |
| pinned PVR input | `cf9e507f412ec33d62c2f720669fcdd093f1822c9cbf3adefd0a26a6b4d072ee` |
| pinned QuickCamera core input | `fb22355acd35b9772a5538a7d1c49175641165ad0368e7c47e5831f5f1727017` |
| pinned HIDL input | `c3157e66d842dcdca148f1b98328bd5e7ce80c4ab9bbbacba895465556314f47` |

Archive includes 15 narrow AArch64 disassembly windows plus an identical embedded manifest. Raw proprietary code stays private, not in GitHub.

## Directly verified native PVR consumer

`PvrCameraDevice::PvrCameraFrame::processCameraFrame`:
- `0x6662c` passes a stack `FrameMetaDate*` at `sp+0x10`; `0x66634` invokes **exactly** `QuickCameraClient::DeQueueFrame(void**, FrameMetaDate*)` through PLT.
- `0x6667c` reads first two `u64` words from that returned structure; `0x666a8` duplicates its first timestamp word to both PVR frame_item `+0x18/+0x20`. Subsequent K0 slot copying is established in P2.
- `0x666b0` reads the 32-bit fields at FrameMetaDate `+0x10/+0x14`, and `0x666bc` copies the first into a PVR frame item. This is layout evidence only, not physical exposure semantics.

`QuickCameraClient::DeQueueFrame(void**, FrameMetaDate*)` (`0x6b6e8`, size `0x1a8`):
- `0x6b720` asks `VideoQueueUtil::DeQueVbQueueBuffer` to dequeue a V4L2 buffer index.
- `0x6b7ec` dereferences the matching buffer map node to an internal buffer object. `0x6b7f0` loads **base address** from object `+0x20`; `0x6b7f4` loads **32-bit metadata offset** from object `+0x28`; `0x6b7f8` forms `metadata_ptr=base+offset`.
- `0x6b7fc/0x6b800` load/store metadata `u64` at `+0x08`, then `0x6b804/0x6b808` load/store `u64` at `+0x00`.
- `0x6b80c–0x6b820` directly copy `u32` at `+0x10/+0x14/+0x18`. There is **no timestamp subtraction, conversion, or offset** inside this successful dequeue branch.
- `0x6b824–0x6b828` pass the buffer base back as the image-data pointer.
- All three exported PVR `DeQueueFrame` overloads perform the same 8+8+4+4+4 byte metadata copy, using the same per-buffer base+offset addressing. Other two entries: `0x6b1a4` (native_handle**,void**,meta*) and `0x6b520` (native_handle**,meta*).

## Producer-side comparison (from P3-A3)

In `quickcamera.core.so`, `CSLMessageHandler` uses `CSLMessage+0x18` as a 64-bit QTIMER-labeled event at `0x37618` and stores it in a modulo-38 request timestamp ring at `0x37640`. `CSLFenceCallback` stores selected cached `u64` at metadata `+0` (`0x386c8/0x386cc` or `0x387f4/0x387fc`), request ID `+0x8` at `0x3881c` and additional fields `+0x10/+0x14/+0x18`. A timed-wait expiry branch `0x38be4–0x38c20` may **substitute the preceding request's timestamp**. The matched record sizes/field offsets strongly support the candidate chain.

**Important proof boundary:** exact identity between producer's metadata destination, the exported native handles / HIDL buffer descriptor, and PVR's mapped `base+metadata_offset` is **not yet proven** by this 15-window capture. The actual camera hardware physical event and the runtime occurrence of the previous-request fallback are also unknown. Distinguish:
- `pvr_dequeue_metadata_copy_verified=true` (source-level)
- `pvr_shared_buffer_identity_verified=false`
- `producer_to_frame_meta_verified=false`
- `physical_exposure_event_verified=false`
- `exact_time=false`
- `live_lighthouse_correction_allowed=false`
- `mapping_verified=false`
- `pose_verified=false`

## Recommended next offline trace

Trace how the HIDL `QuickCameraBufInfo` native handles plus per-buffer metadata offset map into PVR `QuickCameraClient`'s `base+0x20, offset+0x28` buffer object. Focus on configuration callback invoked from `ConfigAndAllocBuffers@0x6a3dc`, `PrepareStreamOn@0x6a768` mapping setup, and the local constructor/callback helper responsible for allocating and storing the mapped buffer object. **Do not repeat P2 camera captures, force device wake, change firmware, or enable live Lighthouse correction.**

This note records the evidence directly examined on 2026-10-17 without making unproven physical or cross-machine time claims.

## P3-A4D — Targeted callback-vtable relocation follow-up (source prepared)

The exact PVR consumer copy is verified, but same shared memory still requires an identity proof. The PVR `PrepareStreamOn()` implementation (already retrieved from the 15-window archive) inserts buffer records into three indexes; `DeQueueFrame(void**,FrameMetaDate*)` follows the V4L2 dequeued index to one such record and loads its image mapping at `record+0x20`, metadata offset at `record+0x28`. PVR `ConfigAndAllocBuffers@0x6a3f0-0x6a408` constructs a C++ HIDL callback functor whose vtable sits near `0x752c0`. The callback's real function implementation was NOT in the previously captured 15 windows. This is the next specific source to resolve, not a request for new Pico capture.

The revised trace script v3 locally reads ELF relocation records from the pinned private PVR binary and collects exact entries at `0x752b0..0x75330`. A bounded set of candidate addresses is included in its private disassembly archive. **All candidates remain unverified** until instructions establish that the callback copies HIDL `QuickCameraBufInfo` buffer descriptor/offset into the fields referenced by `PrepareStreamOn`. No public vendor ELF bytes, raw disassembly or private calibration are committed.

The source is deterministic and offline-only; it does not use ADB, Pico, SteamVR, or networking except publishing hashed evidence to private TrueNAS. Presence of relocation candidates cannot by itself certify the callback binding, native-handle identity, QTIMER physical event or live correction. Existing fail-closed flags remain false.

Owner invocation remains `python -m unittest pico.tests.test_p3a4_bridge_contract -v` then `pwsh -NoProfile -File .\pico\tools\trace_p3a4_quickcamera_bridge.ps1` after git pull. Expected window count is 15 plus recovered callback candidates (potentially zero); do **not** assert an exact number before hardware-host test. Test status: synthetic checks to be run on owner's Windows; GitHub readback required.
