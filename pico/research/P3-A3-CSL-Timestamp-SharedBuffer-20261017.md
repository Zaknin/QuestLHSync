# P3-A3 — QuickCamera CSL timestamp cache to per-frame buffer (2026-10-17)

State: **OFFLINE SOURCE PARTIAL**, no new headset access. Public text findings only; no proprietary ELF, raw disassembly, captures, or calibration uploaded.

## Input integrity
Private canonical archive: `PicoLHSync/P3-A/p3a-producers-20261017T143042Z-f9c27e45.zip`.
ZIP SHA-256: `2d937e84f50c3990fb07c6ee0304d0146b087da1cc9c79fb3b8d3a41cdd73dd4`.
All 8 ELF64/AArch64 members re-verified against the accompanying canonical manifest SHA-256, with the sidecar checksum checked. The analysis targeted pinned `/vendor/lib64/quickcamera.core.so` SHA-256 `fb22355acd35b9772a5538a7d1c49175641165ad0368e7c47e5831f5f1727017`. GNU readelf and LLVM 17 llvm-objdump examined source locations without executing the binaries.

## Native instruction evidence

* `CamQuickAccessDevice::CSLMessageHandler` entry veneer `0x4c470 -> 0x375d0`. The message branch reads `CSLMessage+0x18` at `0x37618`, then writes that value into a modulo-38 per-device 64-bit timestamp ring at `0x37640`; an associated availability byte is set. The library's frame-message logging explicitly identifies `CSLTimestampTypeQtimer`, `requestID`, `timestamp`, and a *separate* `monoTimestamp`. Labels are corroborative, not a substitute for source dataflow.
* `CamQuickAccessDevice::CSLFenceCallback` entry veneer `0x4c478 -> 0x38338`. At `0x386c8/0x386cc` it reads the modulo-38 cache and stores the 64-bit result to a metadata destination derived from the device's buffer mapping. The timed-wait case again performs this transfer at `0x387f4/0x387fc`.
* At `0x3881c` it writes request ID into the same metadata record at `+0x08`. At `0x38970` and `0x38978` it writes per-sensor data at `+0x10` and `+0x14`; at `0x38a38`, another state field at `+0x18`. Thus the native producer emits a contiguous structured record with timestamp at `+0x00`, request ID `+0x08`, further fields at `+0x10/+0x14/+0x18`.
* Important exception: after timed-wait expiry, `0x38be4–0x38c20` computes `(requestID-1) mod 38` and copies the *previous* cached timestamp into the metadata record. Therefore the first word cannot automatically be declared the contemporaneous frame SOF for every callback without characterizing this fallback, its conditions, and frame association.
* `SensorNode::ExposureCallback` entry veneer `0x4c498 -> 0x42564` reads `CNTVCT_EL0` at `0x42594`; this is a separate path and does not establish the source of the first producer metadata word.
* `quickcameramodule@1.0-impl.so` depends directly on `quickcamera.core.so`; HIDL `OnBufferReady(unsigned int)` carries a buffer index. The HIDL `QuickCameraBufInfo` conversion includes native handles for shared buffers. These establish an implementation bridge, not yet exact byte-for-byte correspondence to PVR's `QuickCameraClient::DeQueueFrame(FrameMetaDate*)`.

## Status and remaining proof

**Established:** a device QuickCamera CSL QTIMER-labeled frame-message 64-bit value can be placed into byte 0 of per-frame shared-buffer metadata, alongside a request ID and sensor fields. The timeout branch can substitute the prior request's value.

**Not established:** (a) that these exact 8-byte metadata contents are always the `FrameMetaDate.first_u64` duplicated by PVR into active K0 rings; (b) SOF/exposure start/center/end meaning and sensor timestamp calibration; (c) timeout frequency in active K0; (d) active HIDL instance and PVR camera association. Additional proof must connect the shared-buffer address and layout through `QuickCameraClient::DeQueueFrame` and verify physical event semantics. The P2 `slot130` coefficient audit stays closed.

Safety gates unchanged: `observe_only=true`, `exact_time=false`, `live_lighthouse_correction_allowed=false`, `mapping_verified=false`, `pose_verified=false`.

Next action is **offline-only** investigation of PVR QuickCameraClient DeQueueFrame mapping/size and HIDL QuickCameraBufInfo handle layout against the newly identified metadata record. Do not alter cameras, firmware, tracking services or the SteamVR driver.