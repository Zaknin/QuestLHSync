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


## P2 next static/quantitative step (2026-10-16)

A median difference of `-225997 ns` for all four K0 streams is
compatible with a near-constant configuration/exposure adjustment,
but the median alone cannot distinguish a fixed correction from
a frame-varying calculation. The exact source equation loads
`E` from `frame_item+0x14`, `B` from the per-camera
`CameraManager+0x320*id+0x330`, and `A` from
`CameraManager+0x320*id+0x338`. Their actual units and source
remain unknown.

Two **offline** tools have been added:

- `pico/tools/audit_k0_slot130_variation.py` computes per-frame
  `vendor_ns - ring_ts130_ns` distributions for the existing
  private CSV, including unique values, adjacent changes, min,
  median and max, and most common exact nanosecond differences;
  distinguishes dynamic correction from a frozen parameter.
  Five synthetic regression cases were added in
  `pico/tests/test_k0_slot130_variation.py`.
- `pico/tools/trace_k0_slot130_parameters.ps1` runs the five
  new tests and actual CSV distribution, then performs
  SHA-256-pinned offline disassembly of
  `CameraManager::collectCameraInfo`,
  `PvrCameraDevice::setPvrImageListener`, and
  `CameraImageListener` ELF relocation candidates to
  investigate parameter and callback ownership. All full
  traces are saved in the existing private static evidence folder;
  only short excerpts are printed.

```powershell
cd C:\Dev\PicoLHSync
git pull --ff-only
pwsh -NoProfile -File .\pico\tools\trace_k0_slot130_parameters.ps1
```

The new tools and synthetic tests were checked in and read back
but have NOT yet been executed on the owner's Windows checkout.
No headset access, new camera data capture, exposure manipulation,
or live `exact_time` activation is needed.


## Owner's second offline run: invariant correction and listener relocation — 2026-10-16

The owner executed `trace_k0_slot130_parameters.ps1` successfully.
All **5/5** new synthetic tests passed. The existing **1,204
K0 frames** show **exactly the same integer subtraction in every
individual frame** of the 12-second recording:

```text
C0: 301/301, raw slot122 - computed slot130 = 225997 ns
C3: 301/301, raw slot122 - computed slot130 = 225997 ns
C4: 301/301, raw slot122 - computed slot130 = 225997 ns
C5: 301/301, raw slot122 - computed slot130 = 225997 ns
all channels: unique=1, adjacent transitions=0, min=median=max=225997 ns
```

Thus `slot130 = slot122 - 225997ns` **for this recording**, not
a universal hard-coded value guaranteed across exposures, devices,
power cycles, cameras, or firmware versions. From the native formula,
the observed aggregate of camera config A and the signed product B*E
is `225997-52000=173997ns` for all observed frames; that fact
does not yet separately identify A, B, or E, nor the actual instant
of optical exposure.

The disassembly also confirms how the QuickCamera listener is stored:

```asm
# PvrCameraDevice::setPvrImageListener(shared_ptr<PvrImageListener>)
0x6502c: ldr x19,[x0,#0x38]
0x65030: stp x9,x8,[x0,#0x30]   // listener object and shared ownership

# PvrCameraFrame::processCameraFrame() callback dispatch
0x666d4: ldr x0,[x8,#0x30]   // listener object from device
0x666d8: ldr x8,[x0]         // vptr
0x666dc: ldr x8,[x8,#0x10]   // virtual method at +0x10
0x666e0: blr x8              // frame descriptor passed in x1
```

The service's real, ELF-relocated vtable has:
- `_ZTVN3pvr13CameraManager19CameraImageListenerE` at
  `0x15e690` (length `0x30`).
- `R_AARCH64_ABS64` at `0x15e6b0` →
  `pvr::CameraManager::CameraImageListener::onFrameAvailable(pvr_frame_item_t*)`
  at **`0xabbfc`**.
- `R_AARCH64_ABS64` at `0x15e6b8` →
  `CameraImageListener::onError(int)` at `0xabc64`.
- Two earlier `R_AARCH64_RELATIVE` vtable entries
  `0x15e6a0` and `0x15e6a8`, which may be destructor entries.
- `R_AARCH64_GLOB_DAT` at `0x163370` referencing the vtable.

With the expected Itanium-style vptr address point at
`0x15e6a0`, a virtual call at `vptr+0x10` resolves to
`0x15e6b0`, exactly the `onFrameAvailable` method. This is a
**concrete callback interface match**, and strengthens a
QuickCamera→CameraManager producer connection. It still remains to
prove that the runtime `PvrCameraDevice` uses this specific
`CameraImageListener` instance for the four observed K0 rings;
the presence of another potential listener implementation makes
source-level listener registration and active branch relevant.

The service `onFrameAvailable(int,pvr_frame_item_t*)` at
`0xaae80–0xaaeac` computes the adjustable K0 +130 timestamp,
then calls `writeToSm` at `0xaaef4` (and possibly another
branch at `0xaab5c`). Those native formulas and ring-field
offsets remain as previously proven.

**No need to keep Pico powered on** for continuing this static
ELF/replay stage. The owner can use a separate Pimax Crystal
headset while Pico is off. Next hardware-dependent phase (true
camera exposure epoch, per-camera optics/extrinsics, synchronization
with live SteamVR poses) is explicitly deferred until Pico returns.

Safety: no PFR1 timestamps were rewritten; `exact_time=false`
and all Lighthouse live-correction gates stay blocked. All raw
hardware captures and ELF binaries remain private and local.


## P2 offline cross-reference audit: last producer/listener registration link

Pico remains powered off while owner uses Pimax Crystal. No
fresh capture is needed to resolve the **static** callback link.

The known machine-code/vtable facts should be distinguished from
the remaining runtime assignment:

```text
PvrCameraDevice::setPvrImageListener(...)
    -> stores shared_ptr listener at device+0x30
PvrCameraFrame::processCameraFrame() at 0x666e0
    -> virtual call [listener.vptr+0x10] with pvr_frame_item_t*
CameraManager::CameraImageListener vtable ABI:
    vtable base 0x15e690, callable address point 0x15e6a0,
    method +0x10 (relocation at 0x15e6b0)
    -> CameraImageListener::onFrameAvailable at 0xabbfc
    -> candidate onward callback into CameraManager::onFrameAvailable
    -> CameraManager::writeToSm(kind=0) -> K0 slots
```

The exact vtable relocation is **already confirmed** on this
firmware. What remains unproven: the listener installed on
each of the four active K0-producing PvrCameraDevice objects
has this CameraImageListener vtable, rather than an alternate
producer/listener.

New `pico/tools/audit_k0_listener_xrefs.py` performs **two-file
SHA-pinned offline-only** whole-`.text` disassembly, validates
the real service vtable relocation, prints the exact callback
forwarder and QuickCamera callsite, and searches all callable
functions for these useful sources:

- direct calls to `PvrCameraDevice::setPvrImageListener`;
- direct `CameraImageListener` / `CameraManager::onFrameAvailable`
  edges;
- `STR/STUR/STP` writes to per-camera config `+0x330/+0x338`;
- all other read/write references to these config offsets.

Six synthetic parsing and ABI-gate tests in
`pico/tests/test_k0_listener_xrefs.py` are designed to
fail closed for wrong vtable slots; no vendor binaries or
disassembly text go into the repository.

`pico/tools/trace_k0_listener_xrefs.ps1` runs these tests
before the full offline XREF audit, saves complete results to
`p2-static-clock-private-*/p2-listener-cross-references.txt`
and prints a short index of source function names only:

```powershell
cd C:\Dev\PicoLHSync
git pull --ff-only
pwsh -NoProfile -File .\pico\tools\trace_k0_listener_xrefs.ps1
```

This tool has **not yet run** on the owner's PC. The source-level
cross-references are a candidate for proving the callback chain,
not a substitute for an observed runtime association with K0.
Furthermore, until the QuickCamera first metadata word's true
hardware origin and meaning are established, the strongly
consistent QTIMER time-domain hypothesis remains
`k0_image_timestamp_is_qtimer=UNVERIFIED`.
The physical capture/exposure instant and SteamVR pose clock
also remain unverified; `exact_time=false`,
`live_lighthouse_correction_allowed=false`.


## IMPORTANT: source cross-check proves native formula operand E=4 on all observed K0 frames

This follows directly from comparing owner-supplied `writeToSm`
disassembly and the **actual Java ring-selection logic**:

```text
main K0 writer (service ELF):
  0xab7c8 ldp w8,w11,[x21,#0x10]  -> w11 = frame_item+0x14
  0xab810 stur w11,[x22,#0x0d]    -> K0 slot+97+0x0d = slot+110

Java PicoFrameReader.java, all --clock-scan K0 accepted frames:
  c.view.getInt(base+110) == 4
  (also rechecked after stable-slot sequence validation)

native slot+130 formula:
  0xaae8c ldrsw x8,[x21,#0x14]    -> E = 4 for accepted K0 frames
  slot130 = slot122 - 52000 - A - ((B*4) ASR 1)
          = slot122 - 52000 - A - 2*B
```

Since `slot122 - slot130 = 225997ns` on **all 1,204
accepted frames**, the native arithmetic imposes a precise
constraint under the same camera runtime conditions:

```text
A + 2*B = 225997 - 52000 = 173997 ns
```

This is stronger than guessing from the constant median; the
source proves **why E did not vary in the selected frames**.
It is a camera metadata **exposure code/mode value `4`**
(the production Java reader already names the field
`exposure`), **not a verified duration in nanoseconds**.
Do not label `E=4` as `4ns`, `4us`, `4 rows`,
or any known physical exposure duration. Whether the
specific correction represents image-exposure midpoint,
rolling-shutter delay, start-of-frame offset or another
vendor clock alignment is still unknown.

On the candidate QuickCamera metadata path, `FrameMetaDate`
at `sp+0x10` also supplies `E`:
`ldp w12,w9,[sp,#0x20]` at `0x666b0`
loads the 32-bit value at metadata `+0x10`;
`str w12,[sp,#0x54]` at `0x666bc` writes
`pvr_frame_item_t+0x14` (base `sp+0x40`).
This is an independent, source-level **candidate** route for
the K0 exposure code. It still requires resolving which
listener is bound to each active K0-producing camera.

No new hardware capture and no live correction are needed
for this inference. The Java comment was updated to distinguish
the exposure setting from a measured physical duration;
program execution behavior is unchanged.


## Offline callback xref run — 2026-10-17

Owner ran the SHA-pinned two-ELF cross-reference scan
`trace_k0_listener_xrefs.ps1` after pulling `ab6145e`.
**Six of six** synthetic tests passed and the scan completed.

Key result: in `libpvrtrackingcamera.so`,
`pvr::PvrQuickCamera::setPvrImageListener` calls
`PvrCameraDevice::setPvrImageListener` at **0x63a1c**.
The latter setter stores the shared listener pointer at
`device+0x30`, subsequently invoked in
`PvrCameraFrame::processCameraFrame()` at 0x666e0.
The service callback vtable relocation
`0x15e6b0 → CameraImageListener::onFrameAvailable@0xabbfc`
was revalidated.

**Not yet shown:** construction/registration of the specific
`CameraImageListener` object through the higher-level
`PvrQuickCamera` instance that is actually responsible for
active K0 ids C0/C3/C4/C5. The service has no **direct**
`bl ...setPvrImageListener` match; calls may go through the
`PvrCameraBase` virtual interface. The zero matches
are NOT proof that registration never happens.

Raw field accesses `+0x330,+0x338` also need
base-register attribution: the unspecialized disassembly
scanner matched unrelated `ConfigManager::getAim2GripTrans`,
C++ container code, `PicoCameraDevice`, etc. These are
**not** evidence for the `CameraManager` per-camera
timestamp parameters A and B. Relevant, but still ambiguous,
candidate regions are:
- `CameraManager::CameraManager`: 0xa71ec/0xa71f0;
- `CameraManager::setCameraParameters`:
  0xa8a0c/10, 0xa8bd0/d4, 0xa8d2c/30, 0xa90cc/d0;
- `CameraImageListener::onFrameAvailable`: 0xabbfc;
- `PvrQuickCamera::setPvrImageListener`: 0x63a1c.

The offline tool `audit_k0_listener_xrefs.py` was tightened
to require **both** the correct vtable slot 0x15e6b0
and exact relocation target 0xabbfc, with a new
seventh regression test rejecting a forged/wrong target.
Raw offset matches are now labeled as *base-unverified*.

A new hash-pinned, bounded-excerpt script
`pico/tools/trace_k0_listener_wiring_parameters.ps1`
will print only the listed constructor/setup/callback function
windows, including the originating registers around these
addresses. It saves text disassembly beside the owner's
existing private ELF files and never opens the headset.

```powershell
cd C:\Dev\PicoLHSync
git pull --ff-only
pwsh -NoProfile -File .\pico\tools\trace_k0_listener_wiring_parameters.ps1
```

This version has **not yet run on the owner's PC**.
Remaining safety gates are unchanged:
`K0 producer callback ownership=UNVERIFIED`,
`FrameMetaDate QTIMER origin=UNVERIFIED`,
`slot130 optical exposure event=UNVERIFIED`,
`live_lighthouse_correction_allowed=false`.


## New owner offline output — 2026-10-17: callback forwarding and constructor provenance

The owner's `trace_k0_listener_wiring_parameters.ps1` ran
successfully with **7/7 regression tests passing** and both native
ELF SHA-256 pins accepted. Key findings:

1. The native listener body
   `CameraManager::CameraImageListener::onFrameAvailable`
   at `0xabbfc` is a definite forwarder to
   `CameraManager::onFrameAvailable(int,pvr_frame_item_t*)`.
   The function reads `frame_item[0]` into `w8`, accepts
   `w8<=3` for a compact unsigned-byte jump table at
   **VA 0x73a10**, and uses
   `target=0xabc24+4*table[w8]`. Its known case targets
   send the item to camera IDs **0, 3, 4, 5**; an additional
   case can read camera ID from `listener+0x10`.
   The **four actual table bytes have not yet been read**
   from the private ELF, so the exact index→camera route
   should not be guessed. The callback's active registration
   for the four observed K0 rings also remains unverified.

2. `PvrQuickCamera::setPvrImageListener` at
   `0x6397c` walks owned `PvrCameraDevice` objects and
   invokes their `setPvrImageListener` at `0x63a1c`.
   The device setter at `0x65030` stores the listener
   shared pointer into `device+0x30`; frame producer
   dispatch subsequently calls the listener vtable
   entry at `+0x10`. This completes the *generic*
   QuickCamera callback forwarding interface, but not
   binding a concrete `CameraImageListener` to an active
   sensor.

3. `CameraManager::CameraManager` performs
   `x28=x20; x23=x28-0x300;` and stores `xzr`
   at `[x23+0x330]`, `d8` at `[x23+0x338]`
   (0xa71ec/0xa71f0), so in **this local register
   context** they are `[x28+0x30]` and
   `[x28+0x38]`. We still need to establish how
   `x28` relates to `CameraManager` and the
   `cameraIdx*0x320` layout before treating these
   initializer values as native timestamp constants B/A.
   In `setCameraParameters`, `adrp x8,0x163000;
   ldr x8,[x8,#0x330]` clearly accesses
   global ELF page data, **not necessarily**
   `CameraInfo+0x330`; previous broad offset matches
   from this function must be excluded as false positive
   candidates for A/B.

New **offline-only** tools have been committed:

- `pico/tools/audit_k0_listener_table.py` reads exactly
  four bytes at the known jump table VA 0x73a10 via
  ELF `PT_LOAD` mappings after checking the exact
  service ELF SHA-256. It only recognizes actual
  case instruction addresses seen in the native
  disassembly and refuses unexpected branch targets.
  Six new unit tests are in
  `pico/tests/test_k0_listener_table.py`.
- `pico/tools/trace_k0_constructor_dispatch.ps1`
  first runs the previous seven and new six tests,
  decodes the branch routing, and prints bounded
  constructor/prologue/QuickCamera listener assembly
  plus potential vtable GOT references. All
  complete text reports are retained locally and
  no device operations are performed.

```powershell
cd C:\Dev\PicoLHSync
git pull --ff-only
pwsh -NoProfile -File .\pico\tools\trace_k0_constructor_dispatch.ps1
```

The newly authored script and tests **have not yet been
run on the owner's PC**; no camera timestamp domain
may be upgraded from UNVERIFIED based solely on this
static dispatch mapping. `OBSERVE ONLY`,
`exact_time=false`, SteamVR HMD pose injection blocked.


## Owner's confirmed jump table; seven-slot constructor and unresolved pointer bases — 2026-10-17

The owner successfully ran `trace_k0_constructor_dispatch.ps1`
with **13/13 tests PASS**. The SHA-pinned service ELF
contains exactly these four unsigned bytes at VA
`0x73a10`: **`00 07 0A 0D`**. They resolve the
`CameraImageListener::onFrameAvailable` dispatch as:

| Native `pvr_frame_item_t[0]` | Table byte | Native branch | CameraManager ID |
|---|---:|---|---:|
| 0 | 0 | 0xabc24 | 0 |
| 1 | 7 | 0xabc40 | 3 |
| 2 | 10 | 0xabc4c | 4 |
| 3 | 13 | 0xabc58 | 5 |

This is **direct static evidence** of the exact same set
of camera IDs the existing K0 reader uses. It closes the
previous unknown branch-table mapping, **not** the final
active listener instance registration or physical-to-factory
camera extrinsics.

Also, the expanded `CameraManager::CameraManager()`
disassembly gives:

```text
a7120: mov x20,x0            # manager this
a7190: mov x28,x20
a71a4: str xzr,[x28,#0x40]!  # x28=this+0x40
a71bc: sub x23,x28,#0x300  # x23=this-0x2c0
a71ec: str xzr,[x23,#0x330] # this+0x70, init word B?
a71f0: str d8,[x23,#0x338] # this+0x78, init word A?
a72c4: add x21,x21,#1
a72ec: cmp x21,#7
a72f4: add x23,x23,#0x320
a72fc: b.ne 0xa71e0
```

Thus **seven** camera-style blocks are initialized
with stride **0x320**, constructor `this`-relative
candidate `B` addresses
`0x70+0x320*i` and `A` addresses
`0x78+0x320*i` for i=0..6.
The `d8` word originates from `ldr d8,[x8,#0x6b0]`
after `adrp x8,0x73000`, i.e. file-backed
ELF VA **0x736b0**. Its actual bytes are **not
yet known** and must not be interpreted as a
floating-point value or nanosecond correction
until read and traced.

**Crucial discrepancy:** the frame-time expression
at `0xaae88–0xaae94` addresses
`x19+camera_index*0x320+0x330/0x338`,
not `x20+0x70/0x78`. We have NOT yet
established the relation between the **constructor
`x20`** and the **callback `x19`**; therefore
one cannot identify the constructor values
`0` and `d8` with the active runtime
`B/A`, or infer the actual values of
these parameters from matching source-level
numeric offsets alone. The exact recorded
equation `A+2B=173997 ns` is valid for
the **actual values read by the callback**,
which may differ from constructor initializers.

The next offline-only program reads the raw 64-bit
words at ELF VAs 0x736b0, 0x73748 and
0x73738 via an existing validated
`PT_LOAD` mapping, prints their integer
and floating-point *bit interpretations*,
and extracts `CameraManager::onFrameAvailable`
prologue to recover how callback `x19/x26`
are assigned. The code and six new synthetic
checks are here:

```text
pico/tools/audit_k0_constructor_literal.py
pico/tests/test_k0_constructor_literal.py
pico/tools/trace_k0_clock_base.ps1
```

Owner command without Pico or Android devices:

```powershell
cd C:\Dev\PicoLHSync
git pull --ff-only
pwsh -NoProfile -File .\pico\tools\trace_k0_clock_base.ps1
```

The new tool has not been executed yet on the
owner's Windows checkout. It preserves SHA-pinned
read-only analysis, `OBSERVE_ONLY`,
`exact_time=false` and the hardware
exposure/SteamVR gates.


## P2 constructor/runtime pointer reconciliation; **actual A/B initializer location** — 2026-10-17

The owner ran `trace_k0_clock_base.ps1`; **12/12** regression
tests passed. The static read of constructor-related ELF
constants gave:

```text
ELF VA 0x736b0 (d8):  000000001e000000 (NOT a standalone A/B)
ELF VA 0x73748 (d9):  0500000006000000
ELF VA 0x73738 (d10): 3c000000d4060000
```

These are raw bit patterns, **not floating-point measurements**;
the artificial `f64` interpretations are meaningless until
typed use is established. They must not be mistaken for the
K0 `slot+130` adjustment coefficient values.

### Major source-derived finding — follow the *other* constructor q1 store

The new prologue proves the frame callback and constructor use
the **same CameraManager 'this' base**:

```asm
# CameraManager::CameraManager, at 0xa7120
mov x20,x0              // this

# CameraManager::onFrameAvailable, at 0xaa924
mov x19,x0              // this
sxtw x26,w20            // camera id
madd x9,x26,0x320,x19  // this + cameraIndex * 0x320
ldr x10,[x9,#0x330]    // B
ldr x9, [x9,#0x338]    // A
```

Earlier constructor stores at `0xa71ec/f0` are **NOT**
the actual onFrame coefficient fields. They target
`this+0x70/0x78+0x320*i`. The real matching stores
occur **later inside the same seven-iteration constructor**:

```asm
# single 128-bit literal loaded from file-backed VA 0x73170
0xa717c adrp x9,0x73000
0xa7198 ldr q1,[x9,#0x170]
0xa71cc str q1,[sp,#0x30]
# ...each of 7 iterations of stride 0x320:
0xa72e4 ldr q1,[sp,#0x30]
0xa72f0 str q1,[x23,#0x5f0]  // writes 16 contiguous bytes
0xa72f4 add x23,x23,#0x320
0xa72fc b.ne 0xa71e0
```

From the same constructor:

```text
x23 = this - 0x2c0 + cameraIdx * 0x320
therefore x23 + 0x5f0 = this + 0x330 + cameraIdx*0x320
and x23 + 0x5f8 = this + 0x338 + cameraIdx*0x320
```

Thus **the exact two source fields for native slot+130
are initialized from the 16-byte q1 literal at ELF VA
`0x73170..0x7317f`**:

- lower 64-bit word from `VA 0x73170` = `B` initializer;
- upper 64-bit word from `VA 0x73178` = `A` initializer;
- same initialization applied to seven blocks.

This is stronger than merely matching field offsets.
It resolves the constructor/callback base-pointer ambiguity
at the source-code/ABI level. There may **still be runtime
setters** that update A and B after construction, so this
alone is not proof of their live immutable values.

The original 1204-frame data establish
`slot122 - slot130 = 225997ns` for E=4 on every
accepted frame. Source-level arithmetic predicts
`52000 + A + ((B*4) ASR 1)`. The remaining
straightforward **offline** test is to read the 16 raw
bytes at **0x73170**, decode both words as signed
64-bit values, and compare predicted vs observed.
Do not claim any numeric individual A/B value until
those bytes have been inspected.

New SHA-pinned, fail-closed `pico/tools/audit_k0_q1_coefficients.py`
performs the exact comparison, including ARM64 signed
64-bit wrap arithmetic. Nine synthetic math/offset
tests are provided in `pico/tests/test_k0_q1_coefficients.py`.
Wrapper `pico/tools/verify_k0_q1_coefficients.ps1`
runs those nine plus six earlier constructor tests
before reading the local saved service ELF and writing
the result to `p2-q1-timing-coefficients.json`:

```powershell
cd C:\Dev\PicoLHSync
git pull --ff-only
pwsh -NoProfile -File .\pico\tools\verify_k0_q1_coefficients.ps1
```

**This new analysis was not yet executed on the owner's Windows.**
No Pico, ADB, QuickCamera service calls, tracker, calibration,
`exact_time`, or SteamVR pose modifications involved. All
physical exposure and QTIMER producer-origin verification gates
remain CLOSED, irrespective of numerical agreement.


## 2026-10-17: actual constructor initializer differs from captured K0 — 15/15 tests pass

Owner ran `verify_k0_q1_coefficients.ps1` after updating to `c7419b5`.
**All 15 synthetic tests passed**, both original constructor layout
and the ARM64 arithmetic test suite. The exact SHA-pinned ELF bytes
at VA `0x73170..0x7317f` were:

```text
7d4a0000000000006b09020000000000
B = 19069 (signed 64-bit)
A = 133483 (signed 64-bit)
E = 4 (accepted K0 frame code)
fixed subtraction = 52000ns
predicted initial adjustment = 52000 + 133483 + ((19069*4) ASR 1)
                             = 223621ns
recorded for 1204 K0 frames = 225997ns
difference = +2376ns
```

Therefore, **the initial firmware constant pair does not predict
the recorded +130 correction**. The observed constraint is
`A_runtime + 2*B_runtime = 173997ns`, while the
constructor initializes `A_init + 2*B_init = 171621ns`.
Consequently, assuming the exact same source formula and
`E=4`, the *effective* coefficient difference obeys:

```text
delta_A + 2*delta_B = 2376ns
```

Possible causes include a post-constructor coefficient update,
alternate initialization path/profile, or an unseen frame-metadata
flow. **Not proven**: that A specifically changed by +2376,
that B specifically changed by +1188, that the runtime A/B can be
read safely, or that +130 is the physical exposure midpoint.
Our earlier conditional inference "initial q1 explains all K0
timing" is definitively **falsified** by this paired owner run.

Next diagnostic target is source-level *writes* to the two
`CameraManager` fields `this+camera_index*0x320+
0x330/0x338`, including stores reached via register aliases,
vector stores, memcpy and configuration reload. Numeric agreement
must not be forced by silently altering the fixed `52000`
value or promoting `exact_time`. The existing 1,204-frame
capture and hash-pinned firmware remain sufficient for static
analysis while Pico is powered off.

Gate status: `constructor_A_B_read=PROVEN`,
`A_B_effective_runtime_values=UNVERIFIED`,
`QuickCamera_active_K0_listener=UNVERIFIED`,
`QTIMER_optical_event=UNVERIFIED`,
`physical_exposure=UNVERIFIED`,
`SteamVR_clock_alignment=UNVERIFIED`,
`live_lighthouse_correction_allowed=false`.


## 2026-10-17: exact-match adjacent ROM pair discovered (15/15 PASS)

The owner ran `scan_k0_alternate_constants.ps1` successfully
after pulling `28453d2`. **All 15 synthetic tests PASS**.
The SHA-pinned service ELF search examined **one readable-only,
non-writable, non-executable, file-backed PT_LOAD segment**,
with one aligned literal pair predicting the observed K0
correction:

```text
ELF VA        B       A      fixed+2*B+A  vs K0 observed
0x73170     19069  133483     223621 ns  -2376 ns  [constructor q1]
0x73160     19333  135331     225997 ns       0 ns  [new ROM candidate]
difference   +264   +1848      +2376 ns
```

This is an unusually strong *static* alternative timing
profile candidate: the two 16-byte pairs are adjacent,
and `0x73160` mathematically reproduces the **exact**
225997-ns subtraction seen on **all 1,204 accepted K0
frames**, with \(E=4\). But there is a critical distinction:

- VERIFIED: the exact two ROM pairs exist and one matches
  the real measured timestamp adjustment.
- VERIFIED: the constructor's particular `ldr q1` at
  `0xa7198` reads **0x73170**, not 0x73160.
- **UNVERIFIED**: code actually references 0x73160, and
  whether that code selects an active sensor profile,
  overwrites A/B later, or represents a different
  structure entirely. Numerical agreement alone does
  not prove any runtime selection.
- Still UNVERIFIED: the QTIMER hardware event, optical
  shutter/exposure meaning, and SteamVR pose clock
  alignment. The 2.376-us discrepancy is secondary to
  larger unknown physical time offsets.

One final focused offline test has been added:
`pico/tools/audit_k0_literal_references.py` searches the
**complete disassembly of the same SHA-pinned service
ELF** for candidate AArch64 `ADRP` + indexed loads
from VA 0x73160 and 0x73170, with register invalidation
for detected clobbers/calls; it records owner functions
and surrounding instructions without assuming that a
matched instruction was executed at runtime. `0x73170`
is a positive control from the verified constructor.
`pico/tests/test_k0_literal_references.py` has **seven**
synthetic regression cases; the wrapper
`pico/tools/trace_k0_literal_references.ps1` runs
those seven plus the existing six static-literal tests
(**13 expected**) and saves a detailed private JSON
report of every candidate reference.

```powershell
cd C:\Dev\PicoLHSync
git pull --ff-only
pwsh -NoProfile -File .\pico\tools\trace_k0_literal_references.ps1
```

If no reference is found, the tool does not prove the
literal unused: alternate address-generation patterns,
jumping into the middle of a literal region, inlined
copies, or other code paths may evade this conservative
scanner. **No HMD needed; OBSERVE ONLY; exact_time=false.**
