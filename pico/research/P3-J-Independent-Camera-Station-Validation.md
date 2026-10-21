# P3-J — Independent Camera / Station Validation

**Date:** 2026-10-21
**Branch:** `feature/pico-support`
**Baseline:** `2746123583d846f7973581ef8beb24a257b7a90b`
**Verdict:** `INSUFFICIENT_INDEPENDENT_EVIDENCE`

## Decision

The existing evidence still does not distinguish the two lower-camera mappings. A channel-7 optical candidate was historically reported in the 417.6 s power-toggle recording, but its saved result is aggregate across cameras and does not include a frozen candidate/ROI provenance record. The 418 s OFF and ON windows also have weak head-pose overlap. The available material therefore cannot show that C4 or C5 independently sees a channel-7 source, nor compare the two mappings on a held-out optical association.

The recorded FOV contradiction is real as a model result: under the frozen diagnostic pose, station-center projection predicts ch7 inside C4/C5 images often, while the saved candidate-mapping P3-I ray dump contains no near-station-center rays for either camera. That does not identify which assumption is wrong. A station-center projection is not a model of every Lighthouse sweep/emitter ray, and an observed optical landmark may be a reflection.

No mapping is recommended from this audit. Retain candidate mapping `C0→cam0, C3→cam1, C4→cam2, C5→cam3` as an unverified replay hypothesis only. `mapping_verified` and `pose_verified` remain false.

## Scope, fixed hypotheses, and provenance

Offline-only analysis of recordings and reports already present locally. The full recording and marker CSV were hash-checked before parsing. The recordings, calibration drafts, transforms, filtered LOCO copies, and native outputs remain in private local storage and are not committed.

| Input | SHA-256 | Use |
|---|---|---|
| 417.6 s full OFF/ON recording, `qlhs-20261015-202605.txt` | `b22cbed297d284d9bb55c1f521fdabbaa408e724d8d10199672e1e89e8c6be24` | Raw `U F`, `P 0`, `Q`, and raw channel-first `S` records |
| Full-session switch markers | `61d0a9578248df682e9db55aac618d040c4ce5f66e5b92734d58b12742dff8ba` | QPC action markers; no serials or room labels used in this report |
| 474.0 s focused switch recording | `f5e268facd4405957d7ec2cef97329ebb6b9507fa7160cfcc94c711e211b80b3` | Existing ch1/ch10-only supporting capture |
| Focused-session marker CSV | `a0793d4fb80d3c0964227f03f3cbc7a0c069dc04b5a4faef7d3cdc32166b9c2c` | Existing ch1/ch10 phase markers |
| P3-H 117.2 s motion-rich recording | `190acdc5cddc173550ed0c3c47abfc3b063dfa9b08417657b2241303bbdd578a` | Existing all-stations-ON ray/FOV analysis only |
| P3-I saved ray dump, 15,228 rays | `df3e24d1c6d7d9c71c7ba9377e1b4afee87f443b1a13189a3c5540ac7d0aac2a` | Candidate-mapping rays; no placement-mapping ray dump was found |
| P3-I corrected fixed-yaw FOV summary | `d07d22c3f9295bc55c3918a4bcd006aa7b0deb2da24c23b3580ba0fc2101f875` | Corrected P3-H station-center projection rates |
| Existing candidate calibration draft | `819810ce53c668543d37447be942e6f7b5ee7531a513bac29e5c653b9788bb0d` | Factory Omni/Radtan data, private; not modified |
| Existing placement-guess calibration draft | `b75df0ed561b31d51b4224d0667fa08b464619729e8559086d62403636cbe24b` | Alternative existing hypothesis, private; not modified |
| Frozen `BodyToHead_-Y+X+Z` transform | `b7dab89536c92b0c1313b4b65719a442441bc97fdbc926f1d7a4066b1dde91d5` | Zero-translation diagnostic only |
| `QLHS_REPLAY_DIAGNOSTICS` executable | `d7c88a87c059be26295ffb26a3483da5f176b0a5406251dc007a03772b68d945` | Original QuestLHSync solver diagnostics |

The two mapping hypotheses are exactly:

| Hypothesis | C0 | C3 | C4 | C5 |
|---|---|---|---|---|
| Candidate | cam0 | cam1 | cam2 | cam3 |
| Placement guess | cam0 | cam1 | cam3 | cam2 |

The P3-F/P3-G/P3-H/P3-I transform and timing were not changed. Translation remains zero solely as a diagnostic control. No native solver, threshold, production calibration, driver, or safety flag was changed.

## Marker windows and capture comparability

The 417.6 s record has 41,763 `U F` rows: C0=10,441, C3=10,441, C4=10,441, C5=10,440; 29,112 `P 0` rows; and 417.614 s of camera-frame coverage. Poses cover 417.623 s. No malformed relevant rows were found by the bounded parser used for these counts.

For each channel, the existing 5 s transition exclusion and 23 s ON windows were applied around the QPC `OFF` and `ON` markers:

```text
ON-before = [OFF marker − 28 s, OFF marker − 5 s)
OFF       = [OFF marker + 5 s, ON marker − 5 s)
ON-restored = [ON marker + 5 s, ON marker + 28 s)
```

Markers are operator ENTER times after a requested physical action. They do not timestamp laser shutdown or spin-up exactly. Relative to the first camera-frame QPC in the full recording, ch7 windows are ON-before 303.962–326.962 s, OFF 336.962–368.387 s, and ON-restored 378.387–401.387 s.

| Channel | ON-before frames / P0 poses | OFF frames / P0 poses | ON-restored frames / P0 poses |
|---|---:|---:|---:|
| ch13 | 2,300 / 1,556 | 3,844 / 2,722 | 2,300 / 1,611 |
| ch10 | 2,300 / 1,612 | 1,833 / 1,808 | 2,279 / 1,619 |
| ch1 | 2,300 / 1,586 | 2,605 / 2,030 | 2,303 / 1,601 |
| ch7 | 2,300 / 1,609 | 3,142 / 2,190 | 2,302 / 1,601 |

Camera frame counts are taken from each source window, not estimated from nominal 25 Hz. Their unevenness in some ch10/ch1 windows is retained in the denominators. For ch7, the camera-specific frame counts are balanced enough to compare raw counts, but pose coverage is not:

| Camera | ON-before frames | OFF frames | ON-restored frames | Raw detections with peak ≥100, ON-before / OFF / ON-restored |
|---|---:|---:|---:|---:|
| C0 | 575 | 786 | 575 | 16 / 290 / 199 |
| C3 | 575 | 786 | 575 | 210 / 100 / 17 |
| C4 | 575 | 785 | 576 | 16 / 0 / 16 |
| C5 | 575 | 785 | 576 | 22 / 0 / 30 |

These are **all unlabelled detections** at the fixed peak threshold, not channel-7 hits. Per 1,000 camera frames, C4 is 27.8 / 0 / 27.8 and C5 is 38.3 / 0 / 52.1. C0 and C3 change in opposite directions across the same interval. The rate changes therefore cannot be assigned to ch7 without a frozen per-camera optical candidate and pose/FOV control.

The head-pose comparison used the full recorded 3×4 `P 0` matrices and predeclared 5 cm/5° and broad 20 cm/15° matching bounds. Matches are many-to-one nearest pose pairs, not independent samples. Among ON-before poses, 0/1,609 matched any OFF pose within 5 cm/5°, and 177/1,609 within 20 cm/15°. Among ON-restored poses the counts are 0/1,601 and 586/1,601. In the reverse direction, OFF-to-ON-before was 0/2,190 at 5 cm/5° and 1,142/2,190 at 20 cm/15°; OFF-to-ON-restored was 0/2,190 and 905/2,190. Thus the ON/OFF windows do not supply tightly matched ch7 views.

The focused 474 s capture is correctly limited to ch1/ch10; it is not a ch7 negative control. Running the existing `check_targeted_capture.py` against its recording and marker CSV returned `CAPTURE REVIEW` (exit 1):

| Guided phase | HMD poses, baseline / OFF / restored | Frames, baseline / OFF / restored | Representative BASELINE→OFF | Representative BASELINE→restored |
|---|---:|---:|---:|---:|
| ch1 view 1 | 2,925 / 2,630 / 779 | 4,208 / 3,809 / 1,100 | 26.0 cm / 29.9° | 12.3 cm / 44.7° |
| ch1 view 2 | 2,507 / 2,568 / 738 | 3,662 / 3,722 / 1,100 | 34.5 cm / 16.7° | 6.8 cm / 22.9° |
| ch10 view | 1,801 / 2,231 / 752 | 2,592 / 3,181 / 1,101 | 25.3 cm / 35.2° | 4.8 cm / 9.6° |

The helper's existing 20 cm/15° return-to-view criterion is not met for the OFF phases, so the focused capture does not repair the missing matched-view control.

## Existing optical ON/OFF candidates

The existing P2 spatial report gives the following **aggregate** candidate hit counts for the full 417.6 s session, using its fixed 20 px / peak≥100 gate and frames where the candidate projected inside FOV:

| Channel candidate | ON-before hits / visible frames | OFF hits / visible frames | ON-restored hits / visible frames |
|---|---:|---:|---:|
| ch13 | 224/1,182 | 0/2,115 | 171/1,267 |
| ch10 | 3/885 | 0/2,067 | 19/1,836 |
| ch7 | 39/1,564 (2.49%) | 0/2,413 (0%) | 37/1,610 (2.30%) |
| ch1 | not reliably isolated in this capture | — | — |

The ch7 table is compatible with a stationary optical feature associated with power state somewhere in the camera set. It is not an independent per-camera result: the surviving public summary does not say which cameras contributed each hit, and the exact candidate point/ROI selection record was not found in the local P3-C–P3-I evidence. It therefore cannot establish C4/C5 signal, unbiased recall, or false-positive rate. An existing historical negative-control warning is material: an unrelated C3 landmark remained visible in 719/735 frames while ch1 was OFF.

P3-I's corrected station-center FOV calculations were made over 2,604 sampled P3-H poses, where all stations were ON. The fixed-yaw result is pinned by the corrected summary above. For ch7, candidate mapping gives C4=82.3% and C5=80.5% in-image; placement guess swaps those values (C4=80.5%, C5=82.3%). Both hypotheses therefore predict substantial combined C4/C5 visibility; their combined percentage-points are identical, with only the assignment to each sensor swapped. These are not FOV rates for the 418 s switch windows. The older aggregate's discrepant FOV fields were not used because they do not match the corrected fixed-yaw result documented by P3-I.

The saved P3-I candidate-mapping ray table contains C4=66 nearest-model rays and C5=43. Under the P3-I frozen candidate fit, C4 residual p50/p90 was 30.610°/123.362° and C5 was 31.482°/33.108°; each had 0 bright rays below 2° and 0 dim rays below 0.5°. This is a nearest-station-center model check, not a station identity test. The saved ray dump was generated only under candidate mapping; no placement-guess C4/C5 ray residuals are available. The raw optical candidate point and per-camera projection ledger are not present in the inspected local evidence set.

## Camera leave-one-out

The existing replay accepts `all|upper`, not an arbitrary excluded camera. For the requested ablation only, private derived recording copies were made by removing exactly one camera's `U F` rows while preserving the original `P`, `Q`, and raw `S` rows. The original recording remained unchanged. Replays used the pinned P3-G executable, private candidate calibration, frozen transform, `--pico-offline`, `--pico-cameras all`, `--pings`, baseline exposure/timing, and isolated state directories. No solver source or threshold was changed. Status samples are one-second diagnostics; a consecutive lock-sample count is not an exact continuous-duration measurement.

| Mapping / omitted camera | `has_alignment` samples / first alignment | Longest locked status run | `condition=true` samples | Highest Acquire-reported support / tight support |
|---|---:|---:|---:|---:|
| Candidate / C0 | 369/418; 49 s | 188 samples | 0/418 | 21 / 4 |
| Candidate / C3 | 0/418; none | 0 | 0/418 | 19 / 3 |
| Candidate / C4 | 355/418; 63 s | 354 samples | 0/418 | 16 / 2 |
| Candidate / C5 | 370/418; 48 s | 217 samples | 0/418 | 17 / 5 |
| Placement guess / C3 | 0/418; none | 0 | 0/418 | 9 / 3 |

Removing C3 prevented either mapping from establishing an alignment. This is `INSUFFICIENT_OTHER_CAMERA_SUPPORT`, not evidence that C3 extrinsics are correct or that the other cameras are wrong. The retained-camera runs show that the native solver can form/hold an unconditioned alignment under some camera omissions; they do not measure prediction residual on the omitted camera. No camera-held-out residual is reported because these replays did not emit a separately frozen alignment plus a disjoint held-out per-camera prediction set, and a nearest-station assignment would not prove source identity. The only placement-guess ablation was the specifically important no-C3 test; the full LOCO Cartesian product was not run.

An initial placement-guess/no-C3 attempt was rejected before replay because the candidate draft was paired with the placement mapping. It produced no result. The single retry used the already-existing placement-guess calibration draft whose hash is pinned above and completed with exit 0. Both attempts and outputs remain in private local diagnostics.

## Station leave-one-out and mapping independence

No valid station-held-out optical score can be reconstructed from the available artifacts. The ch7/ch13 candidate summary is same-recording aggregate data; the candidate selection time, exact point/ROI, per-camera hits, and held-out sample list are absent. The focused recording cannot substitute for ch7 and its existing pose checker reports `CAPTURE REVIEW`. Consequently, no ch7 or other channel is treated here as an independent LOSO validation.

P2's historical station-held-out median errors (ch1 9.27 px, ch7 44.67 px, ch10 8.07 px, ch13 36.0 px) remain conditional on the provisional correspondence set and fitted geometry. They are not a new independent LOSO result under this audit's rule that the held-out source must not select its point, transform, or gate.

Prior P3-F native mapping comparisons remain inconclusive: on the 474 s recording both mappings produced one accepted alignment and 437.05 s lock, with condition false; placement guess had slightly lower median/p90/max residual (0.325/0.372/0.411°) than candidate (0.344/0.380/0.417°). On the 78 s recording, candidate locked 50.8 s and placement guess did not lock. These conflicting in-sample solver outcomes are not independent optical evidence and are not used to rank mappings.

There is no vendor/K0 metadata mapping from Binder camera IDs `{0,3,4,5}` to factory camera IDs `{0,1,2,3}` in the inspected sources. Both mappings remain geometric hypotheses; neither is confirmed by the P3-J data.

## Evidence status by question

| Question | Result |
|---|---|
| Does any camera see a channel-7 power-correlated optical candidate? | Historical aggregate ch7 candidate has 39/1,564 ON-before, 0/2,413 OFF, 37/1,610 restored-ON hits; selection and per-camera provenance are not independently preserved. Suggestive only. |
| Do C4/C5 independently show that ch7 event? | **`CH7_C4_C5_ASSOCIATION_UNRESOLVED`**. Unlabelled C4/C5 bright detections drop to zero in OFF, but pose overlap is weak and no frozen per-camera ROI/hit ledger exists. |
| Which mapping predicts ch7 in C4/C5 FOV? | Both. Corrected P3-I P3-H pose FOV values are swapped by mapping (82.3%/80.5% versus 80.5%/82.3%), with identical combined C4/C5 visibility. No 418 s interval-specific FOV was stored. |
| Does station-center geometry agree with candidate-mapping rays? | No near rays under P3-I candidate model. This does not distinguish wrong mapping/extrinsics, timing, or a non-center optical source/reflection. |
| Does excluding C3 permit a native alignment? | No under either tested mapping. `INSUFFICIENT_OTHER_CAMERA_SUPPORT`; not an extrinsics verdict. |
| Camera-held-out prediction quality? | Not measured. |
| Independent station-held-out quality? | Not measurable from preserved source-selection records. |
| Binder camera ↔ factory camera identity? | Not proven. |

## Next practical step

Do one controlled, separately approved ch7 repeat using the existing QuestLHSync recording/marker path: hold a repeatable HMD view, freeze a per-camera C4/C5 optical ROI from the initial ON segment before examining OFF/restored data, then compare those same ROIs after ch7 OFF and restored ON at the matched view. Report per-camera hit/frame counts and FOV eligibility under both existing mappings. This single experiment addresses the missing camera-specific association; it does not establish factory extrinsics, physical station center, exact exposure time, or authorize live correction.

## Verification and unchanged gates

- Full 418 s record and marker SHA-256 verified; filtered LOCO inputs removed only the named camera's `U F` records. Original recordings were not modified.
- Five native LOCO diagnostic runs completed with exit 0 and empty stderr after correcting the placement-draft pairing. The rejected initial pairing was blocked before replay.
- `python -m unittest discover -s pico/tests -p 'test_*.py'` — **299 tests, PASS** (103.526 s). Negative CLI cases printed expected usage/blocked messages.
- `out/qlhs_replay.exe --conditioning-self-test` — **PASS** (`PICO_COND_SELFTEST status=PASS`).
- `check_targeted_capture.py` on the existing 474 s recording returned `CAPTURE REVIEW` (exit 1), which is recorded as a limitation, not a test pass.
- `git diff --cached --check` — **PASS**. No new native executable or production code was built or changed.
- No raw recording, raw pose, station identity/serial, room coordinates, factory calibration bytes, or private binary is included in Git.

```text
observe_only=true
mapping_verified=false
pose_verified=false
exact_time=false
shared_buffer_identity_verified=false
frame_meta_bridge_verified=false
physical_event_verified=false
live_lighthouse_correction_allowed=false
```
