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

### P2 paired-clock rate recheck — 2026-10-16

**Read-only progress; neither physical exposure nor live clock conversion is established.** A new standard-library tool `python pico/tools/audit_paired_clocks.py <PicoK0-clockscan.csv> [--output result.json]` estimates short-baseline CLOCK RATE using each frame's own `slot+122 AImage` timestamp versus its `slot+84 BOOTTIME producer-write` timestamp. It bins same-frame differences into 1-second medians to avoid the 40ms phase noise of previously comparing images to later Java probe MONOTONIC timestamps. Older live CSVs without optional `slot+114` are accepted.

| Camera | Same-frame image-minus-producer median (ms) | 20-second binned rate difference (ppm) |
| --- | ---: | ---: |
| C0 | 4736.4960 | +0.20 |
| C3 | 4736.2179 | +0.28 |
| C4 | 4736.6365 | +0.51 |
| C5 | 4736.3782 | −3.27 |

Input was the previously validated 2,004-row live Pico clock scan; 501 four-camera sequence groups and at most 53ns per-group spread of the AImage sensor timestamp. This short record supplies **no strong evidence for a 30–43ppm image-vs-BOOTTIME clock-rate mismatch**. The older vendor-vs-PROBE-MONOTONIC rate measurements were made at different instants in a 25Hz ring and are not a suitable estimate of *paired* physical clock-rate difference. Even the new small per-camera estimates are noisy and must not be extrapolated into an authoritative long-run ppm correction.

Fundamental ambiguity: let image timestamp = physical exposure + unknown sensor epoch, and producer BOOTTIME = physical exposure + sensor-to-producer processing delay. Their observed difference identifies only **epoch minus processing delay**, not either term separately. Consequently, the roughly +4.736s offset cannot be turned into exposure time by subtraction, even if the clock slopes agree. The hardware exposure timestamp domain / PICO Connect HMD pose epoch remain unverified.

Safety contract: independent of computed ppm, the tool returns `camera_clock_epoch_verified=false`, `physical_exposure_time_verified=false`, `hmd_pose_timebase_verified=false`, `live_lighthouse_correction_allowed=false`. It explicitly validates monotonic sequences and cross-camera coverage, with 5 offline synthetic regression tests (`python -m unittest pico.tests.test_paired_clocks -v`) covering zero rate skew, known +12ppm skew, missing camera, duplicate sequence and image-timestamp jump. No Pico Java streaming changes or SteamVR corrections were made.

Next research stage: obtain an *independent* event/epoch anchor for `AImage_getTimestamp` and for HMD pose prediction timestamps; perform blind station-point association without using the landmark that seeds its own validation. The station-withheld geometric error remains tens of pixels for channels 7/13: do not enable `OBSERVE ONLY` overrides.

### P2 verification strength audit: solver split — 2026-10-16

A separate **PRIVATE** audit reloaded previously saved `correspondences.npz` and `solver_internal.npz` (no refit, no direct export of poses/calibration). The new reusable `pico/tools/audit_solver_holdout.py <private-correspondences.npz> <private-solver_internal.npz>` prints aggregate train/test membership, session overlap and 10-second block overlap. It is a sanity check of the **experimental design**, not source classification or metric accuracy.

Observed old solver split: **1,357 train / 751 held out**, zero exact index leakage, **zero shared ten-second blocks**, but both `B_control` and `C_target` appear in BOTH train and held-out observations: the split is **NOT a whole-session holdout**. The previous reported ~1.24px fit therefore cannot be called independent *session-separated* accuracy.

| Lighthouse channel | Train selected 2D observations | Held-out selected observations |
| --- | ---: | ---: |
| 1 | 76 | 40 |
| 7 | 39 | 21 |
| 10 | 477 | 272 |
| 13 | 765 | 418 |

Channel 7 is represented by only **60** total selected points in this geometric solver, while channel 13 has **1,183** (≈19.7 times more). The pooled pixel-error statistic will be dominated by channels 10 and 13. In addition, associations were selected *using prior projected seed landmarks*, so withholding 10-second blocks does not make source identification blind; the same identity prior helped select both training and test targets. This is a model-selection limitation, not necessarily code leakage.

Two distinct gates remain: (1) absolute optical exposure/HMD pose timebase, and (2) blind, independent multi-camera source association with balanced channels plus a whole-recording test and leave-one-station-out. Both are currently BLOCKED. Do not treat 'zero off-interval hits' in a seed-centered search as self-contained evidence of station-center calibration.

The split audit requires `numpy` (already used by the existing offline solver), does not accept live driver calibration, and always emits `live_correction_allowed=false`. Four synthetic regression tests were added at `pico/tests/test_solver_holdout_audit.py`. It never writes headset-specific data to GitHub.


### P2 deterministic validation-fold preparation — 2026-10-16

Following the split audit, `pico/tools/plan_solver_folds.py` prepares PRIVATE,
reproducible diagnostic train/test index arrays from an existing
`correspondences.npz` (`session`, `ch`, `t` arrays). It creates one
leave-entire-session-out fold per recorded session and four
leave-entire-station-out folds (Lighthouse channels 1, 7, 10, 13).

Run, from the repository root, with the **private** observation file:

    python pico/tools/plan_solver_folds.py <private-correspondences.npz> --report <private-fold-report.json> --folds <private-fold-indices.npz>
    python -m unittest pico.tests.test_solver_folds -v

The count-only JSON report flags missing channel coverage; the optional NPZ
contains only index arrays. No station coordinates, camera intrinsics, images,
poses, or installed live calibration are generated. The source archive is not
modified. Synthetic validation checks enforce disjoint, exhaustive partitions
and all live-correction flags remaining FALSE.

**Critical limitation:** these folds are generated from observations already
selected around fitted 3D seed landmarks. They do **not** prove blind source
identity or independent geometry. A valid next test must refit solely on
training captures, blindly detect sources afresh in the held-out raw capture,
apply OFF/ON negative controls, and evaluate station-center geometry, timing,
per-channel pixel residuals and metric accuracy. The existing solver is NOT
authorized to consume these arrays as evidence of a passing calibration.
No on-device corrections may be enabled. Keep `OBSERVE ONLY`,
`mapping_verified=false`, `pose_verified=false`, and the original
PFR1/F timebase unchanged.


### P2 read-only Camera2 timestamp source metadata discovery — 2026-10-16

The next independent *metadata* check is whether Android Camera2 exposes
`ACAMERA_SENSOR_INFO_TIMESTAMP_SOURCE` for any publicly enumerated camera ID.
This is NOT itself an exposure-time anchor, and public Camera2 device IDs
are not automatically the same as the internal `pvrtracking` Binder K0 IDs.

The standalone program `pico/src/camera_timestamp_source_probe.c` performs
only `ACameraManager_getCameraIdList`,
`ACameraManager_getCameraCharacteristics`, and
`ACameraMetadata_getConstEntry`. It never opens a camera, creates a session,
starts a new stream, reads images, calls the tracking Binder service, or
changes pose data. The build is **opt-in** and does not modify the normal
Magisk package or Java reader:

```powershell
cd C:\Dev\PicoLHSync
git switch feature/pico-support
git pull --ff-only
python .\pico\build_module.py --camera2-probe-only
$ADB = '192.168.23.12:5555'
adb -s $ADB push .\pico\build\pico_camera2_timestamp_probe /data/local/tmp/pico_camera2_timestamp_probe
adb -s $ADB shell su -c 'chmod 700 /data/local/tmp/pico_camera2_timestamp_probe; /data/local/tmp/pico_camera2_timestamp_probe'
```

The output is textual, with a declared static-metadata-only safety mode,
Android `BOOTTIME` and `MONOTONIC` clock snapshots, exposed Camera2 IDs,
and per-ID `UNKNOWN`, `REALTIME`, or missing metadata. A successful
query establishes the characteristic **only for that enumerated Camera2 ID**.
No mapping from such IDs to `C0/C3/C4/C5` (and no source contract for the
internal QuickCamera route) has been verified. A result of `REALTIME` for an
unrelated public Camera2 ID does NOT authorize shifting K0 image timestamps
or overriding the multi-second image-vs-producer discrepancy; `UNKNOWN`
likewise does not determine the absolute epoch. A zero-device listing, missing
key, or permission error is a diagnostic result, not a reason to interfere
with active SLAM or open a second stream.

Even if a matching K0 Camera2 source were established, the Camera2 source
enum by itself would not validate the PICO Connect HMD pose timebase or
the previously measured pose/camera phase shift. An independent exposure
event or well-characterized firmware clock conversion is still necessary.
**No Lighthouse power cycling is required for this metadata check.**

Safety gates remain **OBSERVE ONLY**, `mapping_verified=false`,
`pose_verified=false`, `physical_exposure_time_verified=false`, with
no live Lighthouse pose corrections.


### P2 Camera2 metadata result from real Pico 4 Pro — 2026-10-16

The owner compiled the standalone Android NDK probe using
`ndk/27.2.12479018` on Windows 11 and executed it via `adb shell su -c`
on the Pico 4 Pro. **Build: PASS; standalone program: PASS.**
The probe enumerated six public Camera2 IDs, `0..5`. Each returned
`ACAMERA_SENSOR_INFO_TIMESTAMP_SOURCE_REALTIME` (`raw=1`).
Android CLOCK_BOOTTIME minus CLOCK_MONOTONIC at the probe instant was
**18,618.216259188 seconds**, consistent with a prior in-session measurement.
The tool exited with `STATIC_METADATA_ONLY`.

This is **not** an independent epoch anchor for the four internal K0
tracking streams: mapping between public Camera2 IDs `0..5` and internal
Binder cameras `C0/C3/C4/C5` is unverified. Under the Camera2 REALTIME
contract, *a matching public device's ordinary image timestamps* should
use the elapsedRealtime / BOOTTIME domain. The archived K0 images instead
contain `AImage_getTimestamp` values roughly 4.736 s *ahead of*
their completed buffer's BOOTTIME write-lock, which is incompatible with
an unconverted direct REALTIME exposure interpretation. This discrepancy
could be from an internal HAL/vendor timestamp transformation, a distinct
non-public stream/domain, or a violated timestamp contract; none is
currently demonstrated as the cause. In particular, **do not subtract
4.736 s as a calibration constant**.

As a low-risk follow-up, the *same executable* supports opt-in
`--fingerprint`: this reports only static facing, sensor orientation,
pixel array and whether 640x480 output is advertised. No raw images,
intrinsics, extrinsics, pose, or actual image timestamps are fetched. The
flag is intentionally separate from the proven V1 default invocation.
Build and run from the existing Windows checkout:

```powershell
cd C:\Dev\PicoLHSync
git switch feature/pico-support
git pull --ff-only
python .\pico\build_module.py --camera2-probe-only
if ($LASTEXITCODE -ne 0) { throw 'Android NDK build failed' }
$adbTarget = '192.168.23.12:5555'
$remote = '/data/local/tmp/pico_camera2_timestamp_probe'
adb -s $adbTarget push .\pico\build\pico_camera2_timestamp_probe $remote
if ($LASTEXITCODE -ne 0) { throw 'ADB push failed' }
adb -s $adbTarget shell su -c "$remote --fingerprint"
```

A matching 640x480 output dimension or orientation can only narrow the
candidate mapping, not prove it. The next decisive timebase measurement
still requires an independent exposure/pose clock anchor, e.g. a
non-disruptive hardware-timed visible/IMU event or validated firmware
conversion. Do not open Camera2 devices while pvrtracking/SLAM owns
them, and do not enable live tracking corrections. All P2 gates remain
false and the normal Pico PFR1 / SteamVR driver unchanged.


### P2 six-camera static fingerprint — measured on real Pico 4 Pro, 2026-10-16

Second standalone metadata probe **compiled and executed successfully** after
setting executable permissions again following `adb push`. All values below
come from Android Camera2 *static characteristics only*; no cameras were
opened. `ACAMERA_LENS_FACING_EXTERNAL=2`; `BACK=1`.

| Public Camera2 ID | Facing | Orientation | Pixel array | Advertises 640x480 output | Timestamp source |
| --- | --- | ---: | --- | --- | --- |
| 0 | EXTERNAL (2) | 270° | 640x481 | Yes | REALTIME (1) |
| 1 | EXTERNAL (2) | 270° | 640x481 | Yes | REALTIME (1) |
| 2 | EXTERNAL (2) | 270° | 640x481 | Yes | REALTIME (1) |
| 3 | EXTERNAL (2) | 270° | 640x481 | Yes | REALTIME (1) |
| 4 | BACK (1) | 90° | 2328x1748 | Yes | REALTIME (1) |
| 5 | BACK (1) | 90° | 400x1600 | No | REALTIME (1) |

The common unusual 640x481 pixel array, 640x480 advertised output,
orientation and external-facing designation are **strong corroborating
evidence** that public Camera2 IDs 0..3 are the four tracking cameras
whose internal K0 image payloads are 640x480. However they **do not**
prove individual Camera2-ID ↔ internal K0-ID (`C0/C3/C4/C5`) order,
nor independently verify that `AImage_getTimestamp` values in the
PVR callback obey the publicly advertised Camera2 timestamp contract.

Re-read of Android public Camera2 specification: for REALTIME the
capture-result sensor timestamp is in the same domain as
`SystemClock.elapsedRealtimeNanos()` / Android BOOTTIME. The archived
internal K0 value `slot+114 == slot+122` ~4736ms *after* the producer
BOOTTIME buffer-write timestamp contradicts straightforward application
of that contract. Plausible explanations (still **hypotheses**)
include internal timestamp re-epoching after Camera2 acquisition,
undocumented PVR-to-HAL camera path behavior, public-ID mismatch,
or a vendor metadata/timebase contract violation. Matching camera
characteristics alone must not be taken as proof of any explanation.

**Next safe identification step**: read the Android 10 camera service's
own `dumpsys media.camera` (without starting cameras) to extract HAL
provider/device names and public-ID bindings. If that yields the
provider mapping, cross-correlate it with the already archived PVR
binary's source-level/disassembly camera-ID path. Do not upload raw
camera metadata/extrinsics or open a second capture session. If
`dumpsys` cannot establish the per-camera correspondence, report it
as unresolved rather than physically disturbing SLAM or inventing
an ID mapping. Independently determining the sensor epoch still
requires a separate observable clock/exposure anchor.

No changes to normal Magisk/Java/PFR1/SteamVR streaming, no
sensor timestamp corrections, and no relaxation of `OBSERVE ONLY`,
`mapping_verified=false`, `pose_verified=false`.


**Previously archived device-level process separation matters:** the owner's
root ADB observations (2026-10-13) showed two vendor camera paths:
`android.hardware.camera.provider@2.4-service_64` held
`/dev/video0` (cam-req-mgr) and `/dev/video2` (cam_sync);
`pico.camera.quickcamera.quickcameramodule@1.0-service_64` held
`/dev/video1` (hub_cam-req-mgr) and `/dev/video3` (hub_cam_sync).
The archived static disassembly of `libpvrtrackingcamera.so` also
identifies a QuickCamera dequeue/return callback chain alongside the
AImageReader chain. This is concrete evidence of *distinct access paths*
rather than proof that ordinary public Camera2 metadata is the
contract governing every internal PVR tracking image. The four matching
640x481 public camera characteristics strengthen physical-device
identification, while the QuickCamera separation is a plausible
source of an altered image epoch. It is NOT yet a verified root cause.

For the next device-side, non-streaming observation, use only the standard
Android 10 camera service dump, print provider/device bindings rather
than the complete sensitive metadata dump, and do not issue Camera2
open/session or vendor-specific dump commands that could change state:

```powershell
$adbTarget = '192.168.23.12:5555'
adb -s $adbTarget shell dumpsys -t 10 media.camera |
  Select-String -Pattern 'Number of camera devices|Number of normal camera devices|Camera Provider HAL|Camera HAL device|Device [0-9]+ maps|Device [0-9]+ is|Active Camera Clients|device@|quickcamera' |
  Select-Object -First 100
```

An empty or partial dump is an informative result and does not justify
probing live camera ownership. The **next real timebase anchor** must
come from independent firmware-clock mapping, synchronized optical/IMU
timing, or verified Camera2-to-QuickCamera frame timestamp correspondence.
No offset conversion is to be inferred just from six REALTIME enums.


### P2 Android CameraService provider inventory — owner read-only dump, 2026-10-16

Owner's `adb shell dumpsys -t 10 media.camera` returned:

- `Number of camera devices: 7`.
- `Number of normal camera devices: 4`.
- Legacy-compatible index mappings `Device 0 maps to "0"`,
  `Device 1 maps to "3"`, `Device 2 maps to "4"`,
  `Device 3 maps to "5"`.
- `Camera Provider HAL legacy/0 (v2.5, remote)` with 7 device entries
  `device@3.5/legacy/0` through `device@3.5/legacy/6`.
- `Device 0` through `Device 5` were closed with no ordinary
  CameraService client. This does NOT imply that a separate vendor
  QuickCamera/pvrtracking pipeline was idle.

**Critical API1 distinction verified against Android 10 AOSP source:**
`CameraService::updateCameraNumAndIds()` populates
`mNormalDeviceIds` using
`CameraProviderManager::getAPI1CompatibleCameraDeviceIds()`.
The “normal camera devices” dump is the Camera1/API1-compatibility
subset; its `Device N maps to "ID"` lines translate legacy positional
indexes to actual string IDs, NOT internal PVR K0 channel indices.
Source (AOSP historical CameraService):
https://android.googlesource.com/platform/frameworks/av/+/e397f43/services/camera/libcameraservice/CameraService.cpp

The NDK API `ACameraManager_getCameraIdList` can also enumerate a
**subset** of SDK CameraManager devices when certain legacy hardware
is unsupported. Source (official Android NDK):
https://android.googlesource.com/platform/frameworks/av/+/master/camera/ndk/include/camera/NdkCameraManager.h

Therefore 7 HAL device entries, 6 enumerated NDK IDs (0..5), and 4
legacy/API1-compatible IDs (0,3,4,5) are NOT by themselves evidence of
extra sensor hardware, a precise K0 mapping, or a timestamp conversion.
The 7th entry `legacy/6` needs **static metadata inspection** to
classify, without Camera2 open/stream commands or identity guessing.

Safe, focused PowerShell 7 inspection (stdout only, discard locally
after diagnosis unless voluntarily retained as private evidence):

```powershell
$adbTarget = '192.168.23.12:5555'
$lines = @(adb -s $adbTarget shell dumpsys -t 10 media.camera)
if ($LASTEXITCODE -ne 0) { throw 'camera dumpsys failed' }
$head = $lines | Select-String 'Camera HAL device device@3\.5/legacy/6 .*static information' | Select-Object -First 1
$tail = $lines | Select-String 'Camera HAL device device@3\.5/legacy/6 .*dumpState' | Select-Object -First 1
if (-not $head -or -not $tail) {
    'Camera6 static section missing or truncated; no inference'
} else {
    $lines[($head.LineNumber - 1)..($tail.LineNumber - 2)] |
      Select-String -Pattern 'Camera HAL device|Resource cost|API1 info|android\.info\.supportedHardwareLevel|android\.request\.availableCapabilities|android\.sensor\.info\.timestampSource|android\.sensor\.info\.pixelArraySize|android\.lens\.facing|android\.sensor\.orientation' -Context 0,2 |
      Select-Object -First 70
}
```

Stay OBSERVE ONLY. Even valid public REALTIME metadata for the four
640x481 EXTERNAL cameras cannot be transferred to internal K0 timestamps
until the vendor path and timestamp arithmetic are independently verified.


### P2 HAL legacy/6 static classification — real device, 2026-10-16

The owner's follow-up **read-only** `dumpsys -t 10 media.camera` static section for
`device@3.5/legacy/6` establishes:

- `android.request.availableCapabilities` contains
  **`LOGICAL_MULTI_CAMERA`** together with BACKWARD_COMPATIBLE,
  RAW, YUV_REPROCESSING, PRIVATE_REPROCESSING, READ_SENSOR_SETTINGS,
  MANUAL_SENSOR, BURST_CAPTURE, MANUAL_POST_PROCESSING.
- `android.lens.facing=EXTERNAL`,
  `android.sensor.orientation=270`,
  `android.sensor.info.pixelArraySize=[640, 481]`,
  `android.sensor.info.timestampSource=REALTIME`,
  `android.info.supportedHardwareLevel=FULL`.
- `Resource cost: 100`; HAL `Conflicting devices: 0`.
  API1 display label also reads "Facing: Front", showing why Camera1
  descriptive labels should not override Camera2 metadata.

Android's definition of `LOGICAL_MULTI_CAMERA` is a logical camera
backed by two or more physical cameras, not a proof that device 6 is
a *seventh* standalone sensor. The matching 640x481 characteristics
make it a candidate for grouping the physical tracking cameras, but
**membership and exact public-ID ↔ K0-ID routing are still unknown**.
The reported resource conflict with device 0 is not a physical-ID map.

Android's standard static metadata
`android.logicalMultiCamera.physicalIds` is the next discriminator.
The NDK metadata tag `ACAMERA_LOGICAL_MULTI_CAMERA_PHYSICAL_IDS`
contains a NUL-delimited byte array of physical camera ID strings,
not numeric camera indices. Physical camera IDs can be hidden from
ordinary CameraManager ID listings on Android 10. Official references:
https://source.android.com/docs/core/camera/multi-camera and
https://developer.android.com/ndk/reference/group/camera

**Safe one-shot inspection; never opens the camera**. Filter *only*
the HAL 6 static section, including 2–4 lines of context around keys.
Do not post a full metadata dump with calibration/extrinsics:

```powershell
$adbTarget = '192.168.23.12:5555'
$lines = @(adb -s $adbTarget shell dumpsys -t 10 media.camera)
if ($LASTEXITCODE -ne 0) { throw 'camera dumpsys failed' }
$start = $lines | Select-String 'Camera HAL device device@3\.5/legacy/6 .*static information' | Select-Object -First 1
$end = $lines | Select-String 'Camera HAL device device@3\.5/legacy/6 .*dumpState' | Select-Object -First 1
if (-not $start -or -not $end -or $end.LineNumber -le $start.LineNumber) {
    'HAL 6 static section not present / dump truncated'
} else {
    $lines[($start.LineNumber - 1)..($end.LineNumber - 2)] |
      Select-String -Pattern 'android\.logicalMultiCamera\.physicalIds|android\.logicalMultiCamera\.sensorSyncType|android\.request\.availableCapabilities' -Context 0,3
}
```

**Interpretation gate:** HAL 6 physicalIds may establish *public*
parent↔physical identifiers. It does not prove which internal
`pvrtracking` K0 `C0/C3/C4/C5` index corresponds to each one,
and CALIBRATED sensor synchronization (if reported) would address
*relative* exposure alignment, NOT the ~4.736s absolute K0 epoch
disagreement with BOOTTIME. Keep all tracking and timebase safety
gates blocked; no live corrections.


### P2 resolved HAL legacy/6 physical membership and sync contract — 2026-10-16

The owner ran a **read-only** `dumpsys media.camera` static section query.
For `device@3.5/legacy/6` the exact decisive fields were:

```text
android.request.availableCapabilities:
  [BACKWARD_COMPATIBLE RAW YUV_REPROCESSING PRIVATE_REPROCESSING
   READ_SENSOR_SETTINGS MANUAL_SENSOR BURST_CAPTURE MANUAL_POST_PROCESSING
   LOGICAL_MULTI_CAMERA]
android.logicalMultiCamera.physicalIds (1a0000): byte[7]
  [48 0 49 0 50 0 51]
android.logicalMultiCamera.sensorSyncType (1a0001): byte[1]
  [APPROXIMATE]
```

The byte values are ASCII `0 NUL 1 NUL 2 NUL 3`; thus the logical
HAL `legacy/6` reports **physical Camera2 IDs "0", "1", "2", "3"**.
No camera was opened. Note the vendor field is **7 bytes rather than 8**:
the last ASCII "3" has no terminating NUL in the dump, even though
Android's tag definition specifies preservation of a final delimiter.
Interpret the bounded `byte[7]` contents, and do **not** pass this
potentially unterminated data to unchecked C-string functions.
This is a static metadata formatting irregularity, NOT evidence of any
additional physical camera or a timestamp bug.

The owner's physical layout identifies **five outward-facing sensors**:
four monochrome SLAM/tracking units and one RGB passthrough unit.
Pico 4 Pro additionally implements inward-facing face/eye tracking,
and the separate Camera2 ID 5 (400x1600) has **not** been assigned a
particular physical purpose. Do not count HAL 7 as seven outward sensors.
Public Camera2 physical IDs 0..3 being members of logical 6
reinforces, but does not establish an individual correspondence to
internal PVR K0 Binder IDs C0,C3,C4,C5.

**Important clock nuance:** Android
`LOGICAL_MULTI_CAMERA_SENSOR_SYNC_TYPE_APPROXIMATE` means there is
**no guarantee of hardware shutter/exposure synchronization** between
component sensors. Its metadata documentation explicitly notes that
images from a *single logical capture request* can still share the
same frame timestamp despite approximate exposure synchronization.
Therefore the prior K0 347/501 bitwise-equal four-camera timestamps,
and worst 53 ns spread, prove **metadata coherence**, not physical
exposure simultaneity or submicrosecond hardware synchronization.
This is compatible with the owner's measured K0 records, though the
hypothesis of common logical request timestamps within the private
QuickCamera path still requires separate verification.

Official references:
- https://source.android.com/docs/core/camera/multi-camera
- https://developer.android.com/ndk/reference/group/camera
- https://android.googlesource.com/platform/frameworks/av/+/cffd50f6e802b4c33930abdd3ba3d5e1a5d93945/camera/ndk/include/camera/NdkCameraMetadataTags.h

**Current gate:** logical membership verified, per-physical-ID ↔ K0
index mapping unverified, exposure hardware sync unverified, absolute
sensor timestamp epoch unverified, PICO Connect HMD pose timestamp
epoch unverified, blind Lighthouse geometry unverified. Next work
must trace the archived PVR/QuickCamera timestamp-producing and clock
conversion code (including `AImage_getTimestamp` entry and the
`pvr_frame_item_t+0x18/+0x20` propagation) or obtain an independent
physical/pose event-time anchor. Another Camera2 enumeration or
speculative +4736ms offset is not useful. **OBSERVE ONLY** stays.


### P2 QTIMER clock-domain lead — recovered archival evidence, 2026-10-16

**A materially new hypothesis was recovered from the owner's
2026-10-13 read-only `dumpsys pvrtracking` transcript** (recorded
during a separate earlier headset session):

```text
time boottime 10433928640393, monotime 10433928640758, qtimer 10438675043177
```

Treating these 64-bit readings as nanoseconds, this yields

```text
PVR qtimer - PVR boottime   = 4,746,402,784 ns = +4,746.402784 ms
K0 image +122 - write +84  ≈ +4,736 ms      (other recorded session)
Difference                   ≈ +10.4 ms      (cross-session, not verified)
```

**Testable explanation, NOT yet confirmed:** the K0 AImage timestamp
might originate in the vendor/Qualcomm QTIMER clock domain, while
K0 `slot+84` is a BOOTTIME producer-write-lock timestamp. Subtracting
their epoch difference leaves a positive ~10ms **possible producer lag**
(frame acquisition to producer lock). This numerical proximity is
much more specific than fitting an arbitrary camera/SteamVR lag, but
does NOT prove a QTIMER source, hardware exposure, exact session offset,
or firmware clock conversion. In particular, vendor `dumpsys` names
are NOT an API-level clock contract; even its `boottime` field must
be verified against the CameraManager `slot+84` BOOTTIME clock in the
*same session*. We must not use this historic value to calibrate
new frames or the existing ~-96ms offline geometric lag.

New stdlib-only **offline** tool:
`pico/tools/audit_qtimer_bridge.py --before before.txt --csv k0.csv
--after after.txt`. It compares per-session PVR QTIMER-minus-PVR-BOOT
from two service snapshots with the per-camera
K0 `vendor_ns-ring_ts84_ns` gaps from the *intervening* live read-only
`--clock-scan`. It fails closed if the PVR clock epoch does not bracket
K0 ring write-lock times, if QTIMER offset moves more than 2ms during
this short session, or if resulting apparent producer lag is negative
or beyond 100ms. **These engineering bounds are diagnostic heuristics,
not proof of sensor exposure latency.** The output always keeps
`qtimer_timestamp_source_verified=false`,
`sensor_exposure_time_verified=false`,
`camera2_to_k0_mapping_verified=false`,
`steamvr_pose_clock_verified=false`, and
`live_lighthouse_correction_allowed=false`.

One-off read-only execution from owner's Windows PowerShell 7 checkout.
No Lighthouse switching, second camera stream, driver build, or Magisk
install is required. Device tracking must be awake for 12 seconds.
Reader JAR build/push uses the already supported `--reader-only` mode:

```powershell
cd C:\Dev\PicoLHSync
git switch feature/pico-support
git pull --ff-only
python -m unittest pico.tests.test_qtimer_bridge -v
if ($LASTEXITCODE -ne 0) { throw 'QTIMER offline tests failed' }
python .\pico\build_module.py --reader-only
if ($LASTEXITCODE -ne 0) { throw 'Reader build failed' }
$adbTarget = '192.168.23.12:5555'
$jar = '/data/local/tmp/PicoFrameReader.jar'
adb -s $adbTarget push .\pico\build\PicoFrameReader.jar $jar
if ($LASTEXITCODE -ne 0) { throw 'Reader JAR push failed' }

$save = Join-Path $PWD 'pico\build\qtimer-p2-private'
New-Item -ItemType Directory -Force -Path $save | Out-Null
function Read-PvrClock {
    $raw = @(adb -s $adbTarget shell su -c 'dumpsys -t 10 pvrtracking')
    if ($LASTEXITCODE -ne 0) { throw 'pvrtracking dumpsys failed' }
    $match = $raw | Select-String -Pattern '^time boottime \d+, monotime \d+, qtimer \d+' | Select-Object -First 1
    if (-not $match) { throw 'PVR clock line absent' }
    $match.Line
}
Read-PvrClock | Set-Content -Encoding utf8 (Join-Path $save 'before.txt')
$rows = @(adb -s $adbTarget shell su -c "CLASSPATH=$jar /system/bin/app_process /system/bin PicoFrameReader --clock-scan 12")
if ($LASTEXITCODE -ne 0) { throw 'K0 clock scan failed; no partial evidence' }
$rows | Set-Content -Encoding utf8 (Join-Path $save 'k0.csv')
Read-PvrClock | Set-Content -Encoding utf8 (Join-Path $save 'after.txt')
python .\pico\tools\audit_qtimer_bridge.py --before (Join-Path $save 'before.txt') --csv (Join-Path $save 'k0.csv') --after (Join-Path $save 'after.txt') --output (Join-Path $save 'audit.json')
if ($LASTEXITCODE -ne 0) { throw 'QTIMER audit failed' }
```

This session may refute the hypothesis. A promising
`QTIMER_CANDIDATE_REQUIRES_SOURCE_PROOF` result is only a new
**independent cross-clock consistency measurement**, not an approval
to shift `F` frame records or to enable P3 tracking corrections.
The old exact numbers are historic and must not be treated as
current clock offsets. Keep any generated timestamp recordings private.


For simpler Windows operation, the checked-in opt-in PowerShell 7 wrapper
`pico/tools/capture_qtimer_bridge.ps1` executes the exact private,
read-only sequence above (first runs six synthetic Python tests), and
prints the JSON audit plus output directory:

```powershell
cd C:\Dev\PicoLHSync
git switch feature/pico-support
git pull --ff-only
pwsh -NoProfile -File .\pico\tools\capture_qtimer_bridge.ps1
```

Use `-Seconds 20` for a longer interval. The wrapper does not copy
private files to GitHub or Google Drive, and does not alter the normal
Pico reader's live frame stream. The QTIMER hypothesis only strengthens
if both dumpsys snapshots bracket the K0 producer BOOTTIME epoch,
their QTIMER offset is stable, and all four camera gaps give plausible
positive apparent lag. Any mismatch is diagnostic evidence against
the current interpretation, not an invitation to fit another offset.



### P2 live in-session QTIMER ↔ K0 measurement — 2026-10-16, 20:46 local

The owner ran `pico/tools/capture_qtimer_bridge.ps1` using PowerShell 7.6.6,
the Android SDK Java 8 reader build and four live K0 memory rings. This time
the old +4.736 s image-vs-BOOTTIME offset was compared against *two bracketing
PVR QTIMER readings on the same active device session*, rather than crossing
older recordings or regressing asynchronous Java probe clocks.

**Execution evidence:**
- Six synthetic `pico.tests.test_qtimer_bridge` tests: **6/6 PASS**.
- `javac`, `d8`, reader JAR build and ADB push: **PASS** (one harmless
  Java 8 bootstrap-classpath warning).
- Four K0 cameras `C0, C3, C4, C5`: **301 completed frames each**
  over 12 s, 1,204 total.
- `pvr_boot_brackets_k0_write_epoch: true`.
- PVR `QTIMER − BOOTTIME`: **+4746.502697 ms before**,
  **+4746.502545 ms after**, delta **−0.000152 ms** across session
  (0.152 µs), central estimate **4746.502621 ms**.
- `PVR BOOTTIME − MONOTONIC`: **+18618216.259970 ms before** and
  **+18618216.260022 ms after** (this session's suspend-dependent
  separation, NOT transferable to another reboot/sleep state).

| K0 Binder ID | Frames | AImage +122 minus producer BOOTTIME +84 | QTIMER-hypothesis producer lag |
| --- | ---: | ---: | ---: |
| C0 | 301 | 4736.679575 ms | +9.823046 ms |
| C3 | 301 | 4736.438846 ms | +10.063775 ms |
| C4 | 301 | 4736.541759 ms | +9.960862 ms |
| C5 | 301 | 4736.268115 ms | +10.234506 ms |

The oldest separate PVR dump (2026-10-13) independently had
`QTIMER-BOOTTIME = +4746.402784 ms`: just **0.099837 ms**
different from the central 2026-10-16 measurement, but different
sessions/times, and the variation must not be treated as independently
calibrated inter-session clock drift.

The data **strongly corroborate** an internal native QTIMER-domain
image-stamp interpretation. It is consistent with an approximately
10ms acquisition-to-ring-write interval for all four cameras and
explains the 4.736s sign/magnitude without inventing a physical future
exposure. **However** numerical consistency alone cannot establish:
(1) the exact native clock function used to generate AImage timestamp,
(2) whether the PVR `qtimer` field uses identical clock conventions,
(3) the true sensor exposure/rolling-shutter time, or (4) the PICO Connect
/ SteamVR HMD-pose clock conversion.

Report `status=QTIMER_CANDIDATE_REQUIRES_SOURCE_PROOF` is correctly
fail-closed; ALL live-correction flags remain false. Owner's
diagnostics are PRIVATE at
`C:\Dev\PicoLHSync\pico\build\qtimer-p2-private-20261016-204644`
(`before.txt`, `k0.csv`, `after.txt`, `audit.json`).
No raw device timestamp recordings or factory calibration were
uploaded to the public repository.

**Next action:** static, offline firmware-level falsification of the
native image timestamp source and any QTIMER/BOOTTIME converter. Use
the already identified `libpvrtrackingcamera.so`, `libpvrtrackingservice.so`
and if necessary the proprietary QuickCamera service/libraries, without
opening another camera or injecting into SLAM. Do NOT subtract the
session-specific `4746.502621ms` in PFR1/F or tracking: timestamp
source and pose/exposure semantics are still blocked.


### P2 QTIMER static evidence collection (after 2026-10-16 paired test)

The paired QTIMER result warrants **static native call-site verification**
before touching any live timing code. Public Android Camera HAL metadata
specifies that `android.sensor.info.timestampSource=REALTIME` must use
BOOTTIME (see
https://android.googlesource.com/platform/system/media/+/528a4e2245ab7b0e5f323290a2c501d5d65c704f/camera/docs/metadata_definitions.xml).
The historical vendor PVR stream matching QTIMER numerically does not
remove this **contract discrepancy**. A possible vendor timestamp-domain
bug, distinct QuickCamera path, or custom conversion must be traced;
do not silently reinterpret the advertised REALTIME characteristic.

An opt-in PowerShell 7 collector
`pico/tools/collect_pvr_clock_static.ps1` pulls exactly the historical
`libpvrtrackingcamera.so` and `libpvrtrackingservice.so` from
`/system/lib64` or `/vendor/lib64` into a **new private local folder**.
Before using historical virtual addresses, it enforces the previously
measured October 13 ELF SHA256 values. With the already installed Android
NDK's `llvm-objdump`, it extracts only five bounded disassembly windows
surrounding known frame timestamp call/copy operations, together with
clock API imports and a short `clock-call-edges.txt`. It does not open
cameras, execute code in vendor processes, modify system files, install
Magisk, inject libraries, or upload proprietary binaries.

```powershell
cd C:\Dev\PicoLHSync
git switch feature/pico-support
git pull --ff-only
pwsh -NoProfile -File .\pico\tools\collect_pvr_clock_static.ps1
```

If firmware/library hashes differ, the collector intentionally stops
without applying old disassembly offsets. The narrow call-site extracts
will confirm the historical K0 propagation and identify the *next*
HAL/QuickCamera function to inspect, but cannot alone prove the device
timer source if it is created deeper in the vendor HAL. In particular,
QTIMER is a hypothesis **not** a ready-to-deploy timebase conversion.
All observations remain private; report only the text manifest and
selected call edges to continue the analysis. P2 OBSERVE ONLY gates stay
enforced.


### P2 external cross-check: Qualcomm QTIMER camera path and PICO internals — 2026-10-16

A targeted research log is checked in at
[`pico/research/P2-Qualcomm-QTIMER-Camera2-References-20261016.md`](research/P2-Qualcomm-QTIMER-Camera2-References-20261016.md).
Its most relevant findings: open Qualcomm downstream camera kernel code
reads 19.2 MHz CSID QTIMER start-of-frame registers and explicitly
builds a BOOTTIME-domain camera timestamp; other Qualcomm HAL source
has separate ISP BOOTTIME / display MONOTONIC offset handling, so a
native camera clock conversion is established prior art. One Android
developer reported a REALTIME image timestamp not matching
CLOCK_BOOTTIME (no corresponding verified fix/magnitude). A separate
PICO-specific reverse engineering project identifies CameraService
ID 5 (400x1600) as the inward-facing eye/face sensor stream through
OV680, matching the owner's Camera2 enumeration.

**Nothing publicly found establishes the exact Pico 4 Pro +4.746s
timestamp fault.** The new references prioritize investigating the
saved firmware's `AImage_getTimestamp` and nearby `systemTime`
call at 0x3a8bc / 0x3a8d8, and lower Camera HAL source semantics.
The exported `SnsLowLatBridge::qtimer_get_time_ns` and
`pxr::TimeSynchronization::sensorToSystemTime` are notable clock
functions, but their relationship to K0 cameras is not established.
No physical sensor exposure timing or PC pose clock is certified;
no live offset changes permitted.


### P2 Quest Pro clock implementation comparison — 2026-10-16

The *actual original upstream* `CreoleVR/QuestLHSync`
`magisk/src/lhsight.c` uses `clock_gettime(1) = CLOCK_MONOTONIC`
when the polling loop notices a changed tracking-camera buffer.
The Quest Pro's `F` network timestamp is that **detection time**,
not a verified camera-exposure timestamp. Upstream
`FrameGrid::Lag` subtracts the polling phase, `Clock::AddPing`
maps headset MONOTONIC to PC QPC, and the HMD pose history records
`QpcNow() + poseTimeOffset`. The time alignment `expo_`
initially defaults to 18ms and is motion-learned per streamer;
it must not be mistaken for a universal camera exposure delay.

Two important upstream **other-headset** variants use genuine
frame-derived timestamps: Steam Frame converts its V4L2 timestamp
from `MONOTONIC_RAW` if applicable, and the newer Galaxy XR
`gxr_sensor` backend advertises sensor BOOTTIME already converted
to daemon MONOTONIC. Both set `exact_time_=true` once backend
timestamps are considered aligned. They are a relevant architectural
example for **future Pico P2**, not an authorization to enable it now.
Meta's own Quest Pro camera firmware may itself implement QTIMER or
another hardware clock, but its clock origin cannot be deduced from
QuestLHSync source; the app simply does not expose such timestamps.

In our fork `pico/src/lhsight_pico.c`, the `PFR1` records include
both raw `vendor_ts` and MONOTONIC `copied_ns`; the transmitted
`F` timestamp currently uses **`copied_ns / 1000`** (conservative
fallback), while `Optics::LoadPico` sets `exact_time_=false`
and requires `mapping_verified && pose_verified`. This is the
correct blocked behavior while K0 vendor timestamp domain remains
uncertified.

Detailed source path and source links are documented in
[`pico/research/P2-QuestPro-Vs-Pico-Clock-20261016.md`](research/P2-QuestPro-Vs-Pico-Clock-20261016.md).

**New decisive disassembly (SHA-pinned firmware, 2026-10-16):**
in `CameraReader::OnImageCallback`, `AImage_getTimestamp`
returns an image-derived value loaded into `x22`, and a separate
`systemTime(4)=SYSTEM_TIME_BOOTTIME` call returns `x0` moved
to `x6`. Immediately before the same helper call
`0x3a8f4`, arguments `x5=x22` and `x6=BOOTTIME`.
No arithmetic bridges them in the shown basic block. The service
function `SnsLowLatBridge::qtimer_get_time_ns` reads ARM64
`CNTVCT_EL0` and `CNTFRQ_EL0` (with nanosecond conversion),
which is a real architectural hardware timer source in this
exact Pico firmware but is NOT yet traced into Camera2 AImage.

To independently verify that `dumpsys pvrtracking` QTIMER refers
to the same architectural timer, a fully separate opt-in NDK
`--qtimer-counter-only` executable was added. It reads only
CNTVCT/CNTFRQ + BOOTTIME + MONOTONIC, not the camera or tracking
buffers, with all live-correction flags false. PowerShell 7 runner:

```powershell
cd C:\Dev\PicoLHSync
git switch feature/pico-support
git pull --ff-only
pwsh -NoProfile -File .\pico\tools\capture_qtimer_counter.ps1
```

This prints two small PVR clock lines enclosing eight hardware-clock
samples. In a correct match, the hardware `cntvct_minus_boot_ns`
will closely follow PVR `qtimer - boottime`; do not compare
their absolute tick readings across separately restarted devices,
sleep states or firmware builds. This new probe has NOT been compiled
or executed on the owner's Windows/Android devices as of this commit.
No time offset is installed, all P2/P3 gates remain OBSERVE ONLY.


### P2 QTIMER clock owner measurement: CNTVCT matches `dumpsys qtimer` — 2026-10-16

The owner's first real `capture_qtimer_counter.ps1` run **compiled
with NDK 27.2 and `-Werror`**, pushed, chmod'd and executed
the read-only counter probe; 8/8 hardware-counter samples succeeded.
`CNTFRQ_EL0 = 19,200,000 Hz`. PVR `dumpsys` before and after:

```text
before: BOOTTIME=258399539184385 MONOTONIC=239781322924363 QTIMER=258404285687656
after:  BOOTTIME=258400733317457 MONOTONIC=239782517057644 QTIMER=258405479820937
```

Their PVR QTIMER-minus-BOOTTIME values were **4746503271 ns**
and **4746503480 ns**. The hardware `CNTVCT * 1e9/CNTFRQ`
minus BOOTTIME values in the eight-sample run were
`[4746502933,4746502907,4746503037,4746502986,4746503012,
4746502933,4746503037,4746503064]` ns, median **4746502999 ns**,
range **157 ns**, within **272–481 ns** of the PVR readings.
Both are independently time-bracketed using standard POSIX clocks.
This is conclusive practical confirmation that Pico PVR's
`qtimer` is the architectural CNTVCT-derived nanosecond clock
(on this firmware, in this session). It is NOT by itself proof that
the **Camera2 AImage** timestamp was generated from that clock.

The user asked to continue toward better physical frame timestamps
than the original Quest Pro poll-time approach. The original upstream
`CreoleVR/QuestLHSync` Quest Pro backend uses buffer detection
`CLOCK_MONOTONIC` and grid-based poll-lag modeling; our fork
currently similarly emits `copied_ns /1000` in `F` and keeps
`exact_time_=false`. A lower-latency sensor-clock approach is
potentially better but only once its source/epoch and pose clock
semantics are independently verified, as in the upstream
Steam Frame/Galaxy XR path.

### P2 shadow QTIMER→MONOTONIC simulation — offline-only implementation

New `pico/tools/audit_shadow_k0_time.py` does a testable candidate
**per-frame** clock-domain mapping without changing live data:

```text
At the K0 row's measured BOOTTIME t, interpolate between bracketing
PVR snapshots:
  q_minus_mono(t) = qtimer(t) - monotonic(t)
  b_minus_mono(t) = boottime(t) - monotonic(t)
  candidate_image_mono_ns = K0_vendor_ns - q_minus_mono(t)
  producer_write_mono_ns = K0_ring_ts84_ns - b_minus_mono(t)
  candidate_producer_lag = producer_write_mono_ns - candidate_image_mono_ns
  candidate_reader_age = K0_java_read_mono_ns - candidate_image_mono_ns
```

No values are written to LHSync F records, SteamVR poses, Pico clocks,
calibration files or on-device modules. This merely replays the
already-recorded private P2 data, using integer nanoseconds to avoid
loss of precision on large monotonic epochs. It validates:
- the two PVR clock snapshots bracket every K0 sample,
- all four camera sequences are monotonic, odd and complete,
- raw `slot+114 == slot+122`, when the column exists,
- PVR QTIMER offset drift within 2ms,
- the modeled producer lag lies within 0..100ms,
- the modeled Java reader age lies within 0..2s,
- K0 Java BOOTTIME-minus-MONOTONIC agrees within 1ms with
  the interpolation from PVR dumpsys clocks.

These are **safety and plausibility gates** (arbitrary engineering
bounds), not a clock-source or exposure-epoch certificate.
All reports permanently set
`live_lighthouse_correction_allowed=false`;
any failed gate yields `QTIMER_SHADOW_REJECTED_OR_INCOMPLETE`.
Seven synthetic unit-test cases are included (pass/fail,
outside bracket, high drift, wrong slot timestamp, excessive lag,
bad reader age, signed interpolation).

No new HMD capture is necessary. Reuse the existing owner-recorded
private folder `pico/build/qtimer-p2-private-20261016-204644`:

```powershell
cd C:\Dev\PicoLHSync
git switch feature/pico-support
git pull --ff-only
pwsh -NoProfile -File .\pico\tools\replay_shadow_k0_time.ps1
```

The wrapper runs the previous six plus new seven synthetic tests,
chooses the newest `qtimer-p2-private-*` recording, and writes
`shadow.json` into that **private local folder**. The new code has
not been run on the owner's Windows machine yet. Do not change
`pico/src/lhsight_pico.c` to use raw, shadow, or corrected vendor time
or set `exact_time_=true` until physical exposure-source proof and
independent SteamVR-pose timestamp alignment are established.


### P2 shadow replay hotfix — 2026-10-16

The owner's first `replay_shadow_k0_time.ps1` run exposed a
**code-only key mismatch** in the new offline analyzer: the established
`parse_pvr_snapshot()` returns `monotime_ns`, whereas shadow
projection looked up `monotonic_ns`. Six original QTIMER tests
passed; five of seven new shadow tests failed with `KeyError`,
and the PowerShell runner correctly stopped **before producing any
shadow output**. This is not evidence against the physical QTIMER
hypothesis or an HMD failure.

Fixes:
1. Use the canonical PVR dictionary key `monotime_ns` consistently
   in `pico/tools/audit_shadow_k0_time.py`.
2. Launch the offline tool via
   `python -m pico.tools.audit_shadow_k0_time` from the checkout
   root to ensure absolute `pico.tools.*` imports resolve
   portably under PowerShell 7.
3. Add a regression test of the upstream snapshot parser's key;
   expected offline suite is **14** tests (6 existing + 8 new).

The fixed suite still needs to be executed on the owner's Windows
checkout. No K0 timestamps, decoder formats, hardware readers,
installer modules, driver timing, or live correction flags were
modified.

```powershell
cd C:\Dev\PicoLHSync
git pull --ff-only
pwsh -NoProfile -File .\pico\tools\replay_shadow_k0_time.ps1
```



### P2 shadow replay: owner real 1,204-frame PASS — 2026-10-16

The owner completed `pwsh -NoProfile -File pico/tools/replay_shadow_k0_time.ps1`
after the `monotime_ns` compatibility fix. **14/14** synthetic
unit tests passed. Private `shadow.json` was produced locally.
All **1204/1204** existing completed K0 frames fell within the
bracketing PVR clock sample epoch, with four camera runs of 301 frames
each. The offline result:

```text
status=QTIMER_SHADOW_PLAUSIBLE_UNVERIFIED
PVR qtimer-minus-monotonic drift over the bracket: -0.000100 ms
sensor exposure timestamp verified=false
live Lighthouse correction allowed=false
```

| K0 | Candidate producer-write lag median / p90 / max (ms) | Candidate Java reader age median / p90 / max (ms) | Java vs PVR BOOTTIME−MONO residual max (ms) |
|---|---|---|---|
| C0 | 9.823055 / 9.879567 / 10.348226 | 55.108239 / 58.971543 / 86.868722 | 0.011014 |
| C3 | 10.063757 / 10.209562 / 10.682601 | 55.486178 / 59.363026 / 86.994712 | 0.010309 |
| C4 | 9.960923 / 10.104987 / 10.831299 | 55.585994 / 59.554484 / 87.055232 | 0.000597 |
| C5 | 10.234538 / 10.374796 / 11.181143 | 55.728870 / 59.725968 / 87.111899 | 0.000676 |

These model outcomes **are consistent** with a ~10 ms image
timestamp-to-producer-ring-write interval followed by a roughly
40–45 ms delay before this observer reads the preceding completed
frame. The `--clock-scan` intentionally skips the newest ring slot,
so **55 ms is not proof of camera exposure latency nor inherent
SteamVR end-to-end latency**. At the observed 25 fps, one K0
frame period is ~40 ms. All of these estimates are conditional
on the QTIMER clock-domain hypothesis.

Important distinguishers: (a) *clock-domain conversion precision*
has strong numerical evidence, (b) *physical exposure timestamp source*
still lacks native HAL-level proof, and (c) *end-to-end pose correction
accuracy/latency* also depends on camera-to-HMD mapping, optical
calibration, scene detection and PC pose clock. It is too early
to claim achieved Quest Pro superiority. The original Quest Pro
LHSync F timestamps are detection/poll times; Pico may provide
more accurate frame chronology, but not necessarily faster
frame delivery.

No `F` stream, `pico_lhsight`, `exact_time_`, PICO
calibration or SteamVR driver has been modified. Private evidence
retained at
`pico/build/qtimer-p2-private-20261016-204644/shadow.json`.
Next evidence should be native timestamp producer provenance and
physical camera→K0 mapping, not another synthetic clock fit.


### Next native source proof step — offline only, after 1,204-frame shadow pass

`pico/tools/trace_k0_frame_provenance.ps1` has been added to
inspect the previously saved, SHA-256 pinned ELF binaries without
connecting to the Pico headset. It focuses on four bounded ARM64
ranges: (1) AImage image stamp and separate systemTime(4) setup;
(2) `CameraReader` outlined helper at 0x3b4c0 that receives image
timestamp `x5` and BOOTTIME `x6`; (3) QuickCamera metadata dequeue;
(4) K0 DataBuffer copying/unlocking. The script stops if hashes
differ, retains all extracted disassembly in the existing
`p2-static-clock-private-*` local folder, and prints bounded
text excerpts. Do not upload binaries or calibration files.

```powershell
cd C:\Dev\PicoLHSync
git pull --ff-only
pwsh -NoProfile -File .\pico\tools\trace_k0_frame_provenance.ps1
```

Success will help identify where the two timestamps flow after
`CameraReader::OnImageCallback`. It is **not** direct evidence of
the actual QTIMER-origin in the camera HAL. That requires further
static provenance or an independent physical event-time check.
The script has not been executed against the owner's saved ELF files
yet; the existing read-only K0/SteamVR safety gates remain unchanged.


### P2 timestamp provenance: corrected interpretation of owner's native disassembly — 2026-10-16

The owner ran `trace_k0_frame_provenance.ps1` on the same two
SHA-pinned Pico OS 5.11.2 ELF libraries. All four original bounded
extractions succeeded. **Two earlier analyst assumptions were wrong:**

1. `CameraReader::OnImageCallback` calls `AImage_getTimestamp`
   at `0x3a8bc`, retrieves that value in `x22`, then calls
   `systemTime(4)` (BOOTTIME) at `0x3a8d8`. Registers `x5=x22`
   and `x6=BOOTTIME` are forwarded into the call at `0x3a8f4`.
   **That call targets `0x3b4c0`, a compiler-outlined
   `snprintf`/varargs formatting helper calling
   `__vsnprintf_chk@plt` at `0x3b540`**, *not* a timestamp
   conversion, frame dispatcher, or camera synchronization routine.
   The two values are apparently passed for diagnostic formatting;
   the surrounding format string and subsequent call sites still
   require inspection. A following `ldr x5, [sp,#8]` at `0x3a934`
   reuses the raw image timestamp in a **different branch**, which
   is an important future lead.
2. The observed direct metadata copies from `pvr_frame_item_t+0x18`
   to buffer `+0x11`, and `pvr_frame_item_t+0x20` to buffer
   `+0x19`, appear at `0xacd6c–0xacd78` in
   `CameraManager::writeToExpSm`. That is the **separate exposure
   shared memory** path. It does *not* prove which offsets are
   actually written in the main K0 image frame ring. The main image
   ring path is `CameraManager::writeToSm` at `0xab634`
   and has to be inspected independently.

The proprietary QuickCamera path **is also distinct**:
`PvrCameraFrame::processCameraFrame` at `0x66634` calls
`QuickCameraClient::DeQueueFrame` with an output `FrameMetaDate*`
at `sp+0x10`. Its metadata fields are copied into a local frame
descriptor before virtual callback invocation. This route may be
different from Android `AImageReader`. No evidence in the
narrow extract yet establishes **which producer branch** supplied
the K0 `slot+114/slot+122` timestamps. The observed 1204-frame
QTIMER shadow consistency is valid empirical evidence, but cannot
be promoted into direct source-level provenance.

The hash-pinned, **offline-only**
`pico/tools/trace_k0_frame_provenance.ps1` has been corrected to
label the `0x3b4c0` helper as varargs formatting rather than time
conversion, distinguish `writeToExpSm` from the real `writeToSm`,
and include complete bounded disassembly of the following three
high-value functions:

- `CameraReader::OnImageCallback` after the diagnostic formatting
  (`0x3a928–0x3aa98`), for the raw timestamp's actual dispatch.
- `CameraManager::onFrameAvailable`
  (`0xaa8f4–0xaac50`), for frame metadata routing.
- `CameraManager::writeToSm` (`0xab634–0xab988`), for the
  actual image ring record construction.

It also covers `PvrImageReaderListener::processFrame`, QuickCamera
metadata assembly and the `0x254d7` diagnostic format string.
These are narrow static offsets for the verified exact firmware SHA,
NOT a portable ABI. The script does no ADB/device operations.

Next local command (requires no headset):

```powershell
cd C:\Dev\PicoLHSync
git pull --ff-only
pwsh -NoProfile -File .\pico\tools\trace_k0_frame_provenance.ps1
```

The revised extraction has not yet been run on the owner's PC.
Until the two producer branches and their frame item metadata
are unambiguously traced, do NOT mark K0 timestamp as verified
QTIMER or switch LHSync to `exact_time`. Continue OBSERVE ONLY.


### P2 definitive K0 main-ring timestamp copy and QuickCamera duplication lead — 2026-10-16

The owner ran the expanded, SHA-pinned **offline ELF disassembly**
(`trace_k0_frame_provenance.ps1`), with all previous ADB and
clock-projection safety gates intact. This new trace closed a critical
misattribution and materially advanced the producer provenance.

**The direct K0 image-ring copy is now verified in the exact
`libpvrtrackingservice.so` disassembly**, not merely in the
separate exposure ring. `PicoFrameReader.java` requests
`GetCameraShareMemory(cameraId, kind=0)`. In
`CameraManager::writeToSm(CameraInfo&, int kind, pvr_frame_item_t*)`,
`kind=0` selects main buffer `CameraInfo+0x98`, not the
exposure preprocessing/`writeToExpSm` path reserved for `kind=1`.
`x21` holds `pvr_frame_item_t*`; `x22` holds its locked K0
record's metadata body pointer:

```text
0xab7c0: ldp x12,x13,[x21,#0x18]   # frameitem +0x18, +0x20
0xab7cc: cmp x23,#0                # kind=0 sets x23=0
0xab7e0: csel x9,x12,x23,eq        # kind=0 => x9=x12
0xab7ec: stur x13,[x22,#0x19]     # K0 slot +122
0xab7f0: stur x9, [x22,#0x11]     # K0 slot +114
0xab7f4: ldr x9,[x21,#0x28]
0xab804: stur x9, [x22,#0x21]     # K0 slot +130
0xab800: add x23,x22,#0x59        # start of image pixel payload
```

The locked K0 record starts its item metadata body at **slot+97**,
independently corroborated by reader's slot+97 sensor id and
`PIXEL_OFFSET=186 = 97+0x59`. Thus producer struct fields
`+0x18,+0x20,+0x28` map exactly to observed
`K0 slot+114,+122,+130`. No epoch conversion is performed
**inside the main image-ring writer**. The 1,204-frame paired equality
`slot+114==slot+122` is a real observation about two producer
metadata fields and must be traced *upstream*, not credited to
`AImage_getTimestamp` without further evidence.

**A strong source-level explanation for that equality now exists
in the OTHER side of the firmware**. In
`libpvrtrackingcamera.so`,
`PvrCameraFrame::processCameraFrame()` calls
`QuickCameraClient::DeQueueFrame(void**,FrameMetaDate*)`
at `0x66634`, with `FrameMetaDate` output at `sp+0x10`.
After success, the code:

```text
0x6667c: ldp x11,x10,[sp,#0x10] # first two 64-bit FrameMetaDate words
0x66680: add x1,sp,#0x40       # local pvr_frame_item_t body pointer
0x666a0: str x10,[sp,#0x70]    # local frameitem+0x30
0x666a8: stp x11,x11,[sp,#0x58] # local frameitem+0x18 and +0x20
```

This deliberately duplicates the **FIRST QuickCamera FrameMetaDate
64-bit word** into the **two exact timestamp slots** later copied
to K0 `+114` and `+122`, **if that QuickCamera-generated
frame is the active K0 producer**. The code-path attribution
and this hypothesis are substantially stronger than the old
approximate timestamp correlation; however, the actual matching
callback route still needs to be traced through
`PvrCameraFrame` virtual dispatch into the
`CameraManager::onFrameAvailable` consumer. The HAL/provider origin,
epoch and event represented by that first QuickCamera metadata
word remain **unverified**.

The separate `CameraReader::OnImageCallback` uses
`AImage_getTimestamp()` to order a queue/tree; there is no
justification to claim it writes to K0 merely because its
diagnostic `systemTime(4)` appeared nearby. The
`0x3b4c0` target is a **compiler-outlined printf varargs helper**,
confirmed by `__vsnprintf_chk`, not a synchronization routine.

**One tooling correction:** the previous PowerShell command
`llvm-objdump -s --start-address=0x254c0` produced a dump of
`.dynsym`, NOT the intended camera log literal from `.rodata`;
that result must not be interpreted. New offline stdlib
`pico/tools/elf_cstring_at_va.py` maps an ELF64 AArch64
virtual address via `PT_LOAD` file offsets, with bounds
and NUL checks, to inspect exactly the callback string at
`0x254d7`; it has five new synthetic tests.

The targeted next step is a **single offline source-branch audit**:

```powershell
cd C:\Dev\PicoLHSync
git pull --ff-only
python -m unittest pico.tests.test_elf_cstring_at_va -v
pwsh -NoProfile -File .\pico\tools\trace_k0_timestamp_producers.ps1
```

`trace_k0_timestamp_producers.ps1` is SHA-pinned to the same
local camera/service ELF files, extracts and displays:
(1) QuickCamera `FrameMetaDate`→frame-item construction;
(2) the AImageReader timestamp-tree/dispatch alternative;
(3) `PvrImageReaderListener` frame-item construction;
(4) the proven main K0 record writer;
(5) `onFrameAvailable` branches that invoke writer.
It stores bounded disassembly and does not use ADB or touch the
headset, calibration, private frame captures or driver.

**P2 gates remain unchanged:** QTIMER ↔ BOOTTIME ↔ MONOTONIC
consistency strong, native QuickCamera duplicate timestamp
construction now supported by static code, but K0 callback
producer origin and true optical exposure semantics still
unverified; do not enable `exact_time` or Lighthouse correction.


### P2 offline K0 third timestamp and virtual-callback audit — 2026-10-16

Owner completed the targeted static producer analysis. All five
`elf_cstring_at_va` synthetic tests **passed**. It verified the
QuickCamera `FrameMetaDate` first 64-bit word is duplicated at
`pvr_frame_item_t+0x18` and `+0x20`, with a subsequent virtual
callback at `0x666e0` carrying the assembled frame descriptor.
The main K0 `writeToSm` copies those struct offsets into
`slot+114/slot+122`. However, the **actual virtual callback
callee and active K0 producer** have not yet been identified
independently, so this remains a *conditional* complete path.

New important lead: `CameraManager::onFrameAvailable`
**calculates** `pvr_frame_item_t+0x28` at `0xaaeac`,
and the image writer copies that field to
`K0 slot+130`. The formula contains an arithmetic-shifted
half of a product, which might relate to an exposure or sensor
timing adjustment. **We have not established source operands,
units, clock epoch, or physical exposure semantics.**
The existing private 1,204-frame `--clock-scan` CSV already
contains `ring_ts130_ns`; a new capture is unnecessary.

A focused, fail-closed **offline comparison** and five synthetic
test cases are in `pico/tools/audit_k0_slot130.py` and
`pico/tests/test_k0_slot130.py`. The runner
`pico/tools/review_k0_slot130.ps1` reuses bracketing PVR
clock snapshots and K0 CSV from the earlier successful sample,
runs the previous 14 plus new 5 timing regression tests,
then reports +130 values near candidate QTIMER and/or BOOTTIME
epochs. Any interpretation is hypothetical and does not
authorize `exact_time` or live Lighthouse corrections.

```powershell
cd C:\Dev\PicoLHSync
git pull --ff-only
pwsh -NoProfile -File .\pico\tools\review_k0_slot130.ps1
```

Additional separate, optional offline auditor
`pico/tools/audit_k0_callback_dependencies.ps1` identifies
DT_NEEDED and dynamic symbols for the two already captured
vendor PVR ELFs, plus bounded ARM64 virtual callback and
alternative `AImageReader` paths. This should narrow the
QuickCamera library/provider origin for later static inspection;
it does not use ADB or execute code on the headset.

Source-level evidence, known limitations, commands, and gates:
[`pico/research/P2-K0-SourceAndSlot130-20261016.md`](research/P2-K0-SourceAndSlot130-20261016.md).
All newly added tests/tools are **not yet run** on the owner's
Windows checkout. Existing PFR1, native reader, camera metadata,
driver optics, and live tracking code remain unchanged.


### P2 +130 native correction: measured and formula-confirmed — 2026-10-16

Owner's `review_k0_slot130.ps1` **passed 19/19**
synthetic unit tests. From the 1,204 real K0 frames:
`slot+130` was nonzero for every frame, in the same QTIMER-like
epoch as `slot+122` for all four camera channels (301/301 each),
never numerically equal to `slot+122`, and
`median(slot130 - slot122)=-225997 ns` for
C0,C3,C4,C5 individually. It is not BOOTTIME-like.

A new, precise source-level result from the owner's
`libpvrtrackingservice.so` disassembly:

```text
x6  = frame_item+0x20             (K0 slot+122)
x8  = sign_extend32(frame_item+0x14)
x10 = *(manager + cameraIdx*0x320 + 0x330)
x9  = *(manager + cameraIdx*0x320 + 0x338)
slot130 = x6 - 52000 - x9 - ((x10*x8) ASR 1)
```

At `0xaaeac` the computed result is placed into
`frame_item+0x28`; at `0xaaef4` `writeToSm`
receives the frame and copies `+0x28` to K0 `slot+130`.
This is a **deliberate native-adjusted frame timestamp**,
not an arbitrary second clock or a writer artifact. Its
physical semantics (SOF, rolling shutter, center of exposure,
another camera event) have NOT been verified, and the shared
`-225997 ns` medians do NOT imply all per-frame differences
are constant.

Also owner verified the camera ELF directly depends on Pico's
three QuickCamera HIDL libraries
`pico.camera.quickcamera.common@1.0.so`,
`quickcameramodule@1.0.so` and
`quickcameradevice@1.0.so`. Service depends on camera ELF.
`PvrCameraFrame` invokes an image-listener vtable function
at `0x666e0`; the actual target is unresolved. The
`CameraManager::CameraImageListener` vtable is present in the
service, requiring ELF relocations and listener registration
to establish the full QuickCamera→K0 producer chain.

Detailed evidence:
[`P2-K0-SourceAndSlot130-20261016.md`](research/P2-K0-SourceAndSlot130-20261016.md).

Next, **offline only**: determine whether the ~226us correction
varies by frame and inspect the native per-camera config and
callback-table source with the new SHA-pinned analyzer:

```powershell
cd C:\Dev\PicoLHSync
git pull --ff-only
pwsh -NoProfile -File .\pico\tools\trace_k0_slot130_parameters.ps1
```

This writes `slot130-variation.json` alongside existing private
K0 CSV, prints bounded source excerpts and saves ELF disassembly
locally. Five new synthetic tests accompany it; they are
**not yet executed** on the owner's Windows machine.
All P2 safety gates remain OBSERVE ONLY;
`exact_time=false`, no live driver clock conversion.


### P2 observation: invariant K0 +130 delta and resolved listener vtable — 2026-10-16

The owner's next offline check passed 5/5 new tests. All
301 completed frames on each C0, C3, C4 and C5 (1,204 in total)
had `slot122 - slot130 = 225997 ns` **exactly**,
with one unique value and zero adjacent changes per camera.
This was constant throughout the recorded 12 seconds;
do NOT treat it as a general fixed exposure correction
across changing camera conditions, firmware and devices.
The native formula still includes per-camera parameters
and a frame-specific metric.

The exact `CameraManager::CameraImageListener` ELF
vtable relocation at `0x15e6b0` resolves to
`onFrameAvailable(pvr_frame_item_t*)` at `0xabbfc`.
It is consistent with the QuickCamera virtual callback
offset `+0x10` after `PvrCameraDevice::setPvrImageListener`
stores an image-listener shared pointer at device+0x30.
The actual producer/listener instance for observed K0
cameras is **not yet proven**.

Research detail:
[`P2-K0-SourceAndSlot130-20261016.md`](research/P2-K0-SourceAndSlot130-20261016.md).
For the current static disassembly and saved CSV audit,
Pico 4 Pro may safely remain **powered off** while the
owner uses Pimax Crystal. No ADB/SLAM/live HMD access
is needed until physical-event and PC-pose tests resume.
OBSERVE ONLY; `exact_time=false`; no driver changes.


### P2 listener-wiring reverse XREF — Pico powered off — 2026-10-16

The previous owner's 1,204 completed K0 frames establish a
**precisely invariant 225,997-ns subtraction** in `slot130`
relative to `slot122` for the measured recording, and SHA-pinned
ELF relocations establish a real service
`CameraManager::CameraImageListener::onFrameAvailable` at
`0xabbfc` through the virtual table entry at `0x15e6b0`.
QuickCamera invokes virtual listener entry +0x10 with a native
`pvr_frame_item_t` descriptor and the setter stores a
shared listener in `PvrCameraDevice+0x30`. This is an ABI-level
match, **not yet proof of listener registration on the
four active K0 PvrCameraDevice instances**.

The next concrete step is to locate and attribute the
**registration call sites and constructor/initializer stores**
inside the already archived, SHA-pinned native ELF code.
New `pico/tools/audit_k0_listener_xrefs.py` can consume complete
LLVM disassembly on Windows, verify native service vtable
relocations and enumerate the enclosing function names for
`setPvrImageListener` call instructions and
`CameraManager` per-camera `+0x330/+0x338` config reads/writes,
saving full text locally while printing only a compact index.
Six new synthetic parser tests are provided; all require
execution on the owner's Windows checkout.

Use **offline only**, Pico may remain powered off:

```powershell
cd C:\Dev\PicoLHSync
git pull --ff-only
pwsh -NoProfile -File .\pico\tools\trace_k0_listener_xrefs.ps1
```

The script does not call ADB, Android camera APIs, SLAM,
SteamVR or any executable from the vendor firmware. It only
verifies hashes of private captured libraries and invokes
Android NDK `llvm-objdump`/`llvm-readelf`.
Full report:
`pico/build/p2-static-clock-private-*/p2-listener-cross-references.txt`.
Source-level status and remaining gates:
[`P2-K0-SourceAndSlot130-20261016.md`](research/P2-K0-SourceAndSlot130-20261016.md).
No physical exposure timing or K0-to-PC pose clock
verification has yet taken place, so
`exact_time=false`, `OBSERVE ONLY`, and Lighthouse
live offset/correction gates remain closed.


**New P2 source-derived simplification (2026-10-16):** native
`CameraManager::writeToSm` stores `frame_item+0x14`
in K0 `slot+110`. The Java `--clock-scan` only
accepts and then revalidates slots for which
`slot+110 == 4`; hence the native correction operand
`E=4` for every accepted frame in the archived sample.
Combined with the exact observed `slot122-slot130=225997ns`,
the native source equation simplifies to
`slot130=slot122-52000-A-2B`, implying
`A+2B=173997ns` for the observed camera configuration.
Java already calls this integer the K0 `exposure`
setting; it is **not proved to be a physical duration**,
and the `+130` epoch's exact exposure event semantics
remain unknown. The code comment was clarified; frame
selection and output are unchanged.

A new offline SHA-pinned native callsite analyzer has
been committed as
`pico/tools/trace_k0_listener_xrefs.ps1`, using
`pico/tools/audit_k0_listener_xrefs.py` and six
new synthetic parser tests. This targets the remaining
callback registration and A/B initializer XREFs; it has
not been executed on the owner's Windows checkout.
The Pico can remain powered off while the owner uses Pimax.
No SteamVR, ADB, device or live LHSync interaction.


### P2 cross-reference follow-up, with Pico powered off — 2026-10-17

The owner ran `trace_k0_listener_xrefs.ps1`: **6/6 tests
PASS**, SHA-pinned camera/service static audit completed,
service `CameraImageListener` callback vtable confirmed.
The key new static edge is a direct
`PvrQuickCamera::setPvrImageListener` wrapper call
to `PvrCameraDevice::setPvrImageListener` at `0x63a1c`;
this narrows but does not yet certify actual active K0
listener installation. The service had no *direct* setter
call-site match; virtual dispatch remains possible.

Unfiltered references to offsets +0x330/+0x338
contained false-positive other C++ object fields.
They have **not** yet proved the values of camera timing
parameters A/B. The next hash-pinned bounded offline
inspection is:

```powershell
cd C:\Dev\PicoLHSync
git pull --ff-only
pwsh -NoProfile -File .\pico\tools\trace_k0_listener_wiring_parameters.ps1
```

This command reruns the updated **7** listener parser tests
(including a new wrong-relocation-target rejection), then
prints only focused snippets covering:
`CameraManager` initialization/parameter reads,
`CameraImageListener` callback forwarding,
`PvrQuickCamera` setter delegation, and
`PvrCameraDevice` setter. Text results are saved
only in the existing private offline firmware folder.
No Pico, ADB, camera capture, SteamVR or driver changes.
Source/ABI proof still differs from runtime active K0
producer ownership, and `exact_time=false` is unchanged.


### P2 proven callback-forwarder / ELF switch table follow-up — 2026-10-17

After pulling `1330c6f`, owner successfully ran
`trace_k0_listener_wiring_parameters.ps1`; **7/7**
synthetic tests and hash-pinned static disassembly
completed. It established `CameraManager::CameraImageListener::onFrameAvailable`
at `0xabbfc` forwards each frame directly to
`CameraManager::onFrameAvailable` and contains explicit
routing code for camera ids `0,3,4,5`.
A compact four-byte switch table at ELF VA
`0x73a10` routes native descriptor byte `+0`
for indices `0..3`; its actual four bytes still
need to be read. `PvrQuickCamera` delegates
listener installation to `PvrCameraDevice`,
where the shared listener is stored at
`device+0x30`. Actual **runtime K0 producer binding**
is still unverified.

Also corrected an important generic-offset fallacy:
`CameraManager::setCameraParameters` accesses
global `0x163000 + 0x330/+0x338` addresses and
those must not be identified with indexed
`CameraInfo+0x330/+0x338` parameters without
base-register proof. The constructor actually
has `x23=x28-0x300` around its store site, so
`[x23+0x330/338]` are locally
`[x28+0x30/38]`; the `x28` owner and
indexing remain under investigation.

New offline tools
`pico/tools/audit_k0_listener_table.py` and
`pico/tools/trace_k0_constructor_dispatch.ps1`
decode the bounded jump table and collect
constructor/base-register evidence from the
saved SHA-256-pinned service ELF; six new
synthetic tests were added.

```powershell
cd C:\Dev\PicoLHSync
git pull --ff-only
pwsh -NoProfile -File .\pico\tools\trace_k0_constructor_dispatch.ps1
```

The new tooling has not run on owner's Windows yet.
It is read-only, no ADB, new captures, tracking,
live camera correction or SteamVR interaction.
Full proof tracking in
[`P2-K0-SourceAndSlot130-20261016.md`](research/P2-K0-SourceAndSlot130-20261016.md).


### P2 verified CameraImageListener jump table and 7-slot camera constructor — 2026-10-17

Owner completed `trace_k0_constructor_dispatch.ps1`
with **13/13 tests passing**. The actual
`CameraImageListener` switch bytes from the hash-pinned
`libpvrtrackingservice.so` at `VA 0x73a10`
are `00 07 0a 0d`. This independently maps
native callback descriptor indices `0,1,2,3`
to `CameraManager` camera IDs `0,3,4,5`
by four concrete branch addresses, matching the
existing K0 sensor set. Runtime listener assignment
and physical/factory extrinsic mapping remain
separate unverified links.

The native `CameraManager` constructor initializes
seven blocks at 800-byte stride using
`x23=this-0x2c0`, writes a zero word
to `x23+0x330=this+0x70` and the raw
8-byte `d8` value to `x23+0x338=this+0x78`;
both repeat at `+i*0x320`.
It loads `d8` from ELF rodata VA `0x736b0`.
**These are not yet proven to be the same A/B
actually read by the frame-timing code**, which
uses `x19+camIdx*0x320+0x330/0x338`.
The frame callback `x19` base still needs
verification. The observed 1,204-frame constraint
`A+2B=173997ns` stands for the runtime
fields but does not independently identify them.

New offline read-only, SHA-pinned inspection
`pico/tools/trace_k0_clock_base.ps1`
runs 12 tests (6 new constructor-literal, 6
existing listener-table) and reads the exact
rodata constant bits plus the onFrameAvailable
prologue to resolve register bases. No Pico
or ADB required:

```powershell
cd C:\Dev\PicoLHSync
git pull --ff-only
pwsh -NoProfile -File .\pico\tools\trace_k0_clock_base.ps1
```

It has **not yet run on the owner's Windows**.
There are no live clock, camera, SLAM,
SteamVR or `exact_time` changes.
Full audit:
[`P2-K0-SourceAndSlot130-20261016.md`](research/P2-K0-SourceAndSlot130-20261016.md).


### P2 precise K0 +130 A/B source: 128-bit ELF initializer at 0x73170 — 2026-10-17

Owner's `trace_k0_clock_base.ps1` passed **12/12**
synthetic tests and finally resolved native register
provenance: `onFrameAvailable` sets `x19=x0=this`;
constructor sets `x20=x0=this`. Both address
seven blocks at `this+cameraIndex*0x320`.

A closer read reveals the actual `+0x330/+0x338`
coefficient initializer at `0xa72f0`:
`str q1,[x23,#0x5f0]`, where
`x23=this-0x2c0+cameraIndex*0x320`.
That is **exactly** `this+0x330/+0x338+cameraIndex*0x320`.
The 128-bit `q1` is loaded in the constructor
from **ELF VA 0x73170**, stashed at `sp+0x30`,
and copied into each camera block in the 7-iteration
initialization loop. Its first 64-bit word initializes
native coefficient B; the second initializes A.
Prior attention to `d8` at 0x736b0 was a
different structure field, **not the A/B source**.
No claim of live runtime immutability is made.

Offline-only `pico/tools/verify_k0_q1_coefficients.ps1`
runs **15** synthetic regressions (9 new + 6 earlier)
and verifies exact ELF SHA-256 before reading the
16 raw bytes at `0x73170`. It reports the
actual signed integer initializer values and
compares the native expression
`52000 + A + ((B*4) ASR 1)` to the observed
**225997 ns** fixed raw-to-corrected delta over
1,204 K0 frames. The script reports a mismatch
rather than interpreting it as exposure proof.

```powershell
cd C:\Dev\PicoLHSync
git pull --ff-only
pwsh -NoProfile -File .\pico\tools\verify_k0_q1_coefficients.ps1
```

New source, unit tests, and precise constraint
documented in
[`pico/research/P2-K0-SourceAndSlot130-20261016.md`](research/P2-K0-SourceAndSlot130-20261016.md).
Tools have **not yet been run** on owner's PC.
No headset required; `OBSERVE ONLY` and all
`exact_time` and Lighthouse correction gates stay CLOSED.


### P2 actual K0 coefficient initialization differs from observed frames — 2026-10-17

Owner ran `verify_k0_q1_coefficients.ps1` successfully:
**15/15 synthetic tests PASS**; local SHA-pinned service ELF
literal at `0x73170` is
`7d4a0000000000006b09020000000000`, encoding signed
`B_init=19069`, `A_init=133483`.
With the observed `E=4`, the exact native
`slot122-slot130` expression computes
`52000 + A_init + 2*B_init = 223621 ns`.
But the **real K0 capture has 225997 ns** on
every one of the 1204 recorded frames. This is
an exact **+2376 ns (2.376 microsecond)** difference,
not a rounding or unit error:

```text
B_init = 19069; A_init = 133483
A_init + 2*B_init = 171621ns
A_runtime + 2*B_runtime = 173997ns  [assuming same native writer]
delta_A + 2*delta_B = +2376ns
```

The constructor/source-field address correspondence
is proven, but actual live coefficient values,
post-initialization overrides, and exposure semantics
remain **UNVERIFIED**. Don't claim that either
`A+=2376` or `B+=1188` specifically happened.
Source reconstruction and empirical ring timestamps
MUST both be respected; the mismatch is meaningful
for provenance but tiny compared with the separate,
still-unresolved multi-millisecond exposure/producer
timestamp alignment.

A small offline supplementary check is committed:
`pico/tools/audit_k0_alternate_constants.py` scans
only **read-only, non-executable, file-backed** ELF
`PT_LOAD` ranges for aligned `(B,A)` signed-64
pairs that would yield the observed 225997ns
adjustment. Matches, if any, are *candidates*,
NOT proofs of use at runtime. Six synthetic
tests verify bounds, alignment, and exclusion
of writable/executable data. Run with no Pico:

```powershell
cd C:\Dev\PicoLHSync
git pull --ff-only
pwsh -NoProfile -File .\pico\tools\scan_k0_alternate_constants.ps1
```

The runner executes **15 tests** (9 existing q1
tests + 6 new static-literal tests), checks the
saved service SHA256, and writes a private
`p2-alternate-timing-literals.json` report.
It has NOT yet been run on owner's Windows.
The larger next project priority is proving
QuickCamera `FrameMetaDate`'s **raw hardware
clock event** and SteamVR **pose clock mapping**,
not artificially enforcing microsecond-perfect
agreement while exposure semantics are unknown.
All live corrections remain disabled.


### P2: exact ROM coefficient pair reproduces K0 225997-ns adjustment — 2026-10-17

Owner's `scan_k0_alternate_constants.ps1` completed
with **15/15 tests PASS**. Offline SHA-pinned ELF scan
found **one** aligned 16-byte B/A pair in the ELF's
file-backed R-only segment that mathematically matches
the recorded correction:

```text
VA 0x73160: B=19333 A=135331  => 52000 + A + 2B = 225997 ns
VA 0x73170: B=19069 A=133483  => 52000 + A + 2B = 223621 ns
ROM pair delta: B+=264 A+=1848 => 2376ns exact difference
```

This is compelling evidence of an adjacent alternative
constant pair, but it is NOT proof that runtime selects
the `0x73160` pair. The actual constructor's q1 load
at `0xa7198` targets `0x73170`. There must be an
instruction-level source XREF and branch/profile
provenance before asserting any runtime override.
Exact numerical coincidence alone is insufficient.
No physical exposure event or live clock conversion
is verified.

New conservative, SHA-pinned, **offline only**
`pico/tools/audit_k0_literal_references.py` locates
static ADRP+load or ADRP+ADD references to **both** ROM pairs
and prints function-level context without claiming
branch execution. Eight new parser tests accompany it;
`trace_k0_literal_references.ps1` runs **14 total** tests
and saves full candidate XREFs locally:

```powershell
cd C:\Dev\PicoLHSync
git pull --ff-only
pwsh -NoProfile -File .\pico\tools\trace_k0_literal_references.ps1
```

This new script has not yet run on owner's Windows;
no Pico, Android, SLAM, SteamVR or `exact_time` changes.
After determining literal-use provenance, prioritize
hardware time origin and LH/SteamVR pose clock mapping
over further microsecond-scale profile tuning.


### P2 ROM timing sources: ConfigManager loads exact-match pair — 2026-10-17

The owner completed the SHA-pinned
`trace_k0_literal_references.ps1` run with
**14/14 tests PASS**. Static ADRP+LDR references
confirm `pvr::ConfigManager::getInstance()` at
`0xa24b0` and `ConfigManager::ConfigManager()`
at `0xa25e4` both load the ROM pair at
`0x73160` (B=19333, A=135331,
predicted K0 `slot122-slot130=225997ns` with E=4).
`CameraManager::CameraManager()` instead
loads `0x73170` at `0xa7198`
(B=19069, A=133483, prediction 223621ns).
Both source pairs are real. The first matches
all 1204 accepted frames mathematically.

**Do not assert active ConfigManager→CameraManager
coefficient transfer:** the subsequent destination
of q2 from ConfigManager and any camera setter
are not yet verified. The new offline
`pico/tools/trace_k0_configmanager_q2.ps1`
prints narrowly bounded ConfigManager getter/
constructor code around each load, plus actual
CameraManager coefficient initializer and relevant
exported symbols, and re-runs 14 existing tests:

```powershell
cd C:\Dev\PicoLHSync
git pull --ff-only
pwsh -NoProfile -File .\pico\tools\trace_k0_configmanager_q2.ps1
```

This tool has not yet run on Windows; no live
device/SLAM/SteamVR/driver interaction.
Results, interpretation gates and profile-provenance
caution are recorded in
[`P2-K0-SourceAndSlot130-20261016.md`](research/P2-K0-SourceAndSlot130-20261016.md).
After this targeted check, focus on the raw camera
timestamp's hardware event and SteamVR pose clock.
`OBSERVE ONLY`; `exact_time=false`.


### P2 coefficient study closeout; P3 clock-provenance gate — 2026-10-17

The owner ran `trace_k0_configmanager_q2.ps1` successfully,
**14/14** previously established unit tests PASS.
Additional real static source evidence establishes the
alternate pair `0x73160` (B=19333, A=135331) is
stored at `ConfigManager+0xA0` by
`ConfigManager::getInstance()` (q2 load at 0xa24b0,
q2 store at 0xa24e8) and
`ConfigManager::ConfigManager()` (load at 0xa25e4,
store at 0xa2628). `CameraManager` independently
constructs per-camera A/B from `0x73170`;
a ConfigManager-to-CameraManager assignment has NOT
been proven. This is not a verified active runtime
profile or physical exposure event.

The investigation of the 2,376-ns alternative timing
pair discrepancy is provisionally complete.
The remaining P2/P3 blockers are producer provenance
of the QuickCamera first `FrameMetaDate` word,
the actual optical event represented, and Pico-to-PC
OpenVR/SteamVR pose clock synchronization. While Pico
is powered off, we can work on the PC-side OpenVR
pose/QPC timing methodology without changing any
live headset or VR driver state.

The **source-grounded evidence matrix, required missing
QuickCamera dependencies, staged read-only tests and
safe deployment gates** are now centralized in:
[`P2-Closeout-P3-Clock-Provenance-20261017.md`](research/P2-Closeout-P3-Clock-Provenance-20261017.md).

No Pico boot/re-capture is required at this stage.
`OBSERVE ONLY`; `exact_time=false`.


### Handover to new Pico4 Stuff conversation — P3 start, 2026-10-17

P2 is closed at the level of available static/source evidence;
the measured 2,376-ns discrepancy between CameraManager
constructor defaults and captured K0 timestamps is fully
documented. The alternative ConfigManager pair matching
the observed correction is stored at ConfigManager+0xA0,
but transfer to the active CameraManager camera fields
and optical capture event remain unverified.

For the **next conversation in the same ChatGPT project**,
read these two maintained Markdown artifacts first:

- [**Full P2→P3 technical handover**](research/P2-to-P3-FULL-HANDOVER-20261017.md):
  hardware contract, P1 source/transport, 1,204-frame
  evidence, exact ELF addresses and checksums,
  completed tests, private evidence locations,
  fail-closed gates and P3 experiment plan.
- [**P3 new-chat starter prompt**](research/P3-NEW-CHAT-STARTER-20261017.md):
  concise instructions for preserving source provenance
  and beginning an opt-in, host-only Windows
  OpenVR/QueryPerformanceCounter timing probe.

Pico 4 Pro can remain off while the Windows/Pimax
host-only probe is developed. The original
[closeout and P3 gates](research/P2-Closeout-P3-Clock-Provenance-20261017.md)
continue to govern deployment. **No live driver, camera,
SLAM, F timestamp or factory calibration changes** have
been authorized. `OBSERVE ONLY`; `exact_time=false`.
