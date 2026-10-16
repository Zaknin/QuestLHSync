# Pico 4 Pro P2: K0 producer chain, duplicate timestamps and third stamp audit
**Date:** 2026-10-16  
**Evidence:** owner's successful offline `trace_k0_timestamp_producers.ps1` output; two private, SHA-pinned system ELF files; pre-existing private 1,204-frame K0 paired capture.

## Verified at source level

- The QuickCamera path calls `QuickCameraClient::DeQueueFrame` with `FrameMetaDate*` at stack `sp+0x10` and tests success before dispatch. At `0x6667c`, `ldp x11,x10,[sp,#0x10]` loads the first two 64-bit words. At `0x66680`, the frame descriptor base is `x1=sp+0x40`, and at `0x666a8`, `stp x11,x11,[sp,#0x58]` writes that first word twice into frame descriptor `+0x18,+0x20`. Another metadata word `x10` is stored at `[sp,#0x70]` (frame descriptor `+0x30`).
- At `0x666d4–0x666e0`, code loads a callback object from `[PvrCameraDevice+0x30]`, takes its vtable and invokes entry `+0x10` with `x1` pointing to the just-constructed local frame descriptor. It then calls `QuickCameraClient::EnqueueFrame` at `0x666f0`. **The virtual callback target must still be resolved before attributing this route to the active K0 stream.**
- The separate Android `CameraReader::OnImageCallback` calls `AImage_getTimestamp`; `0x3aa68` stores that timestamp as the key of a tree node, and `PvrImageReaderListener` subsequently processes queued images. This does **not** prove `AImageReader` is the active QuickCamera/K0 provider.
- Source literal at `0x254d7` is `camera_%d_%ld_%ld`. The prior `0x3b4c0` call was a varargs printf helper, not a clock-domain converter.
- `CameraManager::writeToSm(kind=0)` copies `pvr_frame_item_t+0x18/+0x20/+0x28` to K0 `slot+114/+122/+130` respectively, directly. It does not perform clock conversion inside this main ring writer. The special `writeToExpSm` is a distinct branch for other ring kind(s), not proof for K0.
- `CameraManager::onFrameAvailable` includes a calculated value assigned at `0xaaeac` to `pvr_frame_item_t+0x28`, and later conditionally calls `writeToSm` at `0xaaef4`. The arithmetic at `0xaae9c–0xaaeac` is approximately `x7 = (x6+x11) - x9 - ((x10*x8)>>1)` under register assignments that must be independently traced. This resembles a midpoint adjustment (half a product), but is **not verified to be an exposure midpoint**, nor is the result's clock epoch known.

## What has and has not been proved

| Item | Status |
|---|---|
| PVR QTIMER maps to CNTVCT_EL0 at 19.2 MHz | Measured independently, sub-microsecond cross-check |
| K0 +114 equals +122 across sampled 1,204 frames | Measured |
| QuickCamera duplicates its first FrameMetaDate word at frame_item +0x18 and +0x20 | Proven in its own native producer path |
| K0 main writer copies frame_item +0x18/+0x20/+0x28 directly to ring +114/+122/+130 | Proven |
| QuickCamera virtual callback specifically supplies active K0 rings | **Unverified** |
| Meaning/source of first QuickCamera FrameMetaDate timestamp | **Unverified** |
| Meaning/source/epoch of computed K0 +130, physical exposure instant | **Unverified** |
| QuestLHSync PC pose clock alignment, K0 camera↔factory calibration mapping | **Unverified** |
| Live exact_time or Lighthouse corrections | **BLOCKED; OBSERVE ONLY** |

## Next step: no additional headset capture

The original read-only `--clock-scan` CSV already has `ring_ts130_ns` for all 1,204 records. Compare it against both raw K0 +122 (QTIMER-like epoch) and BOOTTIME +84, *without assuming either epoch for +130*. The new `pico/tools/audit_k0_slot130.py` is an offline-only report with explicit two alternative hypotheses (if +130 is QTIMER vs if +130 is BOOTTIME). It is backed by five new synthetic unit tests; all transformation flags remain false.

```powershell
cd C:\Dev\PicoLHSync
git pull --ff-only
pwsh -NoProfile -File .\pico\tools\review_k0_slot130.ps1
```

The runner checks existing QTIMER and shadow tests along with the new five before analyzing saved files. It prints four concise per-camera summaries and writes a private `slot130-audit.json`; **no Android, ADB, service, camera, or driver actions**.

To narrow the QuickCamera virtual callback and locate its first FrameMetaDate producer library, an optional second **offline-only** script `pico/tools/audit_k0_callback_dependencies.ps1` inventories the two saved ELF binaries' `DT_NEEDED` and dynamic symbols, dumps the small callback callsite at `0x666c4–0x666f4`, and saves further alternative image reader / CameraManager traces. It does not pull proprietary binaries or access the HMD.

The newly added tools and tests were verified by rereading code from GitHub, **not yet run on the owner's Windows machine**. Do not overstate synthetic tests or source-level provenance in the absence of the next output.


## Owner's completed slot130 and callback dependency audit — 2026-10-16

The owner's Windows run **passed all 19/19** synthetic QTIMER, shadow,
and slot130 tests. Against the earlier real, private 1,204-frame
K0 capture the report was:

- `status=SLOT130_OBSERVED_SOURCE_UNVERIFIED`;
- 301/301 slot130 values **nonzero** for each C0/C3/C4/C5;
- 301/301 values per camera within ±1 second of the K0 raw
  QTIMER-like epoch, **0/301** within ±1 second of BOOTTIME;
- slot130 never exactly equals raw slot+122;
- median `slot130 - slot122 = -225,997 ns` for **each** of the
  four cameras. The median is identical across cameras, but
  this alone does not establish that *every individual* difference
  is fixed or that the timestamp represents the physical exposure center.

The fully readable ARM64 snippet from
`CameraManager::onFrameAvailable` identifies operands unambiguously:

```text
0xaae80: ldr x6,[x21,#0x20]       // raw frame_item T122
0xaae88: madd x9,x26,0x320,x19    // CameraManager indexed camera struct
0xaae8c: ldrsw x8,[x21,#0x14]     // signed frame metric E
0xaae90: ldr x10,[x9,#0x330]      // per-camera parameter B
0xaae94: ldr x9,[x9,#0x338]       // per-camera parameter A
0xaae98: mov x11,#-0xcb20         // -52,000
0xaae9c: add x11,x6,x11
0xaaea0: mul x10,x10,x8
0xaaea4: sub x9,x11,x9
0xaaea8: sub x7,x9,x10,asr #1
0xaaeac: str x7,[x21,#0x28]      // computed field -> K0 slot+130
```

**Exact arithmetic** (modulo AArch64 integer width and arithmetic
shift) is:

```text
slot130 = slot122 - 52000 - camera_config_A
                    - ((camera_config_B * frame_item_E) ASR 1)
A = *(int64*)(manager + 0x320 * cameraIdx + 0x338)
B = *(int64*)(manager + 0x320 * cameraIdx + 0x330)
E = *(int32*)(frameItem + 0x14)
```

This is **proof of a deliberately computed QTIMER-epoch
frame-time adjustment**, because K0 frame+130 is derived directly
from frame+122. It is NOT yet proof that E is exposure, that
A/B represent row or shutter timing, or whether the result
represents start/middle/end of image exposure. The observed
median correction of 225.997 microseconds cannot be generalized
as a constant without full per-frame distribution analysis.

The dependency audit confirmed the exact
`libpvrtrackingcamera.so` ELF links three PICO QuickCamera HIDL
libraries (`common@1.0`, `quickcameramodule@1.0`,
`quickcameradevice@1.0`). The exact
`libpvrtrackingservice.so` links `libpvrtrackingcamera.so`,
`libpvrtrackingbuffer.so` and `libpvrtrackingcommon.so`.
These dependencies corroborate a real camera producer-to-service
architecture, but do not determine which code branch produced
the owner's four active K0 streams.

In `PvrCameraFrame::processCameraFrame`, the native callback
instruction sequence is:

```text
0x666d4: ldr x0,[x8,#0x30]     // callback object
0x666d8: ldr x8,[x0]           // vptr
0x666dc: ldr x8,[x8,#0x10]     // vtable method +0x10
0x666e0: blr x8                // invocation with local frame_item in x1
```

In the service, the `CameraManager::CameraImageListener` vtable
symbol is at `0x15e690` with length 0x30, and
`CameraManager::onFrameAvailable(int,pvr_frame_item_t*)`
is at `0xaa8f4`. **Do not equate these entry points without
resolving ELF relocation/vtable pointer targets and the
PvrCameraDevice listener registration.** A separate
`PvrImageReaderListener` route exists.

This audit also verified `0xaaef4` calls
`CameraManager::writeToSm()` after computing +130. K0 writer
copies this value unchanged to `slot+130`; it does not compute
the timestamp itself. A source-grounded, focused follow-up is to
inspect the per-camera `+0x330/+0x338` initialization, the origin
of frame metric `+0x14`, and the QuickCamera callback vtable.

All data stays local and all safety gates remain BLOCKED for
live `exact_time` or SteamVR pose compensation.
