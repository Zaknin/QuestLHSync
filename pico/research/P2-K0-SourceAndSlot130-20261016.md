# Pico 4 Pro P2: K0 producer chain, duplicate timestamps and third stamp audit
**Date:** 2026-10-16  
**Evidence:** owner's successful offline \`trace_k0_timestamp_producers.ps1\` output; two private, SHA-pinned system ELF files; pre-existing private 1,204-frame K0 paired capture.

## Verified at source level

- The QuickCamera path calls \`QuickCameraClient::DeQueueFrame\` with \`FrameMetaDate*\` at stack \`sp+0x10\` and tests success before dispatch. At \`0x6667c\`, \`ldp x11,x10,[sp,#0x10]\` loads the first two 64-bit words. At \`0x66680\`, the frame descriptor base is \`x1=sp+0x40\`, and at \`0x666a8\`, \`stp x11,x11,[sp,#0x58]\` writes that first word twice into frame descriptor \`+0x18,+0x20\`. Another metadata word \`x10\` is stored at \`[sp,#0x70]\` (frame descriptor \`+0x30\`).
- At \`0x666d4–0x666e0\`, code loads a callback object from \`[PvrCameraDevice+0x30]\`, takes its vtable and invokes entry \`+0x10\` with \`x1\` pointing to the just-constructed local frame descriptor. It then calls \`QuickCameraClient::EnqueueFrame\` at \`0x666f0\`. **The virtual callback target must still be resolved before attributing this route to the active K0 stream.**
- The separate Android \`CameraReader::OnImageCallback\` calls \`AImage_getTimestamp\`; \`0x3aa68\` stores that timestamp as the key of a tree node, and \`PvrImageReaderListener\` subsequently processes queued images. This does **not** prove \`AImageReader\` is the active QuickCamera/K0 provider.
- Source literal at \`0x254d7\` is \`camera_%d_%ld_%ld\`. The prior \`0x3b4c0\` call was a varargs printf helper, not a clock-domain converter.
- \`CameraManager::writeToSm(kind=0)\` copies \`pvr_frame_item_t+0x18/+0x20/+0x28\` to K0 \`slot+114/+122/+130\` respectively, directly. It does not perform clock conversion inside this main ring writer. The special \`writeToExpSm\` is a distinct branch for other ring kind(s), not proof for K0.
- \`CameraManager::onFrameAvailable\` includes a calculated value assigned at \`0xaaeac\` to \`pvr_frame_item_t+0x28\`, and later conditionally calls \`writeToSm\` at \`0xaaef4\`. The arithmetic at \`0xaae9c–0xaaeac\` is approximately \`x7 = (x6+x11) - x9 - ((x10*x8)>>1)\` under register assignments that must be independently traced. This resembles a midpoint adjustment (half a product), but is **not verified to be an exposure midpoint**, nor is the result's clock epoch known.

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

The original read-only \`--clock-scan\` CSV already has \`ring_ts130_ns\` for all 1,204 records. Compare it against both raw K0 +122 (QTIMER-like epoch) and BOOTTIME +84, *without assuming either epoch for +130*. The new \`pico/tools/audit_k0_slot130.py\` is an offline-only report with explicit two alternative hypotheses (if +130 is QTIMER vs if +130 is BOOTTIME). It is backed by five new synthetic unit tests; all transformation flags remain false.

\`\`\`powershell
cd C:\Dev\PicoLHSync
git pull --ff-only
pwsh -NoProfile -File .\pico\tools\review_k0_slot130.ps1
\`\`\`

The runner checks existing QTIMER and shadow tests along with the new five before analyzing saved files. It prints four concise per-camera summaries and writes a private \`slot130-audit.json\`; **no Android, ADB, service, camera, or driver actions**.

To narrow the QuickCamera virtual callback and locate its first FrameMetaDate producer library, an optional second **offline-only** script \`pico/tools/audit_k0_callback_dependencies.ps1\` inventories the two saved ELF binaries' \`DT_NEEDED\` and dynamic symbols, dumps the small callback callsite at \`0x666c4–0x666f4\`, and saves further alternative image reader / CameraManager traces. It does not pull proprietary binaries or access the HMD.

The newly added tools and tests were verified by rereading code from GitHub, **not yet run on the owner's Windows machine**. Do not overstate synthetic tests or source-level provenance in the absence of the next output.
