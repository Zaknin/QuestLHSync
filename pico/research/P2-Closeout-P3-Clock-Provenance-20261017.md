# PicoLHSync: P2 native K0 timing closeout and P3 proof gates

Date: 2026-10-17. Scope: Pico 4 Pro, PICO OS 5.11.2, QuestLHSync
`feature/pico-support`. **OBSERVE ONLY. No live timestamp modification.**

## Executive decision

The available K0 clock ring and two SHA-256-pinned native service/camera
ELFs have been analyzed sufficiently to identify the dataflow, the
computed slot+130 expression, and source-level parameters. Stop spending
serial tests on the **2,376 ns** difference between constructor defaults
and the observed 12-second recording. That discrepancy is documented,
not resolved to a concrete runtime assignment.

The actual integration blocker is **which physical camera event and
clock source QuickCamera's first `FrameMetaDate` timestamp represents**,
followed by calibration to the **host monotonic/SteamVR pose timeline**.
None of those questions can be answered from a second metadata field or
from numerical equality alone.

## Evidence established

| Item | Observation | Evidence level |
|---|---|---|
| Active K0 IDs | 0,3,4,5, 301 stable samples each, 1204 total | Private owner capture |
| Listener routing | callback byte 0,1,2,3 -> manager camera 0,3,4,5; ELF switch bytes 00 07 0a 0d | Static ABI and 4-byte ELF data |
| QuickCamera metadata to frame | first FrameMetaDate 64-bit word duplicated into frame_item+0x18/+0x20 | Native code |
| Main kind-0 K0 ring | copies frame_item+0x18/+0x20/+0x28 to slot+114/+122/+130 | Native writer code |
| +130 calculation | `T130=T122-52000-A-((B*E) ASR 1)` | Native ARM64 code |
| E on accepted frames | `E=4`, from frame_item+0x14 and K0 slot+110 | Code plus accepted sample criteria |
| +130 delta | `T122-T130=225997 ns` every one of 1204 frames | Private owner capture |
| Constructor coefficient default | B=19069 A=133483 from VA 0x73170; predicts 223621 ns | ELF code and literal |
| ConfigManager alternative pair | B=19333 A=135331 from VA 0x73160; predicts 225997 ns | ELF code and literal |
| Alternative pair storage | ConfigManager+0xA0 via stp q1,q2 at 0xa24e8 and 0xa2628 | Native code |
| Config -> camera transfer | **Not located / unverified** | No source proof |
| Hardware clock | PVR dumpsys QTIMER tracks CNTVCT_EL0 ~19.2 MHz; first K0 stamp QTIMER-like | Independent clock checks, not provenance proof |
| Physical exposure instant | Unknown, including scanline and shutter phase | **BLOCKED** |
| Pico timestamp to SteamVR pose time | Unknown: no simultaneous validated cross-host mapping | **BLOCKED** |
| Actual runtime listener ownership | Static ABI/IDs match; exact active instance binding not proven | **BLOCKED** |

The native `ConfigManager` result is *not* a certificate that the
0x73160 pair is active: the constructor of `CameraManager` separately
loads 0x73170. Repeated inspection of these four code windows is no
longer the priority without a new concrete cross-reference.

## P3 plan, prioritized by missing proof

### Gate P3-A: identify true first camera timestamp producer

* **Existing offline evidence:** `libpvrtrackingcamera.so` invokes
  `QuickCameraClient::DeQueueFrame(void**, FrameMetaDate*)`.
  Its first 64-bit metadata word becomes K0 +114/+122. A different
  AImageReader path also exists, without proof it supplies these
  active K0 rings.
* **Missing upstream evidence:** implementation of QuickCamera/HIDL
  producer and any metadata conversions before `DeQueueFrame`.
  The camera ELF has dependencies on the PICO QuickCamera HIDL
  common/module/device components. Their *exact installed paths* must
  be discovered from the device or an already archived matching
  firmware image; do not guess the paths or conflate .so versions.
* **Required outcome:** source-level (or controlled independent
  measurement) identity of the 64-bit clock; units, epoch, rate,
  wrap/sleep behavior, camera ordering, origin hardware event, and
  whether a timestamp denotes SOF, start/end of readout, exposure
  start, midpoint or another event.
* **Constraint:** when PICO is next available, read-only inventories
  and copies of relevant vendor modules only; do not patch/install
  vendor services or alter SLAM, calibration or camera settings.

### Gate P3-B: establish a host/SteamVR timeline

This can be engineered **on Windows with Pimax Crystal** while Pico
is powered off, but can only validate host-side collection semantics,
not the missing headset-to-host mapping.

* Timestamp every host sample with `QueryPerformanceCounter` and
  `QueryPerformanceFrequency` on the same PC. Preserve raw integer
  ticks and sample bracketing (before/after each API call).
* Read OpenVR pose state using existing official API, e.g.
  `IVRSystem::GetDeviceToAbsoluteTrackingPose(origin, 0.0, ...)`
  and record both flags (`bPoseIsValid`,
  `bDeviceIsConnected`), origin, requested prediction seconds,
  call-time QPC brackets and returned matrix.
* **Important limitation:** prediction `0` asks for a pose at
  **call time** according to the OpenVR API; it is **not** a raw sensor
  sampling time or a guaranteed QPC timestamp for the returned pose.
  Do not substitute `WaitGetPoses` frame-vsync timing for a
  hardware image event. Never inject or replace poses during testing.
* Once PICO returns, produce an independently bounded
  cross-machine clock offset/rate estimate, and bound asymmetric
  transport latency rather than treating a single two-way ping
  midpoint as truth. Repeat over restart/sleep and tracking sessions.

Official API references:
- https://github.com/ValveSoftware/openvr/wiki/IVRSystem%3A%3AGetDeviceToAbsoluteTrackingPose
- https://github.com/ValveSoftware/openvr/wiki/IVRSystem%3A%3AGetTimeSinceLastVsync
- https://github.com/ValveSoftware/openvr/wiki/Compositor_FrameTiming

### Gate P3-C: optical event and geometry

* Source provenance alone is insufficient for exact Lighthouse
  timing. Use an independent observable optical timing marker or
  equivalent controlled method to establish the frame event,
  scanline/rolling-shutter term and hardware pose lag.
* Map each K0 camera ID to its physical orientation, intrinsics and
  extrinsics, with enough controls to exclude IR reflections and
  misassigned emitters. Previously reconstructed lighthouse spots
  alone do not verify calibration or exposure phase.
* Apply only independently measured bounded transformations in an
  isolated shadow replay, then rerun motion/pose diagnostics across
  separate sessions and bases before considering any live change.

## Safety and deployment conditions

- No assumption that `slot+130` is exposure-center. The subtraction
  is real; its optical semantics are not.
- No assumption that a persistent 4.7465-second QTIMER/BOOTTIME
  offset can be used on a later boot or headset.
- No source-only timestamp adjustment in normal `PFR1` F records.
- No tracker/SLAM/SteamVR calibration, service modification or
  firmware updates for provenance investigation.
- Never check private ELF binaries, timestamp CSVs or device-specific
  tracking dumps into Git.
- Preserve `exact_time=false`,
  `live_lighthouse_correction_allowed=false`, and
  P2/P3 `OBSERVE ONLY` until source, time-domain, optical,
  PC-clock, and validation gates are independently satisfied.

## Immediate disposition (Pico powered off)

Record P2 in the project log. Host-only OpenVR/QPC research can
proceed without Pico but does **not** by itself prove camera timing.
Do **not** ask for another identical K0 sample or another
constructor-literal run. The next device-dependent operation is
the minimal, read-only inventory/copy of the missing producer
modules **when the owner chooses to power on Pico again**.
