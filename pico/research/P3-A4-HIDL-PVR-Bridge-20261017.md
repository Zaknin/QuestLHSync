# P3-A4 — QuickCamera shared-buffer metadata to PVR FrameMetaDate

Date 2026-10-17. P3-A2 eight ELF archive SHA-256: 2d937e84f50c3990fb07c6ee0304d0146b087da1cc9c79fb3b8d3a41cdd73dd4. P3-A3 CSL timestamp-cache findings remain a source-level partial proof only.

## Newly verified offline (from the same pinned eight ELF)

The 64-bit vendor HIDL implementation of ConfigAndAllocBuffers calls CamQuickAccessDevice::Initialize at 0xA5A8, passing a native QuickCameraBufInfo structure, then calls converttoHidl at 0xA688 to produce the HIDL buffer descriptor list. The conversion body is at 0x9494 (function trampoline 0xAE60). It copies native scalar fields +0x00/+0x04/+0x08/+0x0C/+0x10/+0x14/+0x18 into HIDL fields and builds a list of native handles; these are **buffer configuration** fields, NOT necessarily per-frame timestamps. Quickcamera.core CamQuickAccessDevice::AllocImageBuffers uses CSLAlloc at 0x36964, and native_handle_create at 0x36A50. The HIDL sBufferReady callback at 0x98E4 passes only a buffer index to the client callback. Accordingly, there is a concrete allocation/descriptor/ready-index pipeline, but the exact shared memory mapping in the PVR client has NOT been proved.

These vendor code findings should not be confused with the PVR consumer's FrameMetaDate, nor with QTIMER physical SOF or exposure semantics. No live timing overrides permitted.

## P3-A4 owner-host offline bridge trace

The remaining offline proof depends on the **private, pre-existing** P2 libpvrtrackingcamera.so in the owner's Windows checkout. This ELF is not in the eight-file P3-A2 producer package and is not available in the connected Drive mirror.

New source: pico/tools/trace_p3a4_quickcamera_bridge.ps1. It reads exactly SHA-256 pinned P2 PVR, QuickCamera core and vendor HIDL implementation from local pico/build. It invokes only local NDK llvm-objdump to produce bounded disassembly of the native PVR processCameraFrame reader, CSL message/fence/previous-request fallback, buffer allocation and HIDL conversion/callback/config. It inventories dynamic symbols matching QuickCameraClient/DeQueueFrame/FrameMetaDate/etc. If the PVR ELF exposes a symbol for the DeQueueFrame consumer, the script adds up to four short auto-located windows (bounded by 0x500 bytes). It does NOT connect to Pico or run any ADB command. It never uploads ELF bytes.

On Windows PowerShell 7:

    Set-Location C:\Dev\PicoLHSync
    git pull --ff-only
    python -m unittest pico.tests.test_p3a4_bridge_contract -v
    pwsh -NoProfile -File .\pico\tools\trace_p3a4_quickcamera_bridge.ps1 -OutputRoot $env:P3_A_OUTPUT_ROOT

Before launch, configure `P3_A_OUTPUT_ROOT` to a private output directory outside the repository. All disassembly excerpts and JSON are **private**, with local staging under pico/build and publication to that configured output root; ZIP and JSON are committed by .part, SHA readback, then sidecar .sha256 **last**. A downstream mirror is only a reader. All gates remain false and the manifest reports TRACE_CAPTURED_NOT_PROVEN; successful extraction is NOT proof of actual optical event or live corrected pose.

The next review must inspect the disassembly windows and symbol xrefs to show or reject an exact byte-level connection from CSLFenceCallback metadata at byte 0 of the native per-frame buffer to PVR QuickCameraClient DeQueueFrame first word. If no symbol survived stripping, inspect callsite branch targets on the pinned P2 ELF, do not guess mapping or enable tracking.

Validation state: contract tests authored; owner Windows and PVR hardware-source bridge proof pending.

## 2026-10-17 P3-A4B — exact PVR overload capture correction

Owner ran P3-A4 twice on Windows: 6/6 structural contract tests PASS each time; private outputs `p3a4-bridge-20261017T182916Z-a530c94b` and `p3a4-bridge-20261017T184444Z-5747d0ea`, each `TRACE_CAPTURED_NOT_PROVEN`, 12 windows and 22 PVR symbol hits. The first ZIP/JSON/sidecar was retrieved from downstream Drive and its digests verified, with 12 excerpt files intact. The second archive is canonical on SMB but Cloud Sync readback was not yet visible when checked.

Review revealed a **trace-selector defect**, not a PVR issue: four auto-selected symbol excerpts captured early unrelated QuickCameraClient functions, despite dynamic symbols exposing all **three** specific DeQueueFrame overloads. Grounded dynamic symbol addresses and sizes from PVR pinned `cf9e507...`:

| PVR function | ELF start | ELF symbol size |
|---|---:|---:|
| DeQueueFrame(native_handle**, void**, FrameMetaDate*) | 0x6B1A4 | 0x1D4 |
| DeQueueFrame(native_handle**, FrameMetaDate*) | 0x6B520 | 0x1C8 |
| DeQueueFrame(void**, FrameMetaDate*) | 0x6B6E8 | 0x1A8 |
| ConfigAndAllocBuffers | 0x6A3DC | 0xC8 |
| PrepareStreamOn | 0x6A768 | 0x484 |
| QuickCameraClient ctor | 0x6A148 | 0x180 |
| PvrCameraDeviceCallback::OnBufferReady | 0x663E4 | 0x10 |

Version 2 of `trace_p3a4_quickcamera_bridge.ps1` now captures **all seven specific functions in full ELF-symbol extents**, and the eight previous source regions. It resolves by exact mangled-to-demangled ABI-signature patterns, deduplicates duplicate ctor aliases, requires exactly one matching executable symbol per target, and fails closed if size or symbol mismatches. No new device access, no software changes to runtime code, and no producer-origin certification. Expected output is 15 windows and 22 PVR symbol hits on the unchanged P2 SHA-pinned source, but only a real Windows execution can confirm that.

Offline reader hypothesis to check in v2 evidence: whether `QuickCameraClient::DeQueueFrame(void**, FrameMetaDate*)` reads the same metadata bytes at the native shared-buffer base / mapped native handle that `CamQuickAccessDevice::CSLFenceCallback` fills at offset 0. This PVR boundary was **not** established by prior 12-window output. Do not report timestamp producer chain or physical exposure event as PASS before showing the actual loads/stores and pointer origin.

## Owner Windows P3-A4B run: 2026-10-17T19:00:59Z

Commit `fedad8b` (exact-symbol tracer) was pulled on the owner's Windows. `python -m unittest pico.tests.test_p3a4_bridge_contract -v`: 8/8 PASS. Read-only local PowerShell trace: `TRACE_CAPTURED_NOT_PROVEN`, **15 windows**, **22 PVR symbol hits**, no reported errors. Canonical private evidence: `P3-A/p3a4-bridge-20261017T190059Z-2cfc1c9e.zip`, alongside `.json` and `.sha256` sidecar. No ADB and no runtime changes to Pico or SteamVR. The owner has a private SMB copy, but new ZIP bytes were **not yet available through the Drive mirror** at the latest independent check; no bridge inference is attributed to unexamined windows.

Independently rechecked earlier (SHA-validated) private PVR consumer disassembly at `processCameraFrame+0x664e8`:
- `0x6662c`: `x2=sp+0x10` is the output `FrameMetaDate*`; `0x66634`: PLT call to `QuickCameraClient::DeQueueFrame(void**,FrameMetaDate*)`.
- `0x6667c`: `ldp x11,x10,[sp,#0x10]` loads metadata u64 at +0 and +8.
- `0x666a8`: `stp x11,x11,[sp,#0x58]` duplicates first timestamp word to PVR frame item.
- `0x666b0`: `ldp w12,w9,[sp,#0x20]` reads metadata +0x10 and +0x14; `0x666bc`: first 32-bit value is copied into frame item.

This `FrameMetaDate` layout (+0 timestamp, +8 second u64, +0x10/+0x14 sensor-related fields) **agrees structurally** with the QuickCamera producer buffer record identified in P3-A3. It is **not** proof that the same native/shared buffer is directly copied through the HIDL client. Next review must examine the newly captured three PVR DeQueueFrame overloads and ConfigAndAllocBuffers, including mapped buffer address origin, offset, buffer identity and callback index. The pending physical timestamp/active K0/live-gating claims remain false.
