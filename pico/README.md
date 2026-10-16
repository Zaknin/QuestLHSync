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

#### Running the focused channel 1 / 10 test

With **all four stations ON** and PICO Connect/SteamVR tracking stable, press **Record session** in the QuestLHSync dashboard. Run in a second PowerShell 7 terminal:

    pwsh -NoProfile -ExecutionPolicy Bypass -File .\pico\tools\capture_missing_stations.ps1

The guided test asks for two viewpoints on the channel-1 physical station and one on channel 10. For each pass: return to your marked feet/head pose for ON baseline; after turning the specified station OFF press Enter immediately, then **return to the same mark** and press Enter a second time before the OFF hold. Repeat for ON. Leave the other three powered. The operator must not let HMD tracking cameras sleep.

After the script completes, stop the dashboard recording, press its final Enter, and identify the latest `qlhs-*.txt` plus its sibling `qlhs-*-targeted-switches-*.csv`. Review the data with:

    python .\pico\tools\check_targeted_capture.py <TXT_PATH> <CSV_PATH>

The checker reports per-phase camera frames and HMD pose differences; it never validates actual station optical identity, and a failure may just mean tracking was interrupted. Share TXT/CSV privately for offline source association. Do not publish headset-specific factory calibration.

### P2 targeted channel 1 and 10 follow-up — 2026-10-15

The user performed the focused guided study with two marked viewpoints for channel 1 and a separate viewpoint for channel 10. A **474-second** continuously recorded QuestLHSync session contained **47,404** K0 frames (11,851 per camera), **86,520** blob candidates, **32,859** HMD poses, and **20** QPC-aligned Enter markers. This was analyzed **offline** with the private factory optics and still-unverified HeadFromBody; no live corrections were applied. A previous separately recorded full OFF/ON session provided out-of-session controls.

**Channel 1 is now optically identifiable as a stationary source candidate**, not a verified station center. Using one newly triangulated candidate and a **12-pixel** projection gate / **peak>=80**, counting frame-camera matches during short stable viewpoint holds:

| Physical switch | View | ON before | OFF | ON restored |
| --- | --- | ---: | ---: | ---: |
| ch1 | position A | 10 | **0** | 9 |
| ch1 | position B (independent viewpoint) | 9 | **0** | 8 |
| ch1 | separate prior 2026-10-15 OFF/ON recording | 2 | **0** | 8 |

All four cameras contribute some ON matches. The same source remains detectable when **ch10** is switched OFF while ch1 stays ON, supporting channel differentiation. This candidate is found from optical stereo rays, NOT fabricated from SteamVR station coordinates. Individual detections cluster in short bursts, so per-camera frame counts are temporally correlated and not equivalent to independent flashes.

**Channel 10 received independent corroboration.** Re-fitting its optical point using only the new ON windows, its 8–20 px projected-neighbor matches are ON/OFF/ON **13/0/11** in the focused capture (stable holds) and **2/0/15** in the earlier independent power-toggle capture (separate 23s ON / OFF windows at 10px gate, peak>=100). The channel-10 source is still seen while ch1 is OFF. Two other station-correlated candidates ch13 and ch7 were established in the earlier full-toggle session; all four physical channel-to-room mappings were confirmed by the user.

The **spatial-geometry gate FAILS**: fitting a single rigid transformation between four currently reconstructed optical candidate points and four saved SteamVR station-center coordinates yields approximately **0.19m 3D RMS residual**, with pointwise errors of order 0.11–0.25m. The provisional optical points may be infrared reflections and/or affected by incorrect HeadFromBody, exposure timestamps, detector bearing, or constrained viewing geometry. A source switch label is NOT a calibrated physical station-center measurement, and four IDs do not by themselves authorize pose corrections.

The camera mapping remains a *candidate* C0->cam0, C3->cam1, C4->cam2, C5->cam3. Both mapping_verified and pose_verified remain FALSE. Keep Pico `OBSERVE ONLY`. Next: implement an **offline, station-center-constrained multi-source reprojection solver** with bounded body-to-HMD extrinsics and true on/off-negative controls; test on disjoint sessions and report pixel/metric residuals before deciding whether clock/exposure and optical reflections require further capture. **Do not enable any Lighthouse pose modification yet.**

### P2 station-center constrained offline test and timing diagnosis — 2026-10-15

**Status: LAB-ONLY, OBSERVE ONLY, NO CORRECTIONS.** Three private recordings were analyzed offline (about 969 seconds total), with four OFF/ON station labels; no headset-specific factory coefficients or raw station coordinates were committed. User has physically confirmed channel 1/7/10/13 room placements.

**Clock finding:** Six reprojection tests that *re-optimize the 3D optical point at every time shift* independently favor camera PC-receive timestamp minus **94/96/94/102/94/100ms** for ch13 (two captures), ch10 (two), ch7 and ch1. This is a provisional relative alignment to PICO Connect HMD poses, **not a calibrated optical exposure timestamp**. Q round-trip telemetry shows ~3–5ms median Pico frame-copy-to-PC-receive delay; PC QPC vs Pico MONOTONIC clock drift is about **25.8–27.7ppm**, or 11–12ms over the long captures. New standard-library offline diagnostic: `python pico/tools/clock_drift_from_recording.py <qlhs-session.txt>`. Fix proper vendor sensor timestamp epoch and drift model rather than hard-coding -96ms in a live driver.

**Station-center constrained hypothesis:** 6DoF world alignment and 6DoF factory-body-to-SteamVR-head offset were fit against preliminary optical correspondences from controlled captures; Lighthouse world scale was *fixed at 1.0*. In a 10s-block held-out split, after applying the -96ms *offline pose shift*, joint fit median reprojection was **1.24px**, p90 **3.18px**, compared with 2.05px / 6.99px when using camera receipt time. The ch1 median was still ~7.9px. This is **conditional on the preliminary blob associations** and training on correlated motion; it is NOT blind physical calibration.

**Critical FAIL / no live correction:** when refitting the same constrained model after excluding an entire station from training, held-out median error was **9.27px (ch1), 44.67px (ch7), 8.07px (ch10), 36.0px (ch13)**. Thus the full joint-fit residual is an optimistic in-sample/interleaved measure; strong leave-one-base-out generalization is absent. An independent earlier capture also yields ~12px median for ch1. Optical spots can represent IR reflections rather than emitter centers, and the unverified camera-body geometry and exposure time can still be wrong.

**Action before P3:** verify Pico vendor K0 frame timestamps against Android clock domains and actual exposure age; correct the clock-domain/drift mapping with synchronization and per-frame timing. Develop station-center and reflected-source robust associations, then rerun leave-one-station-out and session-separated validation. Only after proving metric accuracy with physically tracked devices consider disabling OBSERVE ONLY. Keep `mapping_verified=false`, `pose_verified=false` and `HeadFromBody` unprovisioned for live use.

### P2 safe vendor clock scan: four K0 rings (separate from live streaming)

**WHY:** The three user recordings consistently fit PICO Connect HMD poses ~94–102 ms earlier than QuestLHSync frame receipt, while Android copy→Windows receive accounts for only ~3–8 ms. The K0 factory ring's `slot+122` is a **vendor timestamp candidate**, not a proven exposure time: earlier `--clock` scans placed it about 4.7 seconds **ahead of Android BOOTTIME**, not at a plausible unmodified exposure epoch. Do NOT add a fixed -96 ms to live tracking and do not assume `vendor_raw` is MONOTONIC or BOOTTIME.

New `PicoFrameReader --clock-scan [seconds]` mode reads, **without pixel copies**, the latest finished (not newest/in-flight) slot metadata on all four Binder cameras. It brackets the same instant with Android `System.nanoTime()` (MONOTONIC) and `SystemClock.elapsedRealtimeNanos()` (BOOTTIME); outputs CSV with the raw 64-bit nanoseconds, sensor sequence, newest sequence, ring index and slot index. Samples run ~20 sec by default (5–60 sec allowed). Production `PFR1` binary format, `F`/`T` wire protocol, `lhsyncd`, steamvr driver, private calibration, and `OBSERVE ONLY` are **unchanged**.

Build only the independent Java probe in a Windows checkout with JDK and Android SDK (no NDK needed): `python .\pico\build_module.py --reader-only`. **Do not install** any Magisk ZIP. This produces `pico/build/PicoFrameReader.jar`. To avoid disturbing the live QuestLHSync Java reader, copy this JAR to an entirely separate diagnostic path. With a Pico 4 Pro worn and tracking awake (no active PICO Connect/QuestLHSync camera capture is preferred), PowerShell:

    $ADB = '192.168.23.12:5555'
    $remote = '/data/local/tmp/PicoFrameReader-clockscan.jar'
    adb -s $ADB push .\pico\build\PicoFrameReader.jar $remote
    adb -s $ADB shell su -c "CLASSPATH=$remote /system/bin/app_process /system/bin PicoFrameReader --clock-scan 20" > "$HOME\Downloads\pico-k0-clockscan.csv"
    if ($LASTEXITCODE -ne 0) { throw 'Pico clock scan failed' }
    python .\pico\tools\analyze_vendor_clock.py "$HOME\Downloads\pico-k0-clockscan.csv"

Additional regression tests (synthetic, no headset required): `python -m unittest pico.tests.test_vendor_clock -v`. The CSV analyzer checks sequence monotonicity, K0 cadence, vendor-vs-MONOTONIC clock slope and the offsets to both Android clocks. Its status `DIAGNOSTIC_ONLY` **does not imply** sensor exposure or headset pose time is synchronized. The reported vendor clock rate over just 20 s is approximate; do not replace the verified Q ping PC↔Android synchronization with it.

**Decision gate:** an epoch and age model needs evidence that vendor timestamps correspond to actual exposures, with stable offsets across four cameras and device power/suspend states. A direct vendor timestamp *ahead of current BOOTTIME* is not physically a capture timestamp in that epoch; first locate the origin/offset or vendor metadata definition. Only after independent HMD pose correlation and a passed leave-one-station-out geometry test can we promote a live timestamp conversion.

#### Evidence for an earlier metadata timestamp at slot+84

**Offline evidence from 2026-10-15 (not live-calibrated):** 24 private raw K0 ring dumps (6 per camera, 5 stable slots each = **120 frame metadata snapshots**) were rescanned WITHOUT looking at pixel data. In addition to `slot+122`, **`slot+84` is a distinct, positive 64-bit increasing nanosecond-like field**. Both fields advance roughly every 40ms on successive even-step frame sequence numbers; `slot+122` is almost exactly 39.999896ms per frame, while `slot+84` varies by sensor/scheduling jitter. `slot+130` trails `slot+122` consistently by ~0.226ms.

| Binder camera | Samples | median `slot+122` minus `slot+84` | median `slot+84` consecutive step |
| --- | ---: | ---: | ---: |
| C0 | 30 | 4736.506 ms | 40.008 ms |
| C3 | 30 | 4736.042 ms | 40.089 ms |
| C4 | 30 | 4736.047 ms | 40.078 ms |
| C5 | 30 | 4735.734 ms | 39.921 ms |

`slot+122` was previously observed about 4.66–4.70s *ahead* of contemporaneous Android BOOTTIME in a separate live probe; these samples suggest `slot+84` might be approximately **tens of milliseconds behind BOOTTIME** instead of seconds ahead. **This subtraction combines separate sessions and is merely a plausibility estimate**, not a direct clock-domain validation or measured exposure age. `slot+84` might be camera capture, queueing or another vendor event. Never equate it with physical exposure without tracing the metadata semantics.

Reproduce aggregate stats privately: `python pico/tools/inspect_k0_ring_clocks.py <old_raw_ring.bin_or_archive.zip>`; public repo contains only the analyzer and above aggregate offsets, not private ring contents. The updated `--clock-scan` mode outputs raw `ring_ts84_ns`, `vendor_ns` (+122) and `ring_ts130_ns` (+130), alongside same-instant Android MONOTONIC/BOOTTIME; its CSV analyzer checks each field independently. The **live device run is pending**. Until then, the actual P1 `F` timestamp stays the MONOTONIC copy timestamp, NOT slot+84, and all corrections remain OFF.

#### Static firmware proof: slot+84 is a buffer write-lock BOOTTIME timestamp

**Strong binary-level identification, not just a numerical coincidence.** On the user's Pico OS binary `libpvrtrackingbuffer.so`, the exported `pvr::DataBuffer::lockForWrite(int*,int*)` function has a `mov w0,#4; bl systemTime; stur x0,[x25,#0x54]` sequence at the function-relative code offset near `0x3874–0x3884`. `x25` is the selected ring-slot base, and `0x54` = **84 bytes**. The producer explicitly writes an Android `systemTime(4)` sample *when it locks the ring slot for writing*. AOSP defines `SYSTEM_TIME_BOOTTIME=4` ([Timers.h](https://android.googlesource.com/platform/system/core/+/a8be627/include/utils/Timers.h)) and implements it using `CLOCK_BOOTTIME`. The same routine returns the output payload pointer `slot+0x61` (=97), consistent with the image metadata's known sensor index at offset 97. This proves both the field location and clock domain.

**Important correction to the earlier hypothesis:** `slot+84` is **NOT a hardware-exposure timestamp**, and must not be stamped onto a raw optical sighting as capture time. It measures *producer entry to writing the shared-memory record*, which can occur after physical exposure. The `--clock-scan` sample computes `BOOTTIME(now) - slot+84` to quantify an upper portion of the buffering/queueing age at the time of the read-only diagnostic; it does **not** quantify exposure→producer delay. The older `slot+122` and `slot+130` remain unidentified fields inside the camera-specific payload and cannot be treated as current Android time without establishing their vendor epoch.

Production K0 `F` still uses `System.nanoTime()` snapshot/copy time; camera mapping and body/head transform remain unverified, corrections are disabled. Never ship an automatic timestamp rewrite from the 4.736s historical ring offset: the correct conversion of the other clock and the physical exposure event are unknown.

### P2 20-second live K0 clock-scan validation — 2026-10-16

The user successfully ran the **Java-only diagnostic** on the real Pico 4 Pro. This is the direct read-only `PicoFrameReader --clock-scan 20` result (all proprietary/raw CSV remains private). **2,004 valid samples: 501 per camera; all four camera sequence counters advance by exactly 2 for each of 500 steps, with NO dropped sample in the 20-second test; cadence is 25Hz.**

| Camera | Median BOOTTIME(probe) - BOOTTIME(slot+84 write-lock) | Estimated remainder after a 39.999843ms frame | Median slot+122 minus slot+84 |
| --- | ---: | ---: | ---: |
| C0 | 45.213ms | 5.213ms | 4736.496ms |
| C3 | 45.381ms | 5.381ms | 4736.218ms |
| C4 | 45.836ms | 5.836ms | 4736.636ms |
| C5 | 45.641ms | 5.641ms | 4736.378ms |

Across **all 2,004 records** selected `newest_seq - seq = 2`, proving this read-only diagnostic intentionally chooses the immediately previous completed K0 frame. For **1,999/2,004** measurements `ring_index` is the next slot after the selected slot (five samples on a ring index boundary); this is consistent with the producer currently writing a newer slot. It explains an *approximate* whole-frame 40ms component of the measured 45ms write-lock→probe age. The extra ~5ms is just the difference between two medians, not a separately observed physical exposure-to-buffer or decoder delay. The first probe sample of each camera shows an expected initial ~77–78ms lag; 99% of other reads are ~40–51ms.

All four `slot+122` vendor clocks advance almost exactly **39.999843ms** per frame and are synchronised between cameras to within ~0.1µs for same-sequence frames. `slot+84` starts writing at slightly staggered wall times between the four cameras (~<1ms). `slot+130` trails +122 by **0.226ms**. No evidence in this 20s scan establishes any of these camera-specific timestamps as the physical sensor exposure moment.

On this headset, `BOOTTIME-MONOTONIC` offset measured **+9005.776s** (2h30m5.776s), stable to <0.03ms during the 20s scan; the difference is highly suspend-state dependent and MUST NOT be hardcoded. Absolute MONOTONIC offsets from earlier probe sessions (~138s) cannot be reused. The observed +30..43 ppm for vendor-vs-MONOTONIC over only 20s is a short-baseline estimate; use long multi-minute Q sync for clock-rate tracking.

**Engineering decision:** The P1 Java app intentionally discards `newest` and consumes only a verified penultimate slot; production `F` uses later copied MONOTONIC. A live pose relative offset of ~-96ms cannot be unconditionally explained or replaced by the measured ~45ms: producer write-lock is not exposure, Pico Connect pose reporting may add offsets, and stereo landmark errors remain. Keep all protection gates (`OBSERVE ONLY`, `mapping_verified=false`, `pose_verified=false`). To improve timestamp accuracy without sacrificing safety, first add an opt-in recorder of per-frame producer BOOTTIME and copied MONOTONIC on the SAME frame, with epoch snapshots and no driver pose modifications. Then use joint pose/optical validation to assess a clock-corrected solver. Do not re-enable tracking corrections from this timing evidence alone.

#### Optional same-frame write-lock vs copy telemetry

`PicoFrameReader` now also supports an **opt-in runtime diagnostic**: when the Java process inherits `PICO_FRAME_CLOCK_DIAG=1`, it reports every 125 accepted frames per camera (~5s), on **stderr only**, `cam`, `seq`, verified `slot+84 producer_write_boot_ns`, same-frame `java_copy_mono_ns`, `java_copy_boot_ns`, and their positive elapsed `producer_to_copy_ms`. It double-checks `slot+84` during the torn-slot validity test. The normal binary `PFR1` header, payload, `F` timestamps, and 25Hz solver-facing stream are **unchanged when the flag is unset**. This diagnostic is distinct from `--clock-scan` (which does not copy pixel frames).

The updated Java reader must be compiled/deployed for this new opt-in logging to work, and the complete live stream should be tested on the user's device. Do not turn on this debug flag in an always-on production module. It is designed to separate ring-buffer selection time from Java copy time when doing a future **short, controlled** validation. For now no production frame timestamp rewrite has been authorized.

### P2 same-frame active pixel-copy validation — 2026-10-16

The user compiled the new Java reader with `python pico/build_module.py --reader-only`, pushed **only the separate diagnostic JAR** and ran `PICO_FRAME_CLOCK_DIAG=1` through Android `timeout 22` with binary stdout redirected to `/dev/null`. It printed 4 diagnostic events per camera at sequence 3251, 3501, 3751, 4001 (250 sequence units = 125 physical frames ≈5 seconds). No exceptions were reported. This is a real read of full 640x480 K0 pixels, not the metadata-only probe.

| Camera | Four same-frame producer-write → Java-copy values (ms) | Median (ms) |
| --- | --- | ---: |
| C0 | 43.3555, 44.7185, 41.1473, 42.9573 | 43.1564 |
| C3 | 44.7232, 45.1911, 41.7046, 43.4392 | 44.0812 |
| C4 | 45.2654, 45.6979, 41.9085, 43.9121 | 44.5887 |
| C5 | 45.3081, 45.6933, 41.9602, 43.9499 | 44.6285 |

Overall **16 paired measurements**, median **43.931ms**, mean **43.808ms**, range **41.147–45.698ms**. The earlier metadata-only 20s scan (501 frames/camera) found medians 45.21–45.84ms; the two independent acquisition paths are consistent. While the penultimate-safe-slot selection likely accounts for approximately one 40ms camera interval, the residual is **not a proven sensor exposure→write latency**, and reading the actively written `newest` slot to save time would risk torn images. Do NOT change the slot selection algorithm based solely on this.

Same-frame Java snapshots show `BOOTTIME-MONOTONIC ≈ +18618.216262s` (5h10m18.216s) throughout the 20s copy experiment; the earlier scan showed +9005.776s. Android BOOTTIME includes suspend whereas MONOTONIC does not; any per-device offset must be sampled for each active session, not saved across sleep. This supports a separate online clock-domain conversion module only after verifying the sampling and synchronizing with Windows QPC.

`python pico/tools/analyze_frameclock.py <PicoK0-frameclock.txt>` now parses the opt-in stderr logs, verifies same-frame timing and consistent Android clock offsets, and reports per-camera statistics. Synthetic unit tests: `python -m unittest pico.tests.test_frameclock -v`. User's real textual log is **not** committed because it contains device-specific absolute monotonic timestamps.

**Gate remains BLOCKED:** producer write-lock is not hardware exposure time; a provisional -96ms HMD-pose relative optical delay was inferred from offline associations, but cannot be equated to producer-write age. Existing leave-one-station-out heldout residuals for channels 7 and 13 are tens of pixels. Continue only with offline or read-only timestamp/pose diagnostics until direct exposure/pose-frame alignment and robust geometry are validated; leave `OBSERVE ONLY`, `mapping_verified=false` and `pose_verified=false` unchanged.

### P2 Camera2 image timestamp decoded in raw K0 slot — 2026-10-16

**Static cross-library timestamp chain, high-confidence:** On archived user's Pico firmware `libpvrtrackingcamera.so`, `pvr::CameraReader::OnImageCallback(AImageReader*)` calls `AImageReader_acquireLatestImage` and then `AImage_getTimestamp` at disassembly VA `0x3a8bc`. It saves the returned 64-bit timestamp from `sp+0x8` and queues the image. In `CameraReader::processFrame` the queued `AImage_getTimestamp` travels via register `x25` and is placed in `pvr_frame_item_t` field `+0x18` (`stp x25, x22, [sp,#0xf8]` at VA `0x3c610`, where item begins `sp+0xe0`). The camera manager in `libpvrtrackingservice.so`, function `pvr::CameraManager::writeToExpSm`, copies `pvr_frame_item_t+0x18` into its ring payload offset `+0x11` (`ldr x8,[x20,#0x18]` at `0xacd6c`; `stur x8,[x0,#0x11]` at `0xacd70`). Since returned ring payload base is `slot+97` (sensor ID byte), **the Android Camera2 image timestamp resides at `slot+114`**. An adjacent item field `+0x20` becomes `slot+122` (`0xacd74`/`0xacd78`). No source code or private camera intrinsics were needed to establish this layout.

**Independent raw-memory falsification:** 24 archived private K0 ring dumps (6 per C0/C3/C4/C5), each with 5 complete sequence slots, total **120/120** accepted slots, have `uint64_le(slot+114) == uint64_le(slot+122)` bit-for-bit. This was also reproduced in separate older raw K0 dumps. Hence `slot+122`, the previously observed 25Hz, +4.736s clock, duplicates the actual **NDK `AImage_getTimestamp` return value** at `+114` on these devices.

**What this DOES and DOES NOT mean:** `AImage_getTimestamp` is the camera image timestamp returned by Android Camera2, a better semantic candidate for sensor capture timing than `slot+84`, which is known to be `DataBuffer::lockForWrite` BOOTTIME. The image timestamp's **clock epoch is not yet validated against `CLOCK_BOOTTIME` or HMD tracking poses**: on the same ring it lies ~4735.7–4736.6ms *ahead* of the buffer write-lock, meaning direct timestamp-as-BOOTTIME interpretation is physically impossible. Camera timestamp source could be device-specific/UNKNOWN. Do not use it as an uncorrected exposure time. First establish sensor epoch/offset and validate motion/pose alignment; a simple subtraction of the 4.736s observed gap would attach the image to producer time, NOT prove true exposure time.

`PicoFrameReader --clock-scan` now also emits read-only `image_ts114_ns` alongside +84/+122/+130, and the offline `analyze_vendor_clock.py` reports +114/+122 equality. `inspect_k0_ring_clocks.py` counts equality in archived raw rings. These code changes affect **diagnostic-only metadata**: normal P1 `PFR1` headers, `F` timestamps, binary input, driver, and all `OBSERVE ONLY`/calibration gates are unchanged. Fresh on-device scan of the enhanced diagnostic is not required immediately; the 120/120 archival evidence and 2004 live prior +122 samples justify working on the clock-model and geometry offline next.

### P2 clock-domain falsification and cross-camera coherence — 2026-10-16

The private 20-second live `PicoK0-clockscan.csv` was re-analyzed together with **24 separate raw K0 ring snapshots** (six per C0/C3/C4/C5; 120 completed slots). Only aggregated timing metrics are recorded here; neither the raw images nor private calibration are published.

- **501 simultaneous sequence groups** across all four cameras; 2,004 clock-scan records. In each group `slot+122` camera-image timestamp spread is at most **53 ns**; **347/501** groups have bitwise-identical timestamps across all four cameras. This supports a shared *relative* image timebase across the K0 sensors.
- Production buffer-write-lock (`slot+84`) epochs vary in timing between camera rings despite their shared image timestamps. Relative to C0 median producer write-lock offsets are **C3 +0.269ms, C4 −0.131ms, C5 +0.119ms**, emphasizing that one should not confuse write-lock with exposure/capture.
- In every one of 120 archived finished K0 slots, **`slot+114 == slot+122`**, corroborating the disassembled Android `AImage_getTimestamp()` chain. In the live 20s scan `slot+122` advances by a median **39.999843ms** for each of 500 frame intervals.
- Per-camera image timestamp **exceeds the same K0 slot's producer BOOTTIME write-lock timestamp by +4736.218..+4736.636ms** (medians). Since the producer locks the buffer after an image exists, a raw image timestamp **cannot be used unchanged as BOOTTIME physical exposure time**. A stable frame cadence does **not** identify the image clock's absolute epoch.
- Android NDK Camera2 documents the `ACAMERA_SENSOR_INFO_TIMESTAMP_SOURCE` states: REALTIME image timestamps can be compared to BOOTTIME/elapsedRealtime; UNKNOWN timestamps do **not** guarantee inter-subsystem synchronization. Reference: https://developer.android.com/ndk/reference/group/camera ; https://developer.android.com/ndk/reference/group/media . The Pico's actual characteristic has **not** been queried. We therefore reject an unshifted REALTIME interpretation, but do not claim a particular timestamp-source enum without direct evidence.
- The +4.736-second observed difference is a **camera epoch plus producer/sensor-pipeline delay**, which cannot be separated without independent exposure synchronization. Subtracting this number produces an image-time value near the producer write-lock, **not a validated exposure time**. Never turn it into an offline-to-online calibration constant or a fixed -96ms correction.
- 20s BOOTTIME−MONOTONIC clock difference was +9005.776s in the first scan and about +18618.216s in the second session; each session is internally stable but absolute offsets are **not transferable across headset sleep/reboot**.

Engineering changes: `pico/tools/analyze_vendor_clock.py` now accepts both the **original live CSV without `image_ts114_ns`** and newer `--clock-scan` CSV with that optional field; detects four-camera per-sequence image coherence; emits an explicit `direct_vendor_as_boottime_exposure_allowed=false` when future sensor timestamps falsify that interpretation. Six unit-test cases cover legacy compatibility and cross-camera behavior. `actual_exposure_time_verified` / `sensor_exposure_clock_epoch_verified` remain false.

**Next required measurement:** a clock-epoch anchor independent of `slot+84` (producer write-lock) and PICO Connect's pose prediction timestamp, or an independently timed optical/IMU stimulus. **Next geometry gate:** blind, session-separated detections not selected around fitted landmarks and leave-one-base-out validity. While either gate fails, `OBSERVE ONLY`, `mapping_verified=false`, `pose_verified=false`, and unchanged `F` timestamp stay mandatory.
