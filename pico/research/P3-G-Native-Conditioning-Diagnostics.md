# P3-G — Native Solver Conditioning Diagnostics

**Date:** 2026-10-20
**Branch:** `feature/pico-support`
**Starting revision:** `e23dcf55209e425940649fe8142b7c5eebe123cc`
**Outcome:** `WEAK_YAW_OR_TRANSLATION_MODE`; causal origin remains `UNRESOLVED`

## Result

The proximate failure is measured: every eligible final `Fit()` in the two fixed replays had `lambda_min < 0.047`, far below the unchanged native condition threshold `1.0`. The weakest normalized eigenmode was consistently dominated by the fit's translation coordinates (`tx` and `tz`, with a smaller `ty` component and little yaw contribution). The eigenvalue calculation passed synthetic positive/negative controls and an independent NumPy reference check; replay solver decisions and status output matched P3-F exactly.

The recordings do **not** establish why information in that mode is weak. Spatial-cell counts changed little between lower- and higher-`lambda_min` portions, while effective weight mass varied substantially. Camera contributions selected by the fit gate were also highly uneven, especially in the held-out replay, although the candidate factory-camera mapping remains unverified. The data therefore support the specific weak mode, but do not distinguish insufficient parallax from camera/extrinsic association mismatch.

## Scope and replay inputs

This was offline replay of the existing 474-second focused recording and 418-second held-out recording using the original QuestLHSync solver. No Pico, ADB, SteamVR, camera, Lighthouse, driver runtime, or tracking configuration was accessed. No new transform, mapping, or timing hypotheses were tested. Both commands used `--pings`, the existing fixed `BodyToHead_-Y+X+Z` transform, candidate mapping, all four cameras, baseline exposure/timing settings, and separate empty state directories. `--learn` and exposure overrides were not used.

Before replay, the recordings, candidate calibration, fixed transform and executable were SHA-256 checked. Recording and calibration hashes matched the P3-F private run metadata. The calibration and transform were not modified.

| Run | Input duration | Exit | Eligible `Step()` fits | `fit.ok` | `cond=true` | Executable SHA-256 |
|---|---:|---:|---:|---:|---:|---|
| Focused | 474 s | 0 | 438 | 438 | 0 | `d7c88a87c059be26295ffb26a3483da5f176b0a5406251dc007a03772b68d945` |
| Held-out | 418 s | 0 | 370 | 370 | 0 | `d7c88a87c059be26295ffb26a3483da5f176b0a5406251dc007a03772b68d945` |

The 438/370 fit samples are the final `Fit()` calls made by `Solver::Step()` when the solver had an alignment and a usable ray window. They are not the count of all one-second status records. Private stdout, stderr, exact argv, run metadata, isolated state, and diagnostic time series remain outside Git under `%LOCALAPPDATA%\QuestLHSync\private-evidence\p3g-native-conditioning-20261020T102455Z`. No raw recording, calibration, pose, station coordinate or station serial is included in this report.

## Replay-only instrumentation

`QLHS_REPLAY_DIAGNOSTICS` now captures the final `Fit()` called by the ordinary `Solver::Step()` path and emits a bounded series (up to 10,000 fit samples; overflow is counted). For each sample it records fit status, observation count, parameter dimension, every eigenvalue, the normalized minimum-eigenvalue eigenvector, `lambda_min`, `lambda_max`, ratio, robust-weight summaries, strongly downweighted-row count, viewpoint/direction cell counts, and camera/station observation histograms. Histogram output contains camera IDs and station counts by sorted slot only; it omits station identities and coordinates.

The eigenvector is expressed in the **scaled Fit parameterization**, not as a physical camera displacement:

- `eta_yaw = delta_yaw / COND_YAW`, where `COND_YAW = 0.1 deg`.
- `eta_tx/y/z = delta_y[1..3] / COND_T`, where `COND_T = 0.01 m`. `y[1..3]` are translation updates to the transformed station-centroid position inside `Fit()`, not measured camera or body motion.
- `SIG_R = 0.1 deg`; the matrix is the sighting-only robust information matrix built from the existing cross-product residual Jacobian and native row weights. The weak vector is unit-normalized; its sign is canonicalized for stable reporting.

The diagnostic robust weight for one observation is the mean of the three existing component weights `(1 + z²)^(-3/2)` at the final fit. `strongly_downweighted` is a descriptive count where that mean is below `0.5`; this does not change a solver gate. `effective_weight_mass` is the sum of existing time-decay/cell weights multiplied by mean robust weight. Viewpoint bins reuse the solver's 5 cm origin quantization; direction bins reuse its component-wise `1/30 rad` key. These are count summaries, not a claim that every cell is statistically independent.

The existing `MinEig(H, np) >= 1.0` remains the only source of the solver condition decision. The replay-only Jacobi eigensystem runs after that decision and does not change residuals, Jacobians, robust weights, iterations, thresholds, or alignment decisions. The standard QuestLHSync driver was separately compiled from the normal driver sources without defining `QLHS_REPLAY_DIAGNOSTICS`; the temporary DLL was built outside the repository (SHA-256 `528b76b32a3bcb41facc0804f4373a2e0b6eb83a27f7dec970c9d80c3d3c8819`).

## Diagnostic validation

The replay self-test checks a constructed symmetric matrix with known spectrum `{0.5, 2, 5, 9}` and mixed eigenvectors. The diagnostic eigensystem returned those eigenvalues, a unit minimum eigenvector with residual `1.67e-16`, and the unchanged native `MinEig()` returned `0.5`. Python `numpy.linalg.eigh` independently matched the output eigenvalues and absolute eigenvector components.

| Synthetic control | Observations | Viewpoint / direction / joint cells | `lambda_min` | Native condition |
|---|---:|---:|---:|---|
| Diverse viewpoints and station geometry | 96 | 24 / 71 / 96 | 2.86723134 | true |
| One viewpoint and tightly clustered station directions | 128 | 1 / 1 / 1 | 0.0000179991 | false |

The positive control crosses the original `1.0` threshold without changing it; the negative control remains below it. A separate control exercised storage through `Solver::Step()` and captured one fit sample. This validates the diagnostic path and threshold interpretation, not Pico calibration or geometry.

## Pico recording results

Eigenvalue quantiles are minimum / p10 / median / p90 / maximum across eligible fits. The fit condition is based on the **absolute minimum eigenvalue**, not on the eigenvalue ratio.

| Run | Eigenvalue | min | p10 | median | p90 | max |
|---|---|---:|---:|---:|---:|---:|
| 474 s | `lambda_0` | 0.015330 | 0.021055 | 0.032019 | 0.039491 | 0.046265 |
| 474 s | `lambda_1` | 0.111903 | 0.154044 | 0.229160 | 0.301081 | 0.364374 |
| 474 s | `lambda_2` | 1.809206 | 2.899616 | 4.383950 | 5.482915 | 6.000519 |
| 474 s | `lambda_3` | 2.194796 | 3.513993 | 5.138796 | 6.329051 | 7.591568 |
| 418 s | `lambda_0` | 0.007113 | 0.010868 | 0.016036 | 0.028468 | 0.036345 |
| 418 s | `lambda_1` | 0.065248 | 0.102136 | 0.242358 | 0.309996 | 0.352850 |
| 418 s | `lambda_2` | 1.228341 | 1.843959 | 3.604563 | 4.978707 | 6.181227 |
| 418 s | `lambda_3` | 1.618752 | 2.288908 | 4.813565 | 6.037496 | 6.799564 |

The largest `lambda_min` was 21.6× below threshold in the focused run and 27.5× below threshold in the held-out run. Median minimum eigenvalues were 31.2× and 62.4× below threshold respectively. The median `lambda_min/lambda_max` ratios were 0.00625 and 0.00459.

Median absolute components of the normalized weakest mode were:

| Run | yaw | `tx` | `ty` | `tz` | Translation share of squared mode magnitude |
|---|---:|---:|---:|---:|---:|
| 474 s | 0.159 | 0.678 | 0.395 | 0.601 | 97.5% |
| 418 s | 0.173 | 0.683 | 0.341 | 0.633 | 97.0% |

This is a stable, translation-dominated **scaled solver mode**. It must not be read as a physical camera/body translation direction without a verified transform between those frames.

| Run | Median obs (p10) | Median viewpoint / direction / joint cells | Median effective weight mass | Median robust mean | Median strong-downweighted rows | Status samples locked / conditioned |
|---|---:|---:|---:|---:|---:|---:|
| 474 s | 5,059 (1,179) | 73 / 35 / 274 | 29.14 | 0.901 | 225 | 438 / 0 of 475 |
| 418 s | 2,493 (696) | 76 / 35 / 283 | 26.99 | 0.832 | 301 | 370 / 0 of 418 |

The strong-downweight cutoff is descriptive only. Across all fits it counted 96,246 rows in the focused run and 104,198 in the held-out run; median proportions were 4.4% and 10.3% of used observations. The 474 s fit had four active station slots in every sample; the 418 s fit had three or four (median four). The status stream showed four positive station channels at its median sample in both runs.

Selected in-gate observations were unevenly distributed by camera: approximately `68.2% / 2.3% / 29.5% / 0%` for camera IDs `3 / 4 / 5 / 0` in the 474 s replay, and `97.2% / 0.9% / 1.9% / 0%` in the 418 s replay. All four cameras had observations admitted to the solver upstream, so the selection skew occurs in the final fit gate. This is a warning about the unverified mapping/extrinsics or observation association, not proof that any specific mapping is wrong. The 474 s station-slot share was also concentrated (`75.9%, 10.2%, 7.0%, 6.9%` sorted); 418 s was more balanced (`32.2%, 26.0%, 21.2%, 20.5%`). No station identity is attached to those shares.

Between lower- and upper-`lambda_min` quartiles, viewpoint and direction cell counts were nearly unchanged: focused 474 s medians were `69 / 35` versus `72.5 / 34`; held-out 418 s medians were `78 / 36` versus `82 / 36`. Effective weight mass changed more (`20.30 → 34.43` and `14.01 → 35.09`). Descriptive Pearson correlation of `lambda_min` with viewpoint cells was 0.20/0.24 and with direction cells −0.11/0.22; correlation with effective weight mass was 0.93/0.89. This does not establish that movement is sufficient: the high correlation is expected in a summed information matrix, and the cell counts do not encode the geometry of the null direction.

The original replay's support and lock metrics remain strong despite the weak information mode:

| Run | Native locked seconds | Accepted alignments | Median / p90 fit residual | Alignment yaw range | Endpoint translation change |
|---|---:|---:|---:|---:|---:|
| 474 s | 437.05 | 1 | 0.344° / 0.380° | 5.954° | 73.89 cm |
| 418 s | 369.65 | 1 | 0.335° / 0.365° | 7.530° | 51.96 cm |

`locked` is a separate support decision (`Score(c) >= 10`) and does not require `cond=true`; it can therefore persist while the least-informed fit mode remains below threshold. The large relative alignment drift is consistent with that distinction. P3-G did not enable timing learning, so it provides no new timing-estimator evidence; P3-F previously found that its `--learn` call gate was blocked by `cond=false` at sampled statuses.

## Grounded diagnosis

- **`WEAK_YAW_OR_TRANSLATION_MODE` — confirmed numerical mode:** both sessions show a repeatable weak mode dominated by normalized translation components. It is the direct reason the native absolute eigenvalue condition test fails.
- **`INSUFFICIENT_PARALLAX` — not established:** there are tens of distinct origin/direction cells, but their counts neither prove nor disprove adequate parallax. Lower-eigenvalue intervals did not have fewer cells in these runs.
- **`GEOMETRY_OR_ASSOCIATION_INCONSISTENCY` — plausible, not confirmed as root cause:** the final fit gate heavily favors a subset of camera inputs and robust downweighting is higher in the held-out session. Candidate mapping/extrinsics remain unverified, while the inlier residuals are low and four station slots are usually represented.
- **`FIT_DIAGNOSTIC_OR_IMPLEMENTATION_ISSUE` — no evidence found:** known-matrix reference checks pass, native `MinEig()` agrees on the reference spectrum, positive and negative controls behave as expected, and all recorded P3-F solver status/count rows and 10-second alignment traces are byte-for-byte identical to the P3-G runs.
- **Causal origin: `UNRESOLVED`:** the evidence identifies the weak mode but cannot tell whether it comes from directional parallax, candidate camera association/extrinsics, or both.

## One justified next recording

If the headset is available, the single useful follow-up is a short (about 60 s) motion-rich recording replayed once with this same frozen transform and mapping: keep at least three Lighthouse bases, preferably all four, visible; spend about 10 s still as a control; then translate smoothly through a roughly 25–30 cm horizontal figure-eight/box with small vertical variation while yawing slowly through both directions. Keep motion below the solver's existing high-speed rejection rate and do not change calibration or mapping during the run.

The comparison should check whether the same weakest mode gains information during the translated segment, with camera and station fit shares, residuals, and `lambda_min` reported. A diagnostic success is at least 10 continuous one-second fits with the unchanged `lambda_min >= 1.0` condition and support from at least three stations; a partial outcome is a repeatable rise above this baseline without crossing 1.0. This record would test added observability under the current candidate association; it would not itself verify `HeadFromBody`, camera mapping, physical SOF/exposure timing, or Lighthouse readiness. If the camera fit-share skew persists, another parallax recording alone will not resolve the association question.

## Verification and safety

- Replay executable built with `QLHS_REPLAY_DIAGNOSTICS`; `--conditioning-self-test` passed.
- Synthetic reference, positive/negative controls, and `Solver::Step()` capture regression passed.
- `python -m unittest discover -s pico/tests -p 'test_*.py'` — 299 tests, PASS (53.875 s). Expected blocked/error text was emitted by negative CLI tests.
- `cmd /c build_replay.bat` — exit 0; both `qlhs_replay.exe` and ordinary `qlhs_nettest.exe` built. The existing batch environment also prints a `Fastboot++\` command-not-found line before successful compilation; this did not affect the return code.
- P3-F semantic comparison: all `PICO_OFFLINE`, `PICO_SYNC`, `PICO_NATIVE`, `PICO_STATUS`, camera/stage/station summaries and 10-second alignment traces matched for both recordings.
- Ordinary driver build without `QLHS_REPLAY_DIAGNOSTICS` succeeded in a temporary output directory; existing project driver outputs were not replaced.
- `git diff --cached --check` — PASS on the final staged source, regression and report.
- Full Python suite, native replay build, `git diff --check`, and final Git/remote checks are recorded after commit.
- `Solver::Acquire`, `Fit`, `Hypotheses`, `Timing`, support thresholds, and production flags were not mathematically changed. No production driver instrumentation was added.
- Safety gates remain `exact_time=false`, `mapping_verified=false`, `pose_verified=false`, `shared_buffer_identity_verified=false`, `frame_meta_bridge_verified=false`, `physical_event_verified=false`, and `live_lighthouse_correction_allowed=false`.
