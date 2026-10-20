# P3-F Native Alignment Confidence Plan

> Offline analysis plan for the user-authorized P3-F replay and report.

**Goal:** Quantify the fixed P3-E candidate's alignment stability, Timing::Estimate behavior, bounded translation sensitivity, and two camera mappings using only saved recordings and the original native solver.

**Architecture:** Inspect the existing replay CLI, solver telemetry, fixed transform, and saved source recordings; replay only the bounded cases specified in P3-F using isolated state directories. Summarize only aggregate metrics and sanitized diagnostics in the report.

**Tech Stack:** Existing C++ native replay executable, PowerShell/Python orchestration as available, existing project tests/build.

**Spec:** User-provided P3-F request in the attached text.

## Global Constraints

- Offline only: no Pico, ADB, SteamVR, camera, or Lighthouse.
- Do not change native solver behavior, thresholds, production calibration, module, driver, or OBSERVE ONLY status.
- Keep mapping and pose verification false; exclude private calibration, poses, room coordinates, and station serials from Git.
- Preserve the exact replay executable SHA and use isolated state directories.

## Review Focus

- Status telemetry may be sampled at 1 Hz, so durations are sample-based estimates, not continuous ground truth.
- Translation sensitivity must not be confused with a translation calibration.
- Timing::Estimate may never run because an upstream gate is absent; report the exact first blocking gate.
- Support maxima per station must not be mistaken for simultaneous multistation support.
- The 418 s recording is not independent of the prior P3-E rotation selection.

### Task 1: Recover inputs and prior outputs

- Verify repo baseline and inspect P3-E report, replay CLI/source, local recordings, candidate calibration and private saved outputs.
- Record replay executable SHA; do not copy private calibration or raw telemetry into Git.

### Task 2: Define source-backed metrics

- Inspect PICO_STATUS/native diagnostics and solver timing code.
- Fix explicit definitions for lock/condition durations, residual quantiles/good intervals, multi-station simultaneity, reacquire/mirror/jump counters, and timing gate/rejection reasons.
- Build the existing replay tool if required without modifying solver logic.

### Task 3: Run bounded offline comparisons

- Use existing P3-E outputs if they contain per-second records; otherwise run the fixed rotation candidate on 474 s and 418 s.
- Run --pings --learn on 474 s all/upper with isolated clean state.
- Test seven fixed translation hypotheses on 78 s; test informative results on 474 s, and verify any clear winner on 418 s without further fitting.
- Compare only the two requested camera mappings on 78 s and, only if distinguishable, 474 s.

### Task 4: Report and verify

- Create P3-F report with concise numeric table and one required conclusion code.
- Run relevant regressions/build/diff checks, ensure no private material or safety-gate changes, then commit/push and verify remote HEAD.
