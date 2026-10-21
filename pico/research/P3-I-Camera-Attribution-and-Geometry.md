# P3-I — Pico Camera Attribution and Geometry Audit

**Date:** 2026-10-21
**Branch:** `feature/pico-support`
**Baseline:** `c861dc2cdc8c5173c7aa07d49ee0ab52f7bab2a5`
**Verdict:** `CAMERA_MAPPING_OR_EXTRINSICS_SUSPECT` — the observations do not support a confident mapping/extrinsics diagnosis, but the candidate geometry predicts C4/C5 should see channel 7 while the ray/model comparison finds no near channel-7 candidates. This is a contradiction to investigate, not proof that the mapping is wrong.

## Scope and safety

This audit used the existing 117.2-second recording and one offline replay of the existing `QLHS_REPLAY_DIAGNOSTICS` build to emit its optional ray dump. The replay reused P3-H's frozen zero-translation `BodyToHead` hypothesis, factory-derived private calibration, candidate mapping, all four cameras, and unchanged timing. It added only `--rays`; it used an isolated state directory and no `--learn`, exposure override, timing sweep, device access, SteamVR, camera operation, Lighthouse, or live correction. No solver code or thresholds changed. No additional native replay was made for the C4/C5 swap because P3-F already compared the two existing mapping hypotheses.

The recording, private calibration, transform, ray dump, replay stdout, and private analysis JSON remain outside Git. No station identities, room coordinates, raw camera data, calibration coefficients, or private paths are included here. Safety flags remain false.

## Evidence and method

| Input | SHA-256 | Use |
|---|---|---|
| Existing P3-H recording | `190acdc5cddc173550ed0c3c47abfc3b063dfa9b08417657b2241303bbdd578a` | Raw K0 `U F`, HMD `P`, raw channel-first `S`, and `Q` records |
| Existing diagnostic replay executable | `d7c88a87c059be26295ffb26a3483da5f176b0a5406251dc007a03772b68d945` | Original QuestLHSync solver with diagnostics |
| Private factory calibration | `819810ce53c668543d37447be942e6f7b5ee7531a513bac29e5c653b9788bb0d` | Candidate camera intrinsics and `T_BS` |
| Frozen P3-H transform hypothesis | `b7dab89536c92b0c1313b4b65719a442441bc97fdbc926f1d7a4066b1dde91d5` | Diagnostic `BodyToHead` rotation with zero translation |
| Private ray dump | `df3e24d1c6d7d9c71c7ba9377e1b4afee87f443b1a13189a3c5540ac7d0aac2a` | 15,228 reconstructed camera rays |
| Private replay stdout | `70081c648e7e48fa7337b808b1d874a5ed18a1c3c2e544c7d09c4ea0661e3975` | Stage, fit, status, and native acquisition diagnostics |

Replay returned 0 in 4.127 seconds, with 44,202 stdout bytes and no stderr. The ray dump contained 15,228 rows, exactly matching P3-H's valid-ray total. Reconstructing the logged normalized rays from their pixel observations had maximum angular discrepancy 0.0221 degrees (p99 0.02 degrees). The ray-dump `X` record writes yaw in **degrees** (`replay.cpp` multiplies its internal radians by `kDeg`); the offline geometry calculation converted that value back to radians before use. All reported corrected geometry values below use that unit conversion. The historical raw channel-first station records were used; the 48 transformed channel-last `S` records were excluded as independent poses, matching the P3-H parser contract.

The candidate mapping used by P3-H is `C0→cam0, C3→cam1, C4→cam2, C5→cam3`. `prepare_calibration.py` labels it an unverified hypothesis inferred from camera positions, not from vendor sensor-ID metadata. The fixed transform is likewise a diagnostic hypothesis, not a verified headset pose transform. The P3-H native solver accepted one alignment at about 95 seconds and remained locked for 21.25 seconds. Its 21 eligible diagnostic fits were conditioned, median `lambda_min` was 1.748, and median status residual was 0.3594 degrees. These solver outcomes do not validate physical camera identity or the transform.

## Camera funnel and required attribution table

Raw bright/dim counts split input blobs at the existing peak threshold. `valid rays` is the solver diagnostic after pose/still/large-blob checks. `motion admitted` is `valid rays - fast blobs` at the existing 60 degrees/second limit and equals the `Solver::Add` count here. `Fit observations` are the camera-attributed rows selected across the 21 eligible final Fit samples before robust downweighting. The nearest-station angular values use the solver's existing `Nearest` rule and the P3-H final alignment; channel labels are the saved station channels. The full per-camera/per-channel residual table follows.

| Camera | Raw spots (bright / dim) | Valid rays | `Solver::Add` | Final Fit observations | Expected station visibility ch1 / ch7 / ch10 / ch13 (%) | Nearest-model residual p50/p90 by channel (degrees) | Near-station candidates bright <2° / dim <0.5° | Association confidence and finding |
|---|---:|---:|---:|---:|---|---|---:|---|
| C0 | 2,022 (410 / 1,612) | 1,940 | 1,456 | 906 (3.49%) | 73.7 / 16.9 / 73.0 / 41.2 | ch1 6.30/15.75; ch7 30.78/33.88; ch10 5.08/14.00; ch13 109.69/121.69 | 61 / 3 | Low. Some ch1/ch10 model-near candidates; large ch13 residual despite a smaller candidate count. |
| C3 | 8,422 (4,725 / 3,697) | 8,080 | 7,620 | 22,148 (85.43%) | 82.8 / 14.6 / 83.3 / 85.8 | ch1 2.64/5.69; ch7 34.75/115.65; ch10 5.01/6.02; ch13 21.72/41.48 | 1,180 / 6 | Low independent confidence. It has the strongest ch1 proximity, but this same C3-heavy evidence contributed to selecting the alignment; ch13 has many blobs but much weaker nearest-ray agreement. |
| C4 | 2,439 (413 / 2,026) | 2,358 | 1,987 | 1,301 (5.02%) | 20.7 / 82.3 / 19.7 / 19.6 | ch1 4.99/13.92; ch7 30.61/123.36; ch10 6.06/9.48; ch13 116.59/118.72 | 73 / 1 | Low. Candidate geometry predicts ch7 visibility for most sampled poses, yet no bright ray is within 2° of the nearest ch7 model direction. |
| C5 | 2,935 (478 / 2,457) | 2,850 | 2,440 | 1,569 (6.05%) | 23.0 / 80.5 / 22.6 / 22.6 | ch1 5.72/14.11; ch7 31.48/33.11; ch10 5.48/11.42; ch13 40.38/113.24 | 96 / 1 | Low. Candidate geometry also predicts frequent ch7 visibility, but no near ch7 candidates appear; ch13 near-threshold counts coexist with poor all-ray residuals. |

**Interpretation limits:** visibility percentages are station-center projections for 2,604 sampled HMD poses under the candidate mapping, frozen alignment, private factory intrinsics, and diagnostic `BodyToHead`. They mean only “the modeled station center projects into the modeled image and is in front of the camera.” They do not model Lighthouse sweep-plane/emitter geometry, reflections, exposure timing, or whether a detectable light should be present in that frame. `Nearest` assigns every ray to the angularly closest modeled station subject to the native front-facing test; many rows are unrelated blobs. Counts below a residual threshold are candidate coincidences, not identified flashes or station associations.

| Camera / channel | Nearest-model rays | Residual p50 / p90 (degrees) | Bright candidates <2° | Dim candidates <0.5° |
|---|---:|---:|---:|---:|
| C0 / ch1 | 250 | 6.299 / 15.751 | 22 | 0 |
| C0 / ch7 | 520 | 30.783 / 33.876 | 0 | 0 |
| C0 / ch10 | 114 | 5.082 / 13.997 | 16 | 0 |
| C0 / ch13 | 1,056 | 109.689 / 121.693 | 23 | 3 |
| C3 / ch1 | 3,239 | 2.641 / 5.690 | 1,056 | 0 |
| C3 / ch7 | 81 | 34.749 / 115.648 | 0 | 0 |
| C3 / ch10 | 1,043 | 5.014 / 6.021 | 20 | 0 |
| C3 / ch13 | 3,717 | 21.715 / 41.480 | 104 | 6 |
| C4 / ch1 | 211 | 4.993 / 13.921 | 24 | 1 |
| C4 / ch7 | 66 | 30.610 / 123.362 | 0 | 0 |
| C4 / ch10 | 104 | 6.060 / 9.483 | 0 | 0 |
| C4 / ch13 | 1,977 | 116.585 / 118.719 | 49 | 0 |
| C5 / ch1 | 298 | 5.719 / 14.112 | 33 | 0 |
| C5 / ch7 | 43 | 31.482 / 33.108 | 0 | 0 |
| C5 / ch10 | 96 | 5.484 / 11.421 | 0 | 0 |
| C5 / ch13 | 2,413 | 40.378 / 113.239 | 63 | 1 |

### Where C3 dominance arises

C3 supplies 53.2% of raw spots, 78.4% of raw bright spots, and 56.4% of `Solver::Add` rows, but it supplies 85.43% of final Fit observations. Thus there are two visible contributors: the input already has a much higher bright-blob population on C3, and final geometry selection enriches C3 further. The data do not isolate whether the input skew is caused by camera view, sensor exposure/response, illuminator geometry, detector behavior, or a source association; the fit skew additionally depends on mapping, extrinsics, timestamp alignment, and the current model.

The diagnostic reports global robust statistics only: mean robust weight p50/p90 0.715/0.725; effective weight mass p50/p90 37.310/38.535; and 6,040 of 25,924 selected rows (23.30%) strongly downweighted under the existing diagnostic definition. It does **not** report robust weight totals by camera. Since fit camera counts are recorded before robust weighting, this audit cannot attribute C3's 85.43% share to robust weighting or quantify per-camera downweighting.

Per-stage diagnostic counts were: pose-failure blobs C0/C3/C4/C5 = 57/156/68/75; still blobs = 21/156/13/10; large blobs = 0; invalid rays = 0; fast blobs excluded = 484/460/371/410. Each camera had seven frame clock-map failures. The clock-map counter is frame-based, unlike the blob counters, so it is not added to blob totals. These stage counters show that the observed C3 share is not explained by a large invalid-ray or large-blob rejection on the other cameras. C3 still/detector input differs substantially, and ray acceptance alone is not a station-label test.

## Pixel, camera-ID, and optical-model audit

- `PicoFrameReader.java` requests the four internal Binder/K0 IDs `{0,3,4,5}`, verifies the K0 ring metadata and sensor byte, maps shared memory read-only, and copies 640×480 bytes contiguously from slot offset 186. The local reader does not apply an image flip, rotation, or channel swap, and the ring reader has no separate row-stride field; this proves the reader's behavior, not that vendor pixels have the same orientation convention as factory calibration.
- `lhsight_pico.c` passes `W=640`, `H=480` and the byte image to the original Quest `blobs()` detector. It emits each centroid as x then y in tenths of a pixel. `Sync::OnLine` parses that order; `Sync::Use` divides by 10, subtracts the existing 0.5-pixel center offset on both axes, and calls `Optics::Ray(cam,x,y)`. No coordinate-axis swap or image orientation transform is present in this path.
- `prepare_calibration.py` maps Binder IDs `{0,3,4,5}` to factory camera IDs `{0,1,2,3}` as a candidate inferred from placement. It explicitly retains `mapping_verified=false`; no vendor sensor-ID-to-factory calibration contract is demonstrated by this mapping.
- `Optics::LoadPico` requires both mapping and pose verification and a row-major rigid `HeadFromBody`, validates 640×480 Omni/Radtan intrinsics, and composes `HeadFromBody × T_BS`. Lab replay creates a temporary in-memory diagnostic calibration to run the frozen hypothesis; this does not mutate the source draft or production gates. `Optics::Ray` unprojects the corrected pixel through the Omni/Radtan model. The model accepted all 15,228 replay rays (zero invalid rays), but that is numerical/model validity, not proof that image orientation, camera assignment, or `T_BS` matches the physical hardware.
- Existing coordinate checks found the parser and matrix layouts consistent with the current source path: x/y order is preserved, pixel-center correction is explicit, and matrices are consumed row-major in the documented `T_BS` composition. This does not establish that the vendor's image axes or physical sensor frame agree with the private factory file.

No code-level evidence identifies a flip, rotation, x/y swap, or row-stride error. The concrete inconsistency found is instead between candidate-model station-center visibility and the observed nearest-ray population, especially ch7 for C4/C5. Because both camera mapping and body-to-head transform are unverified, this cannot distinguish wrong mapping, wrong extrinsics, timestamp mismatch, optical source/reflection behavior, or the fact that station-center projection is an incomplete visibility model.

## Mapping and independent station evidence

P3-F already made the bounded candidate-versus-placement-guess comparison. On the 474-second session both mappings produced one accepted alignment and 437.05 seconds of lock. Placement guess had slightly lower median/p90/max residual (0.325/0.372/0.411 degrees) than candidate (0.344/0.380/0.417 degrees), while C3 dominated the selected observations and conditioning remained false. On the shorter 78-second session candidate mapping locked 50.8 seconds while placement guess did not lock, so the outcomes do not consistently rank the two. The long replay cannot distinguish them through C3-skewed aggregate fit metrics; no new mapping replay was justified for P3-I.

Prior switch-marker captures do offer limited station-correlated optical controls: the 417.6-second capture showed a strong channel-13 ON/OFF signature, channel 7 had an ON/OFF candidate in the later analysis, and channel 1 was initially not reliably isolated before a focused follow-up added an ON/OFF-correlated candidate. These controls used provisional geometry and candidate points, not ground-truth station centers, and are not independent validation of the P3-H alignment. The history also records a direct false-positive warning: an unrelated landmark was visible on C3 in 719/735 frames while channel 1 was OFF. Aggregate bright-spot counts or a ray close to the nearest station-center direction therefore cannot establish station identity. The P3-H recording itself kept all stations ON and has no negative-control intervals.

For P3-H's 21 eligible fits, the station-slot shares were 83.57%, 15.21%, 1.22%, and 0%. Status samples after the acquisition show channel 13 and channel 1 carrying most support, channel 10 sparse support, and channel 7 zero. A three-station support count was sufficient for the P3-H conditioning criterion, but the fit remained highly uneven and did not validate each channel association.

## Late acquisition at 95 seconds

The status sequence gives the proximate solver-level event: acquisition attempts at 81 and 85 seconds reported support 8; attempts at 88 and 91 reported support 10; the successful attempt at 95 reported support 12 with tight support 3. The first lock/conditioned status followed at 96 seconds.

The per-camera near-station candidate counts do not show a unique geometry/visibility jump at 95 seconds. During 80–95 seconds the bright <2° candidate counts were C0/C3/C4/C5 = 35/96/54/53; during 95–117.2 seconds they were 26/77/6/19. Most other-camera candidate counts were larger before acquisition. C3 had 1,007 such candidates in 0–80 seconds, 96 in 80–95, and 77 after 95. The capture includes translation-rich movement before and across the acquisition boundary, but these facts do not establish which accumulated or pooled observations crossed the unchanged support threshold. Therefore the reason for the timing of the successful acquisition remains **UNRESOLVED**; the 95-second delay is not evidence of a timestamp error.

## Decision

**`CAMERA_MAPPING_OR_EXTRINSICS_SUSPECT` (hypothesis only; root cause unresolved).** The strongest concrete signal is candidate-geometry inconsistency: C4/C5 station-center projection predicts channel 7 in view for about 80–82% of sampled poses, yet no channel-7 nearest ray falls below the 2-degree bright / 0.5-degree dim candidate thresholds. C3 has a large bright-input advantage and its ray population is much more aligned with channel 1, which then dominates Fit selection. This warrants investigating camera-to-factory assignment and relative extrinsics, but cannot choose between candidate and placement mapping or establish a physical cause. Optical reflections and incomplete sweep/source geometry remain live alternatives.

`CAMERA_ASSOCIATION_CONSISTENT` is not supported: C3 fit dominance and the C4/C5-to-ch7 discrepancy remain. `VISIBILITY_LIMITED` alone is not supported because candidate projection predicts C4/C5 see ch7 frequently. `OPTICAL_SOURCE_ASSOCIATION_SUSPECT` remains a plausible contributor but the present data cannot isolate it from geometry. No camera mapping or pose gate is promoted.

**One next practical step:** perform an offline mapping/extrinsics audit against the already-existing station-switch records, using leave-one-camera-out and leave-one-station-out checks with independent ON/OFF windows, and explicitly evaluate the ch7 prediction for C4/C5 under both already-existing mapping hypotheses. Do not request another identical motion capture until this resolves whether the failure is camera geometry or source association.

## Unchanged safety gates

```text
mapping_verified=false
pose_verified=false
exact_time=false
shared_buffer_identity_verified=false
frame_meta_bridge_verified=false
physical_event_verified=false
live_lighthouse_correction_allowed=false
```

The native replay's accepted alignment and conditioned fits are offline solver outcomes only. They do not establish the physical camera map, factory `HeadFromBody`, frame identity, exact timestamps, physical SOF/exposure timing, or safe live corrections.

## Verification

- Reused P3-H offline replay evidence: exit 0; ray dump 15,228 rows; stderr empty; input, binary, calibration, transform, stdout, and ray-dump hashes verified above.
- `python -m unittest discover -s pico/tests -p 'test_*.py'` — **299 tests, PASS** (56.528 s). Negative CLI cases printed their expected blocked/usage messages.
- `out/qlhs_replay.exe --conditioning-self-test` — **PASS** (eigen reference, positive and negative controls).
- `git diff --cached --check` — PASS after staging.
- The recording, calibration, transform, stdout, ray dump, and private analysis files remain local and outside Git.
