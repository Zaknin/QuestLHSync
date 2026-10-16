# Quest Pro vs Pico 4 Pro: clock provenance and LHSync timing paths

Date: 2026-10-16. Source review: upstream `CreoleVR/QuestLHSync`
at master as inspected this date and own `feature/pico-support`.
This is **source-level comparison**, not a new measurement on a Quest Pro.

## Direct answer

The original **Quest Pro** path does *not* forward a verified physical
exposure timestamp through QuestLHSync. It polls already shared tracking
camera buffers in the Meta sensors HAL (Frida CModule) and reports the
**CLOCK_MONOTONIC time when a changed buffer was discovered**. The
original solver then estimates its **poll delay** by fitting the frame
phase/grid. The Quest Pro's *underlying camera HAL* may internally use
QTIMER, but the LHSync code does not expose such a raw value, and
the static source alone cannot establish how Meta implements it.

## Exact upstream source chain

1. `magisk/src/lhsight.c`:
   `now()` calls `clock_gettime(1,...)`, i.e. Linux
   `CLOCK_MONOTONIC`; `poll()` detects buffer changes, and after
   stability check invokes `frame(i, now())`. The output
   `F cam k t_us mean ...` uses `t/1000` from the detection time,
   **not an AImage_getTimestamp** or a known SOF time.
   https://github.com/CreoleVR/QuestLHSync/blob/master/magisk/src/lhsight.c
2. `src/headset/lhsyncd.c`: headset's `Q seq pc_ns mono_ns`
   response captures `clock_gettime(CLOCK_MONOTONIC)` during
   `P seq pc_ns` requests. Upstream driver `Clock::AddPing`
   maps this to PC QPC time using RTT midpoint and lowest RTT samples.
   https://github.com/CreoleVR/QuestLHSync/blob/master/src/headset/lhsyncd.c
3. `src/driver/sync.cpp`:
   `FrameGrid::Lag(cam, hs, lag)` estimates poll lag for Quest;
   `Sync::OnLine` computes headset frame grid
   `hg = hs - lag`, maps it to PC QPC `grid_pc`, and then uses
   `t = grid_pc - expo_ - ...` to select HMD pose.
   `expo_` starts at `kExpoDefault=0.018` seconds, *then can be
   learned from motion*, accounting for streamer prediction/latency;
   it is **NOT automatically an 18ms physical sensor exposure delay**.
   https://github.com/CreoleVR/QuestLHSync/blob/master/src/driver/sync.cpp
4. `src/driver/driver_main.cpp`:
   SteamVR HMD pose timestamp is
   `QpcNow() + p.poseTimeOffset`. Then `OnHmdPose` builds a PC-side
   history interpolated at the chosen sighting time.
   https://github.com/CreoleVR/QuestLHSync/blob/master/src/driver/driver_main.cpp

**Important alternate upstream paths:**
- Steam Frame (`frame/src/lhsight.c`) receives V4L2 buffer timestamp,
  dynamically distinguishes `MONOTONIC_RAW` versus `MONOTONIC`,
  maps it into `CLOCK_MONOTONIC`, and the PC optics sets
  `exact_time_=true`.
- In recent upstream `src/driver/sync.cpp`, Galaxy XR
  `gxr_sensor` similarly sets `exact_time_=true` because its
  backend converts a QVR sensor BOOTTIME value into daemon
  MONOTONIC. This is a very close **software integration pattern**
  for a potential Pico sensor timestamp conversion, but source
  comparisons are not runtime validation.

## Our fork — existing safe behavior

`pico/src/PicoFrameReader.java` produces a PFR1 header containing:
- vendor `slot+122` image timestamp, likely QTIMER epoch (NOT verified),
- Java `System.nanoTime()` = MONOTONIC at pixel-copy time.

`pico/src/lhsight_pico.c` reads both, but **deliberately sends**
`F cam ... copied_ns/1000`, not the vendor raw timestamp.
This is a conservative poll/copy-time fallback akin to the Quest path
(though the detection and buffering latencies may differ).

`src/driver/sync.cpp::Optics::LoadPico` explicitly sets
`exact_time_=false`; both `mapping_verified` and `pose_verified`
must be true before a real PICO optics profile is accepted.
**Do not set exact_time true or adjust 18ms defaults based solely
on the recent 10ms QTIMER-to-write-buffer consistency.**

## New disassembly evidence from the owner's verified Pico firmware

SHA256 of both analyzed ELFs matched Oct 13 audit. In
`libpvrtrackingcamera.so`, `CameraReader::OnImageCallback`:
- `0x3a8bc` `bl AImage_getTimestamp`, returned timestamp loaded into
  `x22` from `[sp,#8]` at `0x3a8d0`.
- `0x3a8d4` `orr w0, wzr, #4` selects
  `SYSTEM_TIME_BOOTTIME=4`.
- `0x3a8d8` `bl systemTime` returns BOOTTIME in `x0`,
  copied to `x6` at `0x3a8e0`.
- `0x3a8f0` `mov x5,x22`, then
  `0x3a8f4` calls a local helper with image and BOOTTIME
  arguments adjacent, **no arithmetic between these calls**.
  A downstream/earlier transform has not yet been excluded.
- `CameraReader::processFrame` at `0x3c70c-3c710` separately
  calls `systemTime(4)`, also explicit BOOTTIME.
- `libpvrtrackingservice.so` functions at `0x96d88` and `0x96d90`
  read **`CNTVCT_EL0`**; `0x96d5c` reads **`CNTFRQ_EL0`**.
  `qtimer_get_time_ns()` converts ticks to nanoseconds using its
  frequency. This verifies **a native QTIMER clock implementation**
  in the service (potentially for IMU/SLPI). It does **not**
  establish that PVR's Camera2 AImage timestamp comes from it.

## Experiment next: clock-only AArch64 comparator

Two newly opt-in standalone programs/scripts have been added:
- `pico/src/qtimer_counter_probe.c` reads `CNTVCT_EL0`,
  `CNTFRQ_EL0`, and BOOTTIME/MONOTONIC with bracketed POSIX
  clock samples, all in userspace, 8 samples; no Binder, camera
  calls or image capture.
- `pico/tools/capture_qtimer_counter.ps1` compiles and runs this
  between two regular read-only `dumpsys pvrtracking` lines.

Goal: independently compare the *architectural counter as implemented
in firmware* to the PVR dumpsys `qtimer` reading within the same
session. **Even a matching result only identifies the PVR timer; it
does not identify the source or physical instant of K0 AImage
timestamps.**

Failure is diagnostic. Do not deploy a `QTIMER→MONOTONIC` correction
or permit live LHSync before independent camera exposure and SteamVR
pose timebase checks are completed.
