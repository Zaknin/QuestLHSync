# P3-A4D — callback relocation probe owner run and offset trace

Date: 2026-10-18. Owner Windows PowerShell 7.6.6 run after code HEAD `208c20ecbf394194fb63c4e3bfd30a88c1b9f9b0`.

## Direct owner-run facts

- Git fast-forward to `208c20e` completed.
- Python `pico.tests.test_p3a4_bridge_contract`: **12/12 PASS**, including native PowerShell `Parser.ParseFile` syntax validation.
- `trace_p3a4_quickcamera_bridge.ps1` completed with `TRACE_CAPTURED_NOT_PROVEN`, `windows=15`, `pvr_symbol_hits=22`.
- Private canonical SMB artifacts: `P3-A/p3a4-bridge-20261018T093025Z-a991ee47.zip`, `.json`, `.sha256`.
- Report has the same number of windows as the base v2 capture, which **indicates no additional disassembly windows were added by the v3 relocation candidate selector**. This is NOT evidence that the callback lacks relocations or that the metadata bridge is disproven. Relocation parser/filter and raw count are not yet inspected from this run.
- At this entry's creation, current artifact had **not yet synchronized into the connected Google Drive folder**; no unobserved archive contents are asserted.

## Relevant native instruction comparison from earlier SHA-verified P3-A4B archive

PVR `QuickCameraClient::PrepareStreamOn()@0x6a768`:
- `0x6a908`: loads the per-stream buffer count from `client+0x68`.
- `0x6a910`: reads a per-buffer 32-bit offset array pointer from `client+0x60`.
- `0x6a92c`: loads the per-buffer offset `w24 = *(uint32_t*)offset_array`.
- `0x6aa18`: reads one buffer's mapped-address slot at `[client+0x10 + index*0x30 + 0x18]`.
- `0x6aa78/0x6aa7c`: stores that buffer base and offset into the tree node at `node+0x20` and `node+0x28`.
- `QuickCameraClient::DeQueueFrame(void**,FrameMetaDate*)@0x6b6e8`, `0x6b7f0..0x6b808`: reads those stored base/offset fields and copies metadata's first `u64` into `FrameMetaDate+0`.

QuickCamera producer `CSLFenceCallback` body, from verified quickcamera.core trace:
- `0x386a4`: reads device-global offset `x10=[CamQuickAccessDevice+0x70]`.
- `0x386b8`: creates metadata pointer `x9=frame_buffer_base+x10`.
- `0x386c8..0x386cc` (or `0x387f4..0x387fc`): writes the selected cached CSL timestamp into metadata `+0`. Timed-out previous-request timestamp fallback remains possible.

The **specific next proof** is to identify the native QuickCameraBufInfo field carrying the producer metadata offset, trace `converttoHidl` and the PVR HIDL configuration callback, and show that `client+0x60` contains the exact same metadata offset for the matching native/shared buffer. A structural resemblance is not enough to assert native memory identity. PVR callback vtable `0x752c0` is a hypothesis pending examination of v3 `callback_relocations` evidence.

Gates: `observe_only=true`, `producer_to_frame_meta_verified=false`, `shared_buffer_identity_verified=false`, `exact_time=false`, `physical_exposure_event_verified=false`, `mapping_verified=false`, `pose_verified=false`, `live_lighthouse_correction_allowed=false`. No Pico/SteamVR interaction is needed to resolve this offline source-level boundary.
