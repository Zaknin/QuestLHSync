# Pico 4 Pro P2: community research on Qualcomm QTIMER and Camera2 timestamps

Date: 2026-10-16. Research only; no live correction authorized.

## Executive finding

A public, exact **Pico 4 Pro + 4.746-second** bug report was not located.
However, public evidence strongly supports the general failure mode
"hardware QTIMER camera timestamp exposed without correct BOOTTIME
translation" as an actionable **hypothesis**:

1. [Qualcomm downstream Android kernel camera CSID implementation](https://android.googlesource.com/kernel/msm.git/+/0bdc64f155814eb6a109d0ec9e3965c821da5853/drivers/media/platform/msm/camera/cam_isp/isp_hw_mgr/isp_hw/ife_csid_hw/cam_ife_csid_core.c)
   reads a hardware start-of-frame timestamp (QTIMER), converts 19.2 MHz
   counter ticks into nanoseconds, and separately computes a
   `boot_timestamp` from `get_monotonic_boottime64()` plus successive
   QTIMER differences. This establishes an actual dual-timebase
   implementation in Qualcomm camera infrastructure. **It is not proof
   of the exact Pico firmware implementation.**
2. [A Qualcomm camera HAL source revision](https://android.googlesource.com/platform/hardware/qcom/camera/+/3d63919a23d7e7954e160c48c36713267106c3c2/msmcobalt/QCamera2/HAL/QCamera2HWI.cpp)
   defines `persist.camera.time.monotonic`, computes
   `mBootToMonoTimestampOffset` and explicitly describes ISP
   BOOTTIME vs display MONOTONIC clocks. This demonstrates that
   conversion errors are a recognized Qualcomm driver integration
   concern, although this is **not the same offset** as QTIMER.
3. [Qualcomm HAL3 source](https://android.googlesource.com/platform/hardware/qcom/camera/+/ada4b90c896689174c3f1929c833c0574fb0491d/msm8998/QCamera2/HAL3/QCamera3HWI.cpp)
   separately uses `capture_time` and `capture_time_av` / private
   display metadata. Distinct frame-related timestamps do exist
   in the same capture pipeline; no claim this is deployed on Pico.
4. [An Android developer Q&A, 2019](https://stackoverflow.com/questions/56624245/how-to-convert-between-android-camera-timestamp-and-system-time/57511693)
   discusses REALTIME vs BOOTTIME and includes a comment from a user
   who says REALTIME timestamps still differ from CLOCK_BOOTTIME. The
   answer explains the intended clocks; the comment is anecdotal and
   **contains no independently verified solution or matching 4.746s
   magnitude**.
5. [Android camera metadata contract](https://developer.android.com/ndk/reference/group/camera)
   stipulates REALTIME capture timestamps are comparable to
   `SystemClock.elapsedRealtimeNanos()` (Linux BOOTTIME), and refers
   to the exposure start; `AImage_getTimestamp` returns timestamp
   from its image source rather than independently calibrating it.
   [NDK AImage implementation](https://fuchsia.googlesource.com/third_party/android/platform/frameworks/av/+/refs/tags/aml_wif_341610000/media/ndk/NdkImage.cpp)
   forwards to `image->getTimestamp`. Therefore a 4.746s QTIMER
   offset must be traced upstream of that call if it exists.
6. [PICO 4 reverse-engineering documentation](https://github.com/thoricelli/PICO-documentation/tree/main/system_libs/FT%26ET)
   explicitly identifies physical CameraService ID 5 (400x1600) as
   the eye-and-face tracking camera path (three OV6211 IR units
   combined by OV680). This independently resolves the apparently
   extra public Camera2 ID 5 on this PICO 4 Pro.
   [PICO services inventory](https://github.com/thoricelli/PICO-documentation/blob/main/services/README.md)
   documents the `pvrtracking` binder and separate
   `pxreyetrackingservice` binder.
7. [Official Android Camera ITS tests](https://source.android.com/docs/compatibility/cts/camera-its-tests)
   include `test_unified_timestamp` and `test_sensor_fusion`,
   testing camera–IMU timestamp coherence, with a ±1ms offset
   target for the high-fidelity sensor fusion test. **Not yet run on
   the private QuickCamera stream**, and do not interrupt SLAM to
   run a competing capture session.

## Owner's instrumented evidence

2026-10-16 12-second in-session read-only PVR/K0 sample:
PVR QTIMER-BOOTTIME +4746.502697ms before,
+4746.502545ms after (delta -0.000152ms); 301 K0 frames
each on C0/C3/C4/C5. If the K0 AImage timestamp is QTIMER,
its apparent time before producer BOOTTIME write-lock:
C0 9.823046ms; C3 10.063775ms; C4 9.960862ms; C5 10.234506ms.

Real firmware SHA-pinned static call sites confirmed by local llvm-objdump:
- `libpvrtrackingcamera.so` at 0x3a8bc calls
  `AImage_getTimestamp@plt`; 0x3a8d8 calls `systemTime@plt`.
- `libpvrtrackingcamera.so` camera processFrame at 0x3c710
  also calls `systemTime`.
- `libpvrtrackingservice.so` exports
  `SnsLowLatBridge::qtimer_get_time_ns()` at 0x96d90 and
  `pxr::TimeSynchronization::sensorToSystemTime(double,double)`
  at 0xf9b0c. Their association with **camera** timestamps is
  NOT established; they may concern the IMU/SLPI path.
- Previous static chain passes `AImage_getTimestamp` to
  `pvr_frame_item_t+0x18` then ring `slot+114`;
  `slot+122` matched in archived frames. Native `AImage_getTimestamp`
  is a transport accessor, **not a clock source generator**.

## Decisive next offline inspection (zero new headset capture)

Use the already copied and hash-verified firmware ELF files in the
owner's private `pico/build/p2-static-clock-private-20261016-205431`.
Inspect instructions around `0x3a8bc` and `0x3a8d8`, especially
`x0` (clock selector) at `systemTime`; follow whether that return
value is stored to `pvr_frame_item_t+0x20` (ring +122) or used for
another independent timing field. The old +114/+122 equality is a
*measured fact*, not a proof that every field or callback is sourced
identically in all conditions.

Separately inspect call sites or XREFs involving
`qtimer_get_time_ns` at 0x96d90 and
`sensorToSystemTime` at 0xf9b0c, **without assuming either function
is used by the camera**.

If `AImage_getTimestamp` is simply delivered upstream unchanged,
the authoritative timestamp producer is the lower HAL/CameraService
or QuickCamera buffer-producer path. Determine which path supplies
the 4 tracking sensors. Do not alter PFR1 frames or tracking unless
QTIMER source, conversion behavior, real exposure instant and
PC pose timebase have independent evidence.

## Safety / disclosure

OBSERVE ONLY, all mapping/pose/exposure/PC-timebase validation flags
false. Do not publish raw/private logs, proprietary binaries, factory
intrinsics/extrinsics, or hardware identifiers to public GitHub.
Public source links here are **contextual examples** and not a
substitution for the firmware SHA-verified implementation.
