# Pico 4 Pro support — P1 experimental backend

Part of [QuestLHSync](https://github.com/CreoleVR/QuestLHSync), proposed for [#15](https://github.com/CreoleVR/QuestLHSync/issues/15).

**Status: P1 development source, not a usable tracking-correction release.** Only Pico 4 Pro on Pico OS 5.11.2 / Android 10 with root has been investigated. No claim is made for Pico Neo 3, Pico 4 or other firmware. This backend is intended to be upstreamed, not maintained as a separate application.

## Reuse rather than rewrite

- `src/headset/lhsyncd.c`: original QuestLHSync discovery (UDP 47281), TCP stream (47280), P/Q clock sync and capture lifetime. No modified copy.
- `magisk/src/lhsight.c`: original `smean()` and `blobs()` (saturated and dim spot detection) compiled directly into the Pico processor. No second implementation of the spot detector.
- Pico-specific: `PicoFrameReader.java` uses the **validated read-only Binder/SharedMemory API**; `lhsight_pico.c` reads its binary frames and emits original `F` and `T` records; `pico.c` implements `src/headset/headset.h` and starts the reader only on PC connection.
- No changes to Pico SLAM, no camera configuration writes, no Frida injection, no forced wake locks, no full-frame Wi-Fi streaming.

## Hardware contract: tested Pico 4 Pro only

| Camera ID | Sensor position | Sensor index | Stream |
| --- | --- | --- | --- |
| 0 | upper-left | 0 | K0 |
| 3 | upper-right | 1 | K0 |
| 4 | lower-left | 2 | K0 |
| 5 | lower-right | 3 | K0 |

`pvr.ITrackingService`, transaction 19 `GetCameraShareMemory(cameraId, kind)`; `kind=0`; 640x480 RAW8; header 20 bytes, ring 5 slots of 308026 bytes, pixel start +186, sequence at +146 (odd K0), timestamp candidate +122, exposure-like metadata +110 = 4. Only IDs 0,3,4,5 are ever requested; never request ID >= 7 because the firmware's bounds checking is unsafe. Each camera K0 is ~25 fps. The reader skips the newest potentially in-flight slot and checks metadata before and after copying from a previous slot; this does not guarantee pixel atomicity.

## Build (Windows)

From repo root:

```powershell
python .\pico\build_module.py
```

Requires JDK `javac`/`jar`, Android SDK platform `android.jar`, build-tools `d8`, Android NDK (`ANDROID_NDK_HOME` or SDK ndk). The build outputs `out/QuestLHSync-pico-module-<upstream-version>-p1.zip`. Compile/installation on Pico must be tested independently. Do **not** install the Quest module alongside the Pico module on the same headset: both use the same TCP/UDP ports.

## Protocol and testing

`PicoFrameReader` communicates with its local native detector over stdout using the internal binary `PFR1` format (40-byte big-endian header + 307200 RAW8 pixels). Native `pico_lhsight` emits the upstream network records:

```text
F <cam> <seq> <headset_monotonic_us> <mean_times_10> <nblobs> [<x10> <y10> <npx> <peak>]...
T <headset_monotonic_us> scans <n> scan_us <n> drops 0 faults 0 polls <n>
```

`lhsyncd` runs on demand when a TCP client is connected, and stops the camera processor after disconnecting. The shared daemon handles UDP discovery and P/Q clock sync. While P2 calibration is not implemented, **`hs_calibration` intentionally returns an error**; the upstream SteamVR driver will not ingest `F` sightings without valid optics. P1 records can still be examined directly via the TCP transport test client after the `H` and `E` lines. Keep SteamVR tracking corrections disabled during P1 testing. On Windows: `python pico/test_stream.py <PICO_WIFI_IP> --seconds 12` (while the headset tracking cameras are active).

## Next upstream blockers before live correction

1. Load real `/.../sensor.yaml` Pico factory omni/radtan camera intrinsics and `T_BS` extrinsics, prove camera image axes and HMD pose-space mapping; add `kind:pico` optics in `src/driver/sync.cpp` (never invent geometry).
2. Validate vendor timestamp candidate `slot+122` against `CLOCK_MONOTONIC`; currently `F` uses **copy time**. It is useful for transport/detection, not precise enough for headset motion compensation. Adapt `FrameGrid` for K0 25 Hz.
3. Recognize Pico streamed HMD (e.g. PICO Connect/Virtual Desktop/ALVR) in `src/driver/net.cpp`, `driver_main.cpp`, without enabling corrections for a wired or mismatched HMD.
4. Validate on-device CPU cost, room-light thresholds (Pico initial floor = 16), frame tearing, reconnect/sleep, calibration fit, and tracking accuracy with an actual lighthouse tracker.

For now use the existing `PicoLHProbe` and raw K0 recordings as independent ground truth. Bluetooth serial-to-location guesses are not required by the upstream solver.

## P1 on-device verification — 2026-10-14

Validated on a **rooted Pico 4 Pro (Pico OS 5.11.2 / Android 10)** with the headset's SLAM tracking kept awake for this development-only test. The binaries were compiled on Windows with Android NDK r27c (target API 29), javac and d8; launched from /data/local/tmp without installing a Magisk module. The original `lhsyncd` listened over the Pico's Wi-Fi (TCP 47280), and the independent `pico/test_stream.py` client received:

| Camera | F frames / 20 s | Detected blobs across frames |
| --- | ---: | ---: |
| C0 | 493 | 403 |
| C3 | 492 | 1110 |
| C4 | 492 | 75 |
| C5 | 492 | 103 |
| **Total** | **1969** | **1691** |

Also received 20 `T` heartbeats. The earlier 12-second check with base stations off observed 1178 frames and zero detected blobs; the headset was subsequently moved to its usual VR seating position, so the two tests do **not** constitute a controlled off/on comparison at a fixed viewpoint. `Spots` are raw optical blobs, not confirmed Lighthouse-station identifications. The test deliberately reports `E Pico factory omni/radtan calibration adapter not implemented (P2)` and does not enable SteamVR pose corrections. No USB was used to transport the observations; USB/ADB remained available for development.

**P1 acceptance:** real Pico camera K0 acquisition, native blob processing and original upstream network transport validated at approximately 25 frames/s per camera. **Next:** calibrated optics, trustworthy frame exposure timestamps and HMD/streamer compatibility (P2+).

## P2 optics progress — 2026-10-14

A private 13-file factory calibration archive from a Pico 4 Pro on Pico OS 5.11.2 was inspected locally; **neither the archive nor the headset-specific calibration coefficients are in this repository**.

- Exactly factory cam0..cam3 use the 640x480 Omni + Radtan model corresponding to K0. cam4 is 2328x1748 with fisheye62; cam5/cam6 and cam7 are 400x400 and not part of K0.
- All four tracking-camera T_BS rotations are proper rigid rotations. T_BS means **body <- camera**; it is not the unverified SteamVR **HMD <- camera** transform.
- Proposed position-based Binder mapping: C0->cam0, C3->cam1, C4->cam3, C5->cam2. It is not verified against vendor camera-ID metadata.
- Reusable mathematical implementation in pico/src/omni_radtan.h; parameterized C++ smoke test in pico/tests/omni_test.cpp. Numerical roundtrip tests using all four private factory calibrations gave 1187-1192 valid points out of 1200 grid points each, with maximum error about 1.1e-9 pixels for valid points. Edge points outside inverse domain are rejected.
- Optics::LoadPico() is wired into the original solver but deliberately **fails closed** unless mapping_verified=true and pose_verified=true, plus a valid row-major 4x4 HeadFromBody rigid transform.
- Pico learns the approx. 40 ms camera period instead of using Quest's 37.5/45 Hz period hypotheses.
- P1 hs_calibration() still sends an error: this build does not enable Pico live tracking corrections.

Generate a **private, NOT solver-ready** draft on Windows with:

    python .\pico\tools\prepare_calibration.py .\pico-calibration.tar

Output out/pico-calibration-DRAFT.json is gitignored. It sets mapping_verified=false, pose_verified=false and HeadFromBody=null. Do not flip these flags or invent a transform to make the driver accept it.

**Remaining P2 validation:** establish actual Binder-to-factory camera IDs from vendor metadata, measure headset body-to-SteamVR-pose transform for the intended streamer and validate K0 sensor timestamp clock domain against CLOCK_MONOTONIC. The Wi-Fi P1 test remains unaffected.

### P2 optional vendor timestamp diagnostic

After rebuilding and deploying the development-only `pico_lhsight` executable, start `lhsyncd` with `PICO_TIMESTAMP_DIAG=1` in its environment. This is inherited by the camera-reader child. It emits an `I pico_ts ...` record approximately every five seconds per camera, with the raw vendor timestamp (`slot+122`), Android `System.nanoTime()` at copy, and mean successive clock steps in their respective units. The existing `F` timestamps **remain copy-time**; no change to normal capture or correction is enabled. The Wi-Fi smoke test (`python pico/test_stream.py <PICO_IP> --seconds 20`) prints diagnostic `I` lines. The clock source, unit, epoch, lag and image-exposure alignment must be established from these observations before using the vendor value for synchronization. Do not make this diagnostic part of a default production service configuration.

### P2 BOOTTIME vs MONOTONIC check (2026-10-14)

A running four-camera P1 stream yielded a nearly identical vendor K0 timestamp on all four cameras, with raw successive steps **39,999,885–39,999,886** and copied-Android-`System.nanoTime()` steps about **40,000,000 ns**. The vendor timestamp was approximately **142.844 seconds ahead** of `System.nanoTime()` across the 20-second recording. This suggests, but **does not prove**, that slot+122 is in the Android `CLOCK_BOOTTIME` domain while `System.nanoTime()` uses `CLOCK_MONOTONIC` (the accumulated suspend interval would account for the large offset).

Use the separate **read-only** Java clock probe to test the hypothesis; do not connect a TCP camera client simultaneously:

    CLASSPATH=/data/local/tmp/qlhs-pico-p1/PicoFrameReader.jar /system/bin/app_process /system/bin PicoFrameReader --clock

The `--clock` command samples the last completed slot of K0 C0 12 times and compares the candidate vendor value against `SystemClock.elapsedRealtimeNanos()` (BOOTTIME) and `System.nanoTime()` (MONOTONIC). The main binary-stream mode is untouched. In particular **F is still copy-time, not vendor-time** until clock domain, frame age and exposure semantics are validated.
