# P3-H — Controlled Parallax Validation

**Date:** 2026-10-21
**Branch:** `feature/pico-support`
**Starting revision:** `23ccb7ab8e76e35c94d3b80c9b0875f3a53ebd00`
**Verdict:** `PARALLAX_CONFIRMED_IMPROVEMENT` (per the defined conditioning acceptance threshold)

## Scope and safety

One offline replay of the new 117.242-second Pico recording was run through the existing P3-G diagnostic build. The factory-derived private calibration and frozen P3-G transform hypothesis were reused unchanged, with the candidate mapping and all four source cameras. The transform has the requested rotation and zero translation; zero translation remains diagnostic only. The state directory was new and isolated. `--pings` was enabled; `--learn`, exposure overrides, timing sweeps, device access, SteamVR, camera operation, and live correction were not used.

No solver implementation, production configuration, calibration, recording, Magisk module, PICO Connect, SLAM, or tracking correction was changed. The raw recording, calibration, transform, replay output, argv, manifest, and isolated state remain local/private and are not in Git.

## Input validation

The recording was present, UTF-8 decodable, **1,918,784 bytes**, and its SHA-256 was verified as `190acdc5cddc173550ed0c3c47abfc3b063dfa9b08417657b2241303bbdd578a`. The digest and replay manifest were also checked again after replay; the input file was unchanged.

| Record family | Validation result |
|---|---|
| `U F` | 11,724 valid frames; 2,931 each from C0/C3/C4/C5; 117.200–117.203 s coverage; blob candidate counts 2,022 / 8,422 / 2,439 / 2,935 |
| HMD `P` | 7,812 finite, structurally valid poses; 117.234 s coverage; rotation matrices passed orthonormality checks |
| Raw station `S` | 464 valid channel-first records; four anonymous station identities, 116 raw records per station |
| Transformed station `S` | 48 valid channel-last records, 12 per station; classified separately and rejected by the replay parser, never passed as raw poses |
| `Q` clock sync | 428 valid records; host receive and headset monotonic values were nondecreasing; 116.821 s coverage |

No malformed relevant `U`, `P`, `S`, or `Q` records were found. The file has 512 station snapshots total, but only the 464 channel-first records are raw observations suitable for `SetStationsRaw`; the 48 channel-last records are already transformed. The replay independently reported `raw_schema=464`, `channel_last_rejected=48`, `ambiguous_rejected=0`, `malformed_rejected=0`, and four cross-format IDs. No station identity or coordinate is recorded here.

Recorded HMD pose positions span **1.022 m / 0.189 m / 0.668 m** by axis. Using centered one-second pose windows, translation speed was p50/p90/p95/max **0.057 / 0.163 / 0.226 / 0.434 m/s**, and angular speed was **23.1 / 52.6 / 67.1 / 104.3 deg/s**. Translation-rich intervals (`>=0.08 m/s`) occurred at 0.5–2.4, 39.7–42.2, 49.7–51.2, 56.9–58.8, 64.7–65.8, 75.9–77.0, 80.3–82.3, 83.3–88.6, 90.1–94.5, 94.9–98.0, 98.6–100.1, 100.8–102.5, and 115.4–116.9 seconds. These intervals were derived from the recorded poses; the planned segment timings were not assumed.

For per-fit comparison only, motion classes use centered one-second pose rates: stationary is translation `<0.02 m/s` and rotation `<2 deg/s`; translation-rich is translation `>=0.08 m/s`; rotation-rich is rotation `>=10 deg/s` while translation is `<0.08 m/s`; remaining samples are transitional. These descriptive cutoffs do not affect the solver.

## Replay integrity and outcome

The replay executable SHA-256 matched the P3-G diagnostic binary: `d7c88a87c059be26295ffb26a3483da5f176b0a5406251dc007a03772b68d945`. Its `--conditioning-self-test` passed immediately before the replay, including the known eigenvalue reference and positive/negative controls. The private calibration and transform hashes matched the existing P3-G run manifest.

The single replay returned exit code 0 in 4.234 seconds, produced 44,202 stdout bytes and no stderr, with no dropped diagnostic fits. It parsed/submitted all 11,724 supported camera frames. Native acquisition accepted one alignment after about 95 seconds; it remained locked for **21.25 seconds** through the end of the recording. Timing estimate successes were zero and timing learning remained disabled.

## Conditioning comparison

| Replay | Eligible diagnostic fits | `lambda_min` median / p90 / max | Fits `lambda_min >= 1` | Longest consecutive conditioned run | Fit station support |
|---|---:|---:|---:|---:|---|
| P3-H, new 117 s recording | 21 | **1.748 / 1.808 / 1.821** | **21** | **15 one-second status samples** (103–117 s; 14 s endpoint span) | Three active station slots in every fit |
| P3-G 474 s focused | 438 | 0.032019 / 0.039491 / 0.046265 | 0 | 0 | Four active slots in every fit |
| P3-G 418 s held-out | 370 | 0.016036 / 0.028468 / 0.036345 | 0 | 0 | Three or four active slots |

All 21 P3-H diagnostic fits had `fit_ok=true`, `lambda_min >= 1.0`, native `cond=true`, and support from at least three active station slots. The one-second status stream has two conditioned intervals: 96–101 s (six samples) and 103–117 s (15 samples), separated by an unconditioned status at 102 s. The 15 later Fit samples span 102.95–116.94 s and all meet the eigenvalue and support criteria. This longest interval exceeds the strong acceptance criterion of ten consecutive one-second conditioned fits with three-station support. The first status alignment was at 95 s; the first lock and conditioned status were at 96 s. No eigenvalues are claimed for the preceding interval because the diagnostic only records eligible final fits after alignment and a usable ray window.

P3-H median `lambda_min` is **54.6×** the P3-G 474 s median and **109×** the P3-G 418 s median. P3-H maximum is **39.4×** and **50.1×** those respective maxima. This is a clear improvement in the recorded native fit conditioning under the same frozen replay hypothesis. It is not proof that parallax alone caused the change: the new dataset differs in motion and observation population, and the fit itself carries observations across adjacent pose windows.

The normalized weakest-mode median absolute components changed from P3-G's translation-dominated mode to P3-H **yaw 0.823, tx 0.477, ty 0.298, tz 0.075**. These remain scaled internal Fit coordinates, not physical camera/body motion. The eigenvalue threshold is unchanged at `1.0`.

## Motion intervals, cameras, stations, and residuals

The 21 fits were classified from the nearest recorded HMD-pose rate sample:

| Pose class | Fits | `lambda_min` median / p90 / max | Conditioned fits |
|---|---:|---:|---:|
| Stationary | 8 | 1.789 / 1.820 / 1.821 | 8 |
| Translation-rich | 5 | 1.657 / 1.714 / 1.717 | 5 |
| Rotation-rich | 4 | 1.765 / 1.786 / 1.788 | 4 |
| Transitional | 4 | 1.770 / 1.792 / 1.792 | 4 |

Conditioning was already above threshold in translation-rich fits and persisted afterward. The translation-rich median was about **7.4% lower** than the stationary-class median, so these within-run buckets do **not** show an additional instantaneous eigenvalue rise during translation. Several stationary-class fits followed the large motion intervals, and the solver's recent observation window overlaps prior motion; the categories are not independent experiments. The supported conclusion is that this motion-rich capture produced a conditioned native solution, not that each translation segment independently caused the conditioning.

Selected final-fit observation shares across all 21 fits were **C0 3.49%, C3 85.43%, C4 5.02%, C5 6.05%**. Historical C3 dominance has **not been resolved**: P3-H is more C3-heavy than P3-G 474 s (68.2%), though less than P3-G 418 s (97.2%). All four cameras contributed solver rows upstream, but the final fit still selected C3 disproportionately. This continues to warrant checking camera mapping/extrinsics and observation association.

Three station slots had nonzero selected rows in every fit, but the aggregate slot shares were highly uneven: **83.57%, 15.21%, 1.22%, 0%**. Thus the acceptance station-count condition is met, while effective support remains concentrated in two slots. Per-fit viewpoint/direction/joint-cell counts were median **79 / 56 / 189**, p90 **80 / 57 / 190**, and maximum **80 / 57 / 200**.

Robust effective weight mass was median/p90 **37.310 / 38.535**. The descriptive strong-downweight count was **6,040 / 25,924 fit rows (23.30%)**, with per-fit downweight fraction median/p90 **22.81% / 25.11%**. The status stream's aligned `median_deg` residual proxy was median/p90 **0.3594° / 0.3828°** across 22 aligned status samples. These are solver residual summaries, not timing or physical-event error measurements.

## Decision and limits

**`PARALLAX_CONFIRMED_IMPROVEMENT`** under the requested quantitative acceptance rule: the longest interval contains 15 consecutive one-second conditioned status samples, with corresponding late Fit samples above the unchanged eigenvalue threshold and at least three active station slots each. The new dataset raised conditioning from P3-G values below 0.047 to above 1.0. The data do not isolate parallax as the sole cause, and the fit remains severely camera- and station-slot-skewed.

The capture does not verify the candidate camera mapping, the diagnostic zero-translation transform as a physical `HeadFromBody`, frame identity, timestamp source/clock domain, SOF/exposure timing, or Lighthouse synchronization. All timing, mapping, pose, shared-buffer, frame-metadata, physical-event, and live Lighthouse correction gates remain `false`.

**One next practical step:** investigate the candidate camera mapping/extrinsics and observation-to-camera association offline using the existing calibration and recordings before requesting any further movement capture. Another identical parallax recording is not justified while the C3 final-fit share remains 85.43% and one active station slot contributes only 1.22%.

## Verification

- P3-G diagnostic self-test: PASS; executable SHA-256 matched the published P3-G report.
- Single P3-H replay: PASS, exit 0, no stderr, 21/21 eligible fits conditioned, zero diagnostic drops.
- Input SHA-256 and replay stdout SHA-256: verified in the private local run manifest.
- Python regression suite and Git checks are recorded for the P3-H commit; no raw capture, private calibration, raw station identity, or raw coordinate is committed.
