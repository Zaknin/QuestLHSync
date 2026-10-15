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
- Revised recording-supported Binder mapping candidate: C0->cam0, C3->cam1, **C4->cam2, C5->cam3**. The prior placement-based lower-camera guess (C4->cam3, C5->cam2) contradicted measured Lighthouse image reprojections and is superseded. The camera mapping remains **unverified** against vendor metadata and the full tracking alignment is still not accepted.
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

### P2 clock-domain result (BOOTTIME hypothesis revised)

On a real Pico 4 Pro, a read-only `PicoFrameReader --clock` run with 12 samples (250 ms apart) confirmed:

- `SystemClock.elapsedRealtimeNanos()` minus `System.nanoTime()` = **+138.14995 seconds**, nearly constant during the 3-second probe.
- The candidate ring timestamp (`slot+122`) was **4.659–4.692 seconds *ahead* of BOOTTIME** in those samples; it was about **142.833 seconds ahead of MONOTONIC** at the first sample.
- The apparent 4.66–4.69 s interval is a **clock-domain offset**, not evidence of multi-second camera latency. The probe samples a previous completed slot at 250 ms intervals, introducing up to a frame-period phase/age variation.
- Successive ring timestamps on the four cameras differed by ~39,999,885–39,999,886 in raw units per 40 ms K0 frame. This is strong evidence that `slot+122` increments in nanoseconds, but it does **not** establish an absolute epoch or exposure phase.
- Therefore **the candidate timestamp is not directly CLOCK_BOOTTIME nor CLOCK_MONOTONIC**. Do not apply a fixed 4.7-second correction without verifying that it remains stable across longer sessions and suspend/wake.
- Existing P1 networking and `F` time-of-copy remain unchanged. Next: compare `--clock` observations tens of seconds apart, prove stable offset/drift, then measure timestamp relative to newest completed frames at higher sampling rate and independently validate camera frame exposure phase.

## Integration work: Pico 4 Pro streamed HMD

The SteamVR network link now recognizes Pico 4 Pro firmware identity `A8110` (and explicit `PICO 4 Pro`/`Phoenix_ovs`) as **Pico 4 Pro**, distinct from Quest and Steam Frame. This is metadata recognition, not proof of a compatible pose transform. The Windows HMD model/tracking-system properties still need confirmation on the user's chosen streamer.

The Pico headset-side `hs_calibration` also has a deliberately opt-in, read-only transfer path: set `PICO_CALIB_PATH` to an absolute filename to send that JSON as the original QuestLHSync `C` record. Without the variable, Pico keeps emitting the P1 calibration error, unchanged. Files are limited to regular files of 2..131072 bytes, and symlinks are rejected. The source, Magisk ZIP, and Git repository contain **no real factory coefficients**.

**Do not enable `PICO_CALIB_PATH` with the private DRAFT during normal sessions**: the Windows loader will reject it because `mapping_verified` and `pose_verified` are false, and the user's local calibration would be transmitted in plaintext to any TCP client that connects. First establish the exact `HeadFromBody` transform for the actual streamer and verify Binder camera ordering, then validate the solver in read-only recording mode before applying corrections.

**Acceptance still outstanding:** actual Windows SteamVR HMD enumeration with PICO Connect, calibration handshake, valid pixel rays against real base-station positions, a stable frame-to-pose mapping and controlled non-applying solver run.

### Read-only Windows HMD identity checkpoint

For PICO Connect -> SteamVR, validate the actual HMD model and tracking-system names before touching the solver or enabling correction. With SteamVR running on the PC, execute:

    python -m pip install openvr
    python pico/tools/steamvr_hmd_info.py

The helper queries OpenVR properties only. It prints HMD model, tracking-system name, actual tracking system if exposed, render model and manufacturer; it deliberately omits the headset serial number. No driver installation or active tracking modification is needed. This is the first useful end-to-end compatibility check, not an ongoing timestamp investigation.

### PICO Connect integration: 2026-10-14 device proof and next PC test

OpenVR on Windows (PICO Connect wireless, Pico 4 Pro) reports:

- `HMD_INDEX=0`, `TrackingSystemName=pico`, `ActualTrackingSystemName=pico`
- `ModelNumber=PICO 4`, `RenderModelName=generic_hmd`, `ManufacturerName=Pico`
- `RegisteredDeviceType=piconeo3/PICO 4`

The headset's separate rooted Android API reports `ro.product.model=A8110`; the original P1 TCP hello reports `model=A8110`. This is the **same physical Pico 4 Pro**; PICO Connect obscures the Pro model in SteamVR.

Driver `QuestFamily()` now treats the generic OpenVR `PICO 4` as `Pico` family, but `Fits()` requires the network-side headset to specifically identify as `Pico 4 Pro` (A8110), not merely some other Pico headset. `StreamerName(pico)` resolves to `PICO Connect`.

**Safety: force observe-only** for Pico until the physical camera mapping, `HeadFromBody` and exposure time are validated. `driver_main.cpp` still records HMD and base station poses but never rewrites or hides lighthouse device poses on Pico, and gravity/relationship corrections are disabled. Existing non-Pico behavior is unchanged.

To build a locally modified Windows driver, **close SteamVR** (and the running dashboard), install VS 2022 C++ Build Tools if necessary, then run `cmd /c build.bat`. Register **this local build** with `python install.py`, not the official auto-updater installer (which downloads upstream without Pico support). Restart SteamVR with the Pico streaming. Check `%LOCALAPPDATA%/QuestLHSync/questlhsync.log` for `OBSERVE ONLY`, `PICO Connect`, and a connection to the `A8110` headset.

**Expected first integration state:** headset and streaming-HMD recognition succeed; camera frames remain unconsumed by the PC solver until we supply and validate real calibration. Do not interpret zero solver sightings as broken cameras; the separate `pico/test_stream.py` already validated their read-only Wi-Fi F records. Do not install the experimental Pico Magisk ZIP yet.

### Offline recording for camera mapping (OBSERVE ONLY)

**Goal:** collect evidence to determine real camera-to-factory mapping and HeadFromBody for PICO Connect without feeding unverified calibration to live solver and without modifying tracker poses.

- A driver with uncalibrated Pico camera data normally ignores `F`. While **Record session** is active, it now stores those in the existing session recording as `U F ...`, not `F ...` (so old solver ingest still does not treat them as calibrated). `Sync::OnHmdPose` separately records the usual `P 0 ...` poses.
- Once a second, the driver now writes `S <station-serial> <channel> <x> <y> <z> <qw> <qx> <qy> <qz>` for valid SteamVR lighthouse station poses in the raw lighthouse frame. These are record-only, not used to realign.
- To acquire: close SteamVR, `git pull --ff-only`, `cmd /c build.bat`, then start PICO Connect and SteamVR. The local build stays registered after `python install.py`. Check the log for `PICO Connect: OBSERVE ONLY` and `A8110 ... connected`. Switch on Lighthouse tracked devices so station poses are available.
- In the QuestLHSync dashboard click **Record session**, slowly face each of the base stations from several positions in the play space while changing HMD orientation and translation for 60-90 seconds (avoid moving the mounted base stations), then click **Record session** again to flush and close.
- The file is under `%LOCALAPPDATA%\\QuestLHSync\\recordings\\qlhs-*.txt`; run `python pico/tools/check_capture.py <path>` to verify it contains `U F`, `P 0`, and `S` observations. It is device-specific and not published in the GitHub repo.
- This is a **data-capture milestone, not a solved calibration**. A camera-station correspondence, rigorous solve and reprojection validation are still required. `mapping_verified` and `pose_verified` must remain false until that is done.


### P2 first offline geometry analysis — 2026-10-15

A private 77.8 s recording was analyzed **offline** against device-specific factory Omni/Radtan intrinsics and four SteamVR lighthouse station poses; no factory data or session positions were published. It contained 7,780 frames (1,945 from each camera), 11,535 optical blob candidates, 5,395 HMD poses and four station identities. It was *not* a live tracking correction test.

Key finding: fitting an approximate body->head frame rotation and a 4-DOF lighthouse-to-PICO alignment produced simultaneous optical reprojection matches on all four Binder cameras only after swapping the proposed lower camera assignments:

| Binder ID | Prior draft | Recording-supported candidate |
| --- | --- | --- |
| C0 | cam0 | cam0 |
| C3 | cam1 | cam1 |
| C4 | cam3 | **cam2** |
| C5 | cam2 | **cam3** |

On a 1-in-12 frame subsample and a candidate joint 10-parameter rigid fit, the **same world/head pose hypothesis** gave 0 matches within 15px on C4/C5 with the prior mapping, versus 28+28 matches with the swapped mapping; upper cameras each retained matches. This model currently produces usable matches chiefly for two of the four lighthouse stations. Median matched residuals of about 7–9px are **far too large to claim tracking-grade calibration** and include possible false positives (the spot detector has no station-ID label). These counts are model-dependent correspondences, not ground truth.

`pico/tools/prepare_calibration.py` now generates C0->cam0, C3->cam1, C4->cam2, C5->cam3, still with `mapping_verified=false`, `pose_verified=false`, `HeadFromBody=null` by default. DO NOT set flags or enable actual pose corrections until independent station association, reprojection error and pose mapping are validated.

### One-at-a-time base station power-toggle markers (manual ENTER)

A **read-only, human-assisted** power-toggle study can label which Lighthouse spots belong to which station. Use `pico/tools/mark_station_switches.ps1` with PowerShell 7+; it **does not** switch power itself and does not enable Pico tracking corrections.

1. Wear the Pico with PICO Connect/SteamVR running, start **Record session** in QuestLHSync and leave all four stations ON.
2. In a separate PowerShell 7 terminal, run: `pwsh -NoProfile -ExecutionPolicy Bypass -File .\pico\tools\mark_station_switches.ps1`.
3. For each station (channels 1, 7, 10, 13), look towards it; physically turn **OFF** that station then immediately press Enter; wait for the script; physically turn it **ON**, press Enter; let the script wait for spin-up. Leave the other three stations running at all times.
4. Stop **Record session** when prompted. The script writes a sibling `qlhs-...-switches-....csv` file with action/channel/serial and the ENTER instant in `QpcNs`; the main QuestLHSync recording uses the same Windows QPC timebase as nanoseconds in its first column. The event is an operator action, not a verified laser power transition; ignore transition margins during analysis. Send the TXT and CSV together.

This controlled study is intended to corroborate unlabeled bright spots against on/off state, not to assert an already-verified Pico camera mapping or accurate alignment.

### P2 controlled station power-toggle findings — 2026-10-15

The user's channel-to-physical-place identifications for channels 13 (FrontLeft-Low), 10 (FrontRight-Mid), 1 (FarRight-Top), 7 (Rear) are **confirmed by direct user inspection**. The PowerShell marker script records human ENTER presses in the same QPC nanosecond timebase as the QuestLHSync recording; these marks are not hardware telemetry for the moment the Lighthouse lasers fully switch.

A private ~417.6-second record and its 10-marker CSV were analyzed offline. The record contains 41,763 raw camera frames, 44,906 optical blob candidates and 29,112 HMD poses. An earlier shorter record had only the initial marker and was excluded from the controlled OFF/ON comparisons. No private calibration coefficients, room coordinates, or recordings are included here.

**High-confidence positive control for channel 13:** with the revised C4->factory cam2 hypothesis and a preliminary HeadFromBody, triangulation from C4 bright-spot rays recovered a stable 3D landmark. Three cameras C0/C4/C5 independently project bright detections to that landmark. Across the OFF-13 interval **no bright detections appeared within 20 px** of its predicted image position on any of those cameras, whereas the before/after ON intervals contain many hits. For C4 specifically the before/during/after counts within 20 px at peak>100 were **134 / 0 / 167**, despite 785 OFF frames with the landmark predicted in-image. This strongly associates that landmark with station channel 13; it is not proof of global Lighthouse alignment.

Fitting a limited camera-to-head transform plus a single 3D point using ~740 putative channel-13 spot correspondences improved median nearest-blob reprojection error on a 1-in-4 held-out *interleaved* subset from ~7.84 px to ~2.38 px. This is not independently time-separated validation (neighboring frames are correlated), not a full multi-station calibration, and no fit values may be installed in the driver.

Channel 10 has a suggestive C3 spot-count response, but **channels 1 and 7 were not optically labeled convincingly** by this pass: HMD poses in their OFF intervals differed from the nearest ON periods, and some spot-count drops began before the ENTER marker. Aggregate blob counts alone cannot identify a station. Avoid claiming that all four were calibrated or enabling tracking corrections.

Keep `mapping_verified=false`, `pose_verified=false`, and PICO `OBSERVE ONLY` pending independent multi-station 3D-ray association, validation of timing/geometry on disjoint motion segments, and corrections-vs-tracker accuracy measurements.

### P2 switch-marker spatial landmark follow-up — 2026-10-15

Offline ray-triangulation and reprojection of the existing 417.6-second switch-marker session isolated **channel-dependent optical signatures**, using private factory Omni/Radtan, provisional C0->cam0/C3->cam1/C4->cam2/C5->cam3 and the still-UNVERIFIED headset/body transform. The operator-confirmed physical station locations are retained. No headset-specific calibration parameters or room coordinates have been committed.

Procedure: triangulate near-synchronous ray pairs from cameras into stationary optical candidate landmarks; project candidates back into the images at interpolated PICO Connect HMD poses. A hit is a detected spot within 20px and peak >=100 **when the landmark is predicted inside the physical camera field of view**. Exclude 5 seconds around human ENTER switch markers and compare 23-second ON windows before/after the OFF interval.

| Power toggled | ON-before hits/visible | OFF hits/visible | ON-after hits/visible | Interpretation |
| --- | ---: | ---: | ---: | --- |
| ch13 (FrontLeft-Low) | 224/1182 | **0/2115** | 171/1267 | strong station-correlated optical signature |
| ch10 (FrontRight-Mid) | 3/885 | **0/2067** | 19/1836 | **weak** optical candidate; independently recheck |
| ch7 (Rear) | 39/1564 | **0/2413** | 37/1610 | strong station-correlated optical signature |
| ch1 (FarRight-Top) | — | — | — | **not reliably isolated** from the available views |

An ON-vs-ON comparison of the 3D triangulated candidate point positions yields ~12mm (ch13), ~42mm (ch10), ~22mm (preferred ch7) median-position differences. A secondary ch7 point was ~113mm apart between the before/after ON intervals and must not be used as a precision landmark. **These are internal consistency numbers for optical candidate points, NOT tracking accuracy or station-center measurements.** Candidate 3D sources may include IR reflections, which move no closer to identifying the lighthouse device's actual optical emitter geometry.

The detections are selected from and evaluated on a related recording, with frame correlation, incomplete exposure-time synchronization and a provisional HeadFromBody transform. They are not independent validation of an alignment. Next: use ch13 and ch7 signatures as seed associations; independently validate ch10 and explicitly determine whether ch1 ever has usable optical visibility. The full multi-station solver, station-center association, verified frame/timestamp mapping and correction-vs-physical tracker tests remain blocked. **OBSERVE ONLY** and false `mapping_verified` / `pose_verified` must remain unchanged.

### P2 independent-recording challenge and focused follow-up

Two older recordings were reprocessed independently of the controlled 2026-10-15 OFF/ON session, using the same *provisional* Pico camera mapping and HeadFromBody hypothesis. Unlike the OFF/ON session, these recordings have no complete toggling cycle and are **positive-only**, so they cannot independently establish channel identity:

| Provisional optical landmark | Earlier 77.8 s recording, matches/visible | Separate ~47.7 s all-ON recording, matches/visible |
| --- | ---: | ---: |
| channel-13 candidate | 7/3,520 | 243/1,431 |
| channel-10 candidate | 37/2,519 | 21/1,878 |
| channel-7 preferred candidate | 3/2,236 | 2/163 (mostly out of FOV) |

Counting uses >=100 peak, 20-pixel predicted-location radius, and only frames with candidate projected inside field of view. This does **not** establish unbiased false-match rates. A frequently observed unrelated landmark (~7937/8893 hits/visible in the main recording) remained detected on **719/735 C3 frames while station 1 was OFF**; do not label that landmark as channel 1. The channel-1 evidence remains insufficient.

**Important geometry falsification:** measured distances between current provisional point centers are NOT the SteamVR station-center distances: the (13,7), (13,10), (7,10) pairs give about **2.674/1.800/3.418 m** for the reconstructed optical candidates versus **2.858/2.013/3.782 m** for SteamVR physical station coordinates. Differences of ~0.18–0.36 m cannot be explained away as demonstrated tracking-grade accuracy. The optical candidates may be reflections, and the current HeadFromBody/timing could be inaccurate. Do not fit a correction by treating candidate points as real lighthouse emitter centers.

To avoid another long, poorly controlled session, `pico/tools/capture_missing_stations.ps1` requests only **two passes on channel 1 from different viewpoints** and **one pass on channel 10**. Each pass records the manual switch instant *and* separate Enter markers after returning to exactly the same viewing pose (`BASELINE_READY`, `OFF`, `OFF_READY`, `ON`, `ON_READY`, `PASS_DONE`), avoiding the previous head-pose mismatch. A fresh **Record session** must run continuously. Other stations remain on; the user operates station power manually. Data stay private; no live pose corrections are enabled.

Keep offline model and driver in OBSERVE ONLY with both verification flags false until source association is demonstrably independent and station geometry/timestamps are checked.
