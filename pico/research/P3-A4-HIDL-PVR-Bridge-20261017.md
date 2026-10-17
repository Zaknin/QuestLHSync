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
    pwsh -NoProfile -File .\pico\tools\trace_p3a4_quickcamera_bridge.ps1

All disassembly excerpts and JSON are **private**, with local staging under pico/build and canonical SMB evidence under \\192.168.23.63\Torrents\Codex\PicoLHSync\P3-A; ZIP and JSON committed by .part, SHA readback, then sidecar .sha256 **last**. Google Drive /Codex is only a downstream mirrored reader. All gates remain false and the manifest reports TRACE_CAPTURED_NOT_PROVEN; successful extraction is NOT proof of actual optical event or live corrected pose.

The next review must inspect the disassembly windows and symbol xrefs to show or reject an exact byte-level connection from CSLFenceCallback metadata at byte 0 of the native per-frame buffer to PVR QuickCameraClient DeQueueFrame first word. If no symbol survived stripping, inspect callsite branch targets on the pinned P2 ELF, do not guess mapping or enable tracking.

Validation state: contract tests authored; owner Windows and PVR hardware-source bridge proof pending.
