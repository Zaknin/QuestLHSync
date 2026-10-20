# P3-E — Geometry bootstrap with the original native solver

**Date:** 2026-10-20
**Branch:** `feature/pico-support`
**Starting revision:** `ac372f90c11bc261df2c472402fe8bcaeb199c78`
**Outcome:** `DISCRETE_HEAD_FROM_BODY_CANDIDATE_FOUND`; calibration remains unverified.

## Result in brief

An offline replay of the original native solver found one proper signed-axis rotation that repeatedly produces accepted alignments and long locked intervals on three previously recorded Pico sessions. The candidate was selected using only the 78-second session, then held fixed for the 474-second focused session and the separate 418-second recording. Identity controls produced no accepted alignment or lock on either long session.

The candidate is only a **zero-translation diagnostic transform**. It is not a measured six-degree-of-freedom `HeadFromBody`, and it does not validate the factory camera mapping, pose frame, time model, physical event, or any Lighthouse correction gate. No native solver threshold or production flag was changed.

## Scope and input provenance

Only local, previously saved inputs and the original `out/qlhs_replay.exe` were used. There was no ADB, Pico, camera, SteamVR, or Lighthouse access. Raw recordings, calibration coefficients, replay stdout, and the private calibration files were not added to the repository.

The short recording was `qlhs-20261015-191506.txt` (78 seconds). The focused session was `qlhs-20261015-212939.txt` (474 seconds), and the independent held-out session was `qlhs-20261015-202605.txt` (418 seconds). The replay executable used for all runs had SHA-256 `0dfe732a8be75e31867790ef6c91176b2394b8371d4e1724a535d2a9058da6a4`.

The private `calibration-candidate.json` was checked against a fresh in-memory result from `pico/tools/prepare_calibration.py` reading the local private `pico-calibration.tar`. Its camera `T_BS`, Omni/Radtan intrinsics, distortion, and resolution entries matched the factory-derived draft. The input still had `HeadFromBody: null`, `mapping_verified=false`, and `pose_verified=false`; its bytes remained unchanged. Replay used the existing candidate camera mapping `C0→cam0, C3→cam1, C4→cam2, C5→cam3`, which remains unverified.

Commands used the same default timing on all runs, with `--pings` and no exposure override or offset sweep:

```text
qlhs_replay.exe <recording> --calib <private calibration-candidate.json> --dir <isolated temp state> --pings --pico-offline --pico-identity-control --pico-camera-mapping candidate --pico-cameras all|upper
qlhs_replay.exe <recording> --calib <private calibration-candidate.json> --dir <isolated temp state> --pings --pico-offline --pico-head-from-body <temp 4x4.json> --pico-camera-mapping candidate --pico-cameras all|upper
```

Each temporary state directory was isolated. Calibration flags were changed only in the replay's in-memory lab copy by the existing offline loader; the private source calibration was not rewritten.

## Coordinate conventions and tested basis set

The factory calibration draft reads the factory `T_BS` field and treats it as `BodyFromSensor`/`BodyFromCamera` (`p_B = T_BS · p_S`). The factory files establish the transform direction and provide the numeric camera extrinsics, but the available local documentation does not unambiguously define the axes of the factory `Body` frame relative to the OpenVR driver frame. `prepare_calibration.py` itself copies `T_BS`; it does not define a Body-to-Head transform.

The bundled Valve OpenVR header documents a right-handed system, `+X` right, `+Y` up, `-Z` forward, with translations in meters. `DriverPose_t` also distinguishes driver-local body/reference space from HMD Head space and says the driver's reference may be an internal IMU rather than the head. This defines OpenVR's coordinate convention; it does not show that PICO Connect's driver reference equals the factory camera `Body` frame.

Because the relative axis mapping could not be established from those contracts, the test enumerated all **24 determinant-`+1` signed axis permutations**. Each matrix represented `Body → Head` and used translation `(0,0,0)`; the 23 non-identity matrices passed the existing `--pico-head-from-body` validation, while identity used the explicit `--pico-identity-control` path. Translation zero was held constant as a diagnostic control for unknown translation, not treated as a calibrated value.

Rows in the table name the three Head rows as signed Body axes. `all` uses C0/C3/C4/C5; `upper` uses C0/C3. Values shown as `all/upper` are in that order. `max support` and `max tight` are the maximum acquisition-candidate support values sampled during that replay. Native `Solver::Add` was invariant across all 24 transforms: 8,367 for `all` and 5,973 for `upper`.

### 78-second basis test

| `BodyToHead` rows | Acquire all/upper | Max support all/upper | Max tight all/upper | Gain rejects all/upper | Accepted alignments all/upper | Lock seconds all/upper |
|---|---:|---:|---:|---:|---:|---:|
| `-X -Y +Z` | 21/21 | 6/5 | 1/2 | 20/21 | 0/0 | 0/0 |
| `-X +Y -Z` | 21/21 | 6/5 | 3/2 | 14/21 | 0/0 | 0/0 |
| `+X -Y -Z` | 21/21 | 7/5 | 2/2 | 18/21 | 0/0 | 0/0 |
| `+X +Y +Z` identity control | 21/21 | 7/8 | 3/3 | 5/4 | 0/0 | 0/0 |
| `-X -Z -Y` | 21/21 | 6/6 | 2/2 | 18/15 | 0/0 | 0/0 |
| `-X +Z +Y` | 21/21 | 3/5 | 1/2 | 21/21 | 0/0 | 0/0 |
| `+X -Z +Y` | 21/21 | 7/6 | 3/2 | 4/10 | 0/0 | 0/0 |
| `+X +Z -Y` | 21/21 | 6/6 | 1/1 | 20/20 | 0/0 | 0/0 |
| `-Y -X -Z` | 21/21 | 6/4 | 2/1 | 14/21 | 0/0 | 0/0 |
| **`-Y +X +Z` candidate** | **12/12** | **19/13** | **4/3** | **6/4** | **1/2** | **50.80/47.80** |
| `+Y -X +Z` | 21/21 | 6/4 | 2/2 | 20/21 | 0/0 | 0/0 |
| `+Y +X -Z` | 21/21 | 9/8 | 2/2 | 6/10 | 0/0 | 0/0 |
| `-Y -Z +X` | 21/21 | 8/6 | 3/2 | 7/13 | 0/0 | 0/0 |
| `-Y +Z -X` | 21/21 | 4/6 | 2/2 | 21/15 | 0/0 | 0/0 |
| `+Y -Z -X` | 21/21 | 6/6 | 4/1 | 14/12 | 0/0 | 0/0 |
| `+Y +Z +X` | 21/21 | 6/6 | 1/1 | 19/19 | 0/0 | 0/0 |
| `-Z -X +Y` | 21/21 | 10/4 | 5/1 | 13/21 | 0/0 | 0/0 |
| `-Z +X -Y` | 21/21 | 10/7 | 5/3 | 6/7 | 0/0 | 0/0 |
| `+Z -X -Y` | 21/21 | 6/4 | 3/2 | 20/21 | 0/0 | 0/0 |
| `+Z +X +Y` | 21/21 | 10/8 | 3/2 | 4/10 | 0/0 | 0/0 |
| `-Z -Y -X` | 21/21 | 6/6 | 2/2 | 20/18 | 0/0 | 0/0 |
| `-Z +Y +X` | 21/21 | 10/6 | 4/2 | 10/13 | 0/0 | 0/0 |
| `+Z -Y +X` | 21/21 | 8/6 | 3/2 | 14/20 | 0/0 | 0/0 |
| `+Z +Y -X` | 21/21 | 5/5 | 2/3 | 21/21 | 0/0 | 0/0 |

Across the identity control and the other 22 rotations, station support remained zero for channels 1, 7, 10, and 13, accepted alignments were zero, and lock duration was zero. Their acquisition candidates did not establish consensus. The candidate's per-station **maximum sampled** support was `ch1=19, ch7=0, ch10=15, ch13=13` for `all`, and `ch1=7, ch7=15, ch10=15, ch13=16` for `upper`; these channel maxima may occur at different times and are not a simultaneous support vector.

All runs had 21 support rejections for identity and the other 22 rotations, versus 7 (`all`) and 8 (`upper`) for the candidate. Body-ambiguity rejections were zero. Candidate gain rejections are reported in the table. The native replay exposes `condition` as a fit-status boolean, not as a separate per-candidate conditioning-reject counter; `final_condition` was false for every basis run. Timing-estimate successes were zero throughout.

The existing native constants `ACQ=12` and `TIGHT_N=6` were not changed. Every non-candidate rotation's sampled maxima stayed below both single-gate values (`max support ≤10`, `max tight ≤5`); the candidate reached support 19 (`all`) and 13 (`upper`) and was accepted. No candidate was selected just because it produced Acquire proposals.

## Fixed-candidate replay and holdout

Only the `-Y +X +Z` candidate and identity control were taken forward. No other 78-second rotation reached an accepted alignment or had nonzero per-station support; therefore there was one plausible geometry candidate, plus the baseline control, within the three-hypothesis cap. The candidate matrix was frozen before either long recording:

```text
HeadFromBody =
  0  -1   0   0
  1   0   0   0
  0   0   1   0
  0   0   0   1
```

This is a proper `+90°` rotation about its matrix `Z` axis, determinant `+1`, with zero diagnostic translation. It was not fitted on the 474-second or 418-second recordings.

Per-channel values below are each channel's maximum `PICO_STATUS` support over the full replay, not a simultaneous vector. `condition` is the final native fit-status field. The native code has no distinct conditioning-rejection counter; support, gain, body-ambiguity rejection counters are listed as emitted.

| Recording | Hypothesis | Set | Solver::Add | Acquire | Max support/tight | Station max support ch1/ch7/ch10/ch13 | Rejects support/gain/ambiguity | Accepted alignments | Timing estimates | Locked seconds (episodes) | Final condition/locked |
|---|---|---|---:|---:|---:|---|---:|---:|---:|---:|---|
| 474 s focused | identity | all | 79,870 | 137 | 9/3 | 0/0/0/0 | 137/102/0 | 0 | 0 | 0 (0) | false/false |
| 474 s focused | identity | upper | 45,853 | 144 | 7/2 | 0/0/0/0 | 144/126/0 | 0 | 0 | 0 (0) | false/false |
| 474 s focused | fixed candidate | all | 79,870 | 52 | 18/6 | 156/314/117/1,211 | 48/24/0 | 1 | 0 | 437.05 (1) | false/true |
| 474 s focused | fixed candidate | upper | 45,853 | 52 | 18/5 | 174/296/113/1,202 | 48/27/0 | 1 | 0 | 439.05 (1) | false/true |
| 418 s holdout | identity | all | 41,107 | 119 | 5/3 | 0/0/0/0 | 119/119/0 | 0 | 0 | 0 (0) | false/false |
| 418 s holdout | identity | upper | 28,949 | 124 | 6/2 | 0/0/0/0 | 124/123/0 | 0 | 0 | 0 (0) | false/false |
| 418 s holdout | fixed candidate | all | 41,107 | 48 | 19/5 | 298/224/267/74 | 45/22/0 | 1 | 0 | 369.65 (1) | false/true |
| 418 s holdout | fixed candidate | upper | 28,949 | 49 | 14/4 | 297/224/246/69 | 47/25/0 | 1 | 0 | 368.65 (1) | false/true |

The candidate therefore produces **accepted native alignments on all three existing Pico recordings**, and the locked result generalizes from the 78-second selection session to the 474-second session and the 418-second holdout. `all` versus `upper` retains the accepted alignment and similar lock duration in the longer sessions. The numerical outcome is not an offline-only synthetic scene; it is replay of saved Pico-origin recordings through the original native solver. It is still an offline replay, not a live headset result.

The accepted geometry is stronger evidence than raw Acquire-candidate count: the identity controls produced many proposals but no support acceptance, no accepted alignment, no station support, and no lock. For the candidate, the original solver reported accepted alignments and persistent lock, while `final_condition=false` and timing-estimate successes remained zero. Do not collapse these distinct metrics or treat lock as proof of a calibrated physical transform.

## Interpretation and remaining limits

- **Discrete orientation evidence:** `BodyToHead_-Y+X+Z` is the only tested zero-translation signed permutation that established native support and accepted alignment across the tested camera sets and recordings.
- **Not a complete calibration:** all 24 hypotheses shared zero translation. Factory `T_BS` supplies camera-to-Body extrinsics, not Body-to-Head translation. The existing result cannot justify retaining a zero translation in production.
- **Conditional camera identity:** the replay used the candidate C0/C3/C4/C5 factory camera mapping. `mapping_verified` remains false; a different mapping may alter the geometry.
- **No timing conclusion:** all native timing-estimate counts were zero. No exposure offset, clock relation, physical SOF, or pose timestamp was established.
- **No vendor pose API claim:** the conditional static search for a Pico native tracking-body pose API was not performed because the offline basis test found a candidate and validated it on two longer sessions. This report does not claim such an API exists or does not exist.
- **No production acceptance:** `HeadFromBody` is a diagnostic candidate; `pose_verified` and all other geometry/timing gates remain false.

## Next experiment

The one missing geometric measurement is an independently referenced **full 6DoF factory-Body-to-OpenVR-Head transform**, with varied rotations/translations and withheld validation. The candidate rotation is repeatable, but its translation is unmeasured and the local OpenVR driver frame is not tied to factory `Body`. A single paired-pose calibration experiment may use a vendor pose API only if its contract explicitly identifies the factory Body frame and supplies a usable time association; otherwise use a surveyed target rigidly tied to that Body datum and concurrent OpenVR Head poses. Solve once, freeze the transform, and validate on withheld poses. This is necessary because a zero-translation rotation-only candidate cannot satisfy the full transform required by the geometry loader. Do not run it as part of this offline result.

## Verification and safety gates

- 24 proper signed-axis matrices generated and validated (`det=+1`, translation zero); 48 short-session replays completed (all/upper).
- Fixed candidate plus identity control replayed on the 474-second focused session and 418-second holdout (8 runs total); all exit codes were zero.
- The 78-second private calibration JSON remained byte-identical after replay; its factory-derived camera entries matched `prepare_calibration.py` output.
- No source, thresholds, factory coefficients, recordings, calibration files, or private replay outputs were changed or committed.
- `python -m unittest pico.tests.test_p3c_native_replay -v` — **12 tests, PASS**.
- `python -m unittest discover -s pico/tests -p 'test_*.py'` — **298 tests, PASS**.
- `git diff --check` — **PASS**.

Unchanged safety gates:

```text
exact_time=false
mapping_verified=false
pose_verified=false
shared_buffer_identity_verified=false
frame_meta_bridge_verified=false
physical_event_verified=false
live_lighthouse_correction_allowed=false
```
