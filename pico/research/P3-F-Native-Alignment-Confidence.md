# P3-F — Native Alignment Confidence and Timing

**Date:** 2026-10-20

**Branch:** `feature/pico-support`

**Starting revision:** `2504c9b0d38993048774bad5a632a109fb8f8be1`
**Outcome:** `GEOMETRY_CONDITIONING_BLOCKED`

## Scope and evidence

This was an offline replay of the existing Pico recordings through the original QuestLHSync solver. No Pico, ADB, SteamVR, camera, Lighthouse, driver, or tracking configuration was accessed. The P3-E per-second candidate output was not retained. Existing P3C private replay output was checked and proved to be identity-control output, so it was not used as evidence for the P3-E transform. The fixed candidate was replayed on the 474 s and 418 s records, and the bounded P3-F comparisons were run below.

The replay binary was rebuilt using `build_replay.bat` and had SHA-256:

`ba86b71b73a3cb74253ab198233042f95085aadc18ab64cfaf92cb01a436a7bf`

The three recording files matched the hashes in the existing P3C run manifest. The private calibration drafts were read unchanged and kept outside Git. Each replay used a new, empty state directory. Replay stdout, stderr, transform matrices, and state files remain only in local private evidence; no recording, calibration, pose, room coordinate, or station serial is included here.

Fixed transform (Body → Head) for the baseline:

```text
 0 -1  0  0
 1  0  0  0
 0  0  1  0
 0  0  0  1
```

The candidate mapping remains unverified: `C0→cam0, C3→cam1, C4→cam2, C5→cam3`. The previous placement guess swaps only C4 and C5: `C4→cam3, C5→cam2`.

## Native alignment quality

`PICO_STATUS` is emitted about once per second. Lock time comes from the native replay diagnostic counter (50 ms steps); conditioning duration, residual distribution, and support coincidence are measured from the status samples. A “good residual interval” here means status `median_deg ≤ 0.5°`, using the existing `Solver::INLIER = 0.5` degree radius as a descriptive cutoff. It is not a new solver gate. Residual quantiles use all status samples with a numeric `median_deg`, not only a hand-selected locked subset.

| Recording | HeadFromBody / mapping / cameras | Locked (fraction) | Condition true (including locked) | Residual median / p90 / max (°) | Longest good-residual interval | Accepted / lock breaks | Peak simultaneous support c1/c7/c10/c13 |
|---|---|---:|---:|---:|---:|---:|---:|
| 78 s | rotation, zero / candidate / all | 50.80 s (65.3%) | 0 / 77 sampled s | 0.378 / 0.392 / 0.423 | 50 s | 1 / 0 | 18 / 0 / 14 / 10 |
| 78 s | rotation, zero / placement guess / all | 0 s (0%) | 0 / 77 sampled s | 0.312 / 0.351 / 0.353 | 44 s | 1 / 0 | 9 / 5 / 9 / 16 |
| 474 s | rotation, zero / candidate / all | 437.05 s (92.2%) | 0 / 474 sampled s | 0.344 / 0.380 / 0.417 | 437 s | 1 / 0 | 138 / 209 / 104 / 939 |
| 474 s | rotation, zero / candidate / upper | 439.05 s (92.6%) | 0 / 474 sampled s | 0.325 / 0.368 / 0.417 | 439 s | 1 / 0 | 55 / 91 / 68 / 1,194 |
| 474 s | rotation, zero / placement guess / all | 437.05 s (92.2%) | 0 / 474 sampled s | 0.325 / 0.372 / 0.411 | 437 s | 1 / 0 | 69 / 104 / 55 / 1,211 |
| 418 s | rotation, zero / candidate / all | 369.65 s (88.5%) | 0 / 417 sampled s | 0.335 / 0.365 / 0.405 | 369 s | 1 / 0 | 298 / 222 / 99 / 66 |
| 418 s | rotation, zero / candidate / upper | 368.65 s (88.3%) | 0 / 417 sampled s | 0.337 / 0.367 / 0.411 | 368 s | 1 / 0 | 288 / 224 / 82 / 66 |

The support vector is from one status instant with the largest sum of channel support, so its values are simultaneous. Separately, the largest number of positive-support channels was four in each long run. At least two channels had positive support in 92.2%/92.6% of 474 s all/upper samples and 88.5%/88.3% of 418 s all/upper samples. Per-channel maxima over the whole recording are not simultaneous and are intentionally not substituted for the vector above.

Across the candidate-mapping baseline, the native `locked` flag persisted for most of both long records, with one accepted alignment, one lock episode, and no lock break in each. This does not imply a stable alignment transform: the 10 s alignment summaries changed by 5.95° yaw range and about 0.74 m endpoint translation on 474 s all; the 418 s all run changed by 7.53° yaw range and about 0.52 m endpoint translation, with sampled translation component ranges up to 1.22 m. These are relative changes only; absolute alignment coordinates are omitted. Lock can coexist with substantial movement of the fitted Lighthouse alignment.

There were no `JUMP` status reports, no body-ambiguity rejections, and no accepted alignment forced by the mirror check. The fixed-transform long runs each accepted one alignment. The 78 s translation matrix had one additional acceptance for −5 cm X (one lock break) and two acceptances for −5 cm Y without a lock break. The additional acceptance is a reacquisition event, but the output does not establish that it was a mirror correction.

### Body/reference observations

The recordings contain 1,531, 9,088, and 8,325 `B` records for 78 s, 474 s, and 418 s respectively. `replay.cpp` parses those as worn/held Lighthouse devices and calls `Sync::OnBodyPose`; `Sync` connects its body-distance and body-motion callbacks to `Solver::BodyFavours`. Thus body/reference observations were available to the replay. The diagnostics report zero body-ambiguity rejections, but there is no counter for positive body-distance or body-motion influence. The evidence therefore confirms ingestion, not that those observations selected or corrected the accepted alignment.

## Timing::Estimate

The 474 s fixed transform was replayed with `--pings --learn` for both all and upper cameras using separate clean state directories. Compared with `--pings` without `--learn`, both runs had identical lock, residual, station-support, and final exposure metrics: timing successes `0`, `timing_learned=false`, final exposure `18.000 ms`.

The caller in `Sync::Check` permits an estimator invocation only when all of these hold: `cfg_.learn_timing`, `solver_.has_x()`, `st.cond`, `st.has_med`, `st.med < 0.4`, and `now - last_timing_ > 15 s`. No 1 Hz status sample in either `--learn` replay had `condition=true`; therefore the sampled call gate was blocked specifically at `st.cond`, despite locked intervals and residuals below 0.4°. No timing-success or split log was emitted. The native diagnostics expose successful estimates but not an attempt counter, so a sub-second transient invocation cannot be excluded from 1 Hz status alone; no invocation is evidenced by the saved output.

Because the call was not evidenced, the estimator's internal slow/fast sample counts, qualifying left/right turns, split, and bootstrap confidence interval were not produced. `PICO_SYNC still/fast` counters are general replay sighting classes and are not `Timing::Search`'s post-filter sample counts. They are not used here to claim that timing data were sufficient or insufficient.

For reference, the unchanged `Timing::Search` implementation filters slow-head observations below 10°/s, fast-head observations from 10–150°/s near a known station within 5°, needs 200 qualifying sightings on its first wide search or 40 later, requires left and right turns beyond 10°/s, rejects a left/right estimate split over 30 ms, and requires the bootstrap interval to be no more than 6 ms. These gates were not shown to have been reached. The timing result is `NOT_OBSERVED_AT_CALL_GATE`, not a failed timing estimate.

## Translation sensitivity

The seven fixed hypotheses use the same rotation and candidate mapping; only the diagnostic translation differs. Values are from the 78 s all-camera record. Condition remained false for all 77 covered status seconds.

| Translation (m) | Lock (s / %) | Residual median / p90 / max (°) | Accepted / breaks | Peak concurrent channels | Longest good-residual interval |
|---|---:|---:|---:|---:|---:|
| (0, 0, 0) | 50.8 / 65.3% | 0.378 / 0.392 / 0.423 | 1 / 0 | 3 | 50 s |
| (+0.05, 0, 0) | 53.8 / 69.2% | 0.344 / 0.382 / 0.388 | 1 / 0 | 3 | 53 s |
| (−0.05, 0, 0) | 52.8 / 67.9% | 0.350 / 0.392 / 0.405 | 2 / 1 | 3 | 53 s |
| (0, +0.05, 0) | 50.8 / 65.3% | 0.338 / 0.376 / 0.380 | 1 / 0 | 3 | 50 s |
| (0, −0.05, 0) | 53.8 / 69.2% | 0.372 / 0.378 / 0.383 | 2 / 0 | 4 | 53 s |
| (0, 0, +0.05) | 47.8 / 61.5% | 0.391 / 0.392 / 0.392 | 1 / 0 | 3 | 47 s |
| (0, 0, −0.05) | 53.8 / 69.2% | 0.362 / 0.404 / 0.437 | 1 / 0 | 3 | 53 s |

The matrix did not identify one clear translation: the best residual and the longest lock occur at different offsets. For the most informative Y cases, 474 s `+5 cm Y` kept the baseline lock at 437.05 s and slightly worsened p90 residual (0.385° versus 0.380°); `−5 cm Y` raised lock to 444.05 s but also worsened p90 (0.396°) and median (0.347° versus 0.344°). Both remained `condition=false`, with one accepted alignment and no lock breaks. There was no joint improvement worth freezing for an additional 418 s translation replay.

The final 10 s alignment summaries across the seven short-session translation hypotheses span up to 138.1° in wrapped yaw and 6.37 m in pairwise translation separation. This is evidence that the current metrics can admit widely separated alignment solutions under small diagnostic translation changes; it is not evidence for any one translation or for an explicit mirror correction. The large branch spread, combined with condition=false, makes `TRANSLATION_NOT_OBSERVABLE_FROM_CURRENT_METRICS` too strong as a standalone conclusion: the solver did not provide a conditioned solution from which observability could be assessed.

## Camera mapping comparison

The two mappings were compared at fixed rotation and zero translation. At 78 s, candidate mapping locked for 50.8 s versus 0 s for placement guess; placement guess had lower residuals but did not maintain lock. On 474 s all cameras, both mappings produced one accepted alignment and 437.05 s lock with no break. Placement guess had slightly lower residual median/p90/max (0.325/0.372/0.411°) than candidate mapping (0.344/0.380/0.417°), while both had `condition=false` and four supported channels concurrently. The long-run residual difference is small and the short-run behavior is not consistent with selecting solely by residual. Neither mapping is verified.

The first 78 s placement-guess invocation was rejected before replay because it was passed the candidate-specific draft. It was retried once with the already-existing placement-guess draft; that successful run is the mapping result above. No calibration draft was edited.

## Interpretation and next blocker

The native solver shows low angular residuals and long locked periods on both long records. However, its fit conditioning flag was false in every sampled status, including every locked status. In `Fit`, `cond` is based on `MinEig(H, np) >= 1.0`; the lock flag is separate and does not require `cond`. This distinction explains why the replay can stay locked while the fit remains unconditioned and the timing gate is unavailable.

Four station channels were simultaneously supported in status samples, so a simple lack of station count is not demonstrated. The existing output does not report the deficient Hessian eigenvector, per-degree-of-freedom information, or parallax distribution; it cannot separate insufficient parallax from mapping/extrinsic error or other geometry mismatch. Translation perturbations produce different accepted alignments, but neither translation nor mapping can be calibrated from these fits while conditioning is false.

**Decision: `GEOMETRY_CONDITIONING_BLOCKED`.** The next blocker is obtaining a conditioned geometric fit; this dataset does not identify its deficient mode. Do not treat the zero or ±5 cm translation as physical. A future independent full Body-to-Head translation measurement remains necessary for a production 6DoF transform, but by itself it does not fix the current lack of solver conditioning. No timing estimate was obtained.

## Verification and unchanged gates

- Successful bounded replay invocations: 17; one early placement-guess attempt was rejected before processing and retried with its matching existing draft.
- `build_replay.bat` returned 0 and built `qlhs_replay.exe` and `qlhs_nettest.exe`; it printed a `Fastboot++\` command-not-found line before the successful compiler output. The replay executable used afterward is SHA-pinned above.
- `python -m unittest pico.tests.test_p3c_native_replay -v` — 12 tests, PASS.
- `python -m unittest discover -s pico/tests -p 'test_*.py'` — 298 tests, PASS (53.987 s). Negative CLI tests emitted their expected usage/blocked messages.
- `git diff --cached --check` — PASS.
- No `Solver::Acquire`, `Fit`, `Hypotheses`, or `Timing` algorithm, thresholds, calibration source bytes, driver, module, or recording was modified.
- `mapping_verified=false`, `pose_verified=false`, `exact_time=false`, `shared_buffer_identity_verified=false`, `frame_meta_bridge_verified=false`, `physical_event_verified=false`, `live_lighthouse_correction_allowed=false`.
- Offline Python regression, native replay tests, build, and `git diff --check` results are recorded in the handoff after final verification.
