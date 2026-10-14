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
