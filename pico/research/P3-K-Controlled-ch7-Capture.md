# P3-K — Controlled ch7 Camera-Specific Capture

**Status:** preparation complete; hardware experiment **NOT RUN**.
**Baseline:** `40c66b0518618616caab50be0ed00c2349cf1180`
**Scope:** one manually controlled channel-7 ON/OFF/ON recording, with C4/C5 ROI selection frozen from the initial ON phase.

## Operator command

Start one QuestLHSync **Record session** and confirm all Lighthouse stations are ON. Keep the headset worn, awake, tracked, and at one marked view. Then run:

```powershell
pwsh -NoProfile -File .\pico\tools\capture_ch7_controlled.ps1
```

The script chooses the newest `qlhs-*.txt` in `%LOCALAPPDATA%\QuestLHSync\recordings`, but only proceeds if the file is regular, inside that directory, recent, and growing during a two-second preflight. It polls for continued file growth during the timed holds and aborts if the recording stops. It never changes Lighthouse power. The operator changes **only ch7**; ch1, ch10, and ch13 stay ON.

The script writes a local CSV with `Seq,Action,Channel,QpcNs,Utc` and prints the TXT and CSV SHA-256 values after the operator stops the recording. It does not record station serials or room labels. Each QPC marker is taken after the operator confirms the physical action or restored view; it is not a laser transition measurement.

## Guided sequence

| Marker | Operator action and required interval |
|---|---|
| `BASELINE_READY` | Confirm all stations ON and settle at the marked view; hold ch7 ON for at least 20 s. |
| `OFF` | Operator powers ch7 OFF and confirms immediately. |
| `OFF_READY` | Restore the baseline view while ch7 stays OFF; hold for at least 20 s. |
| `ON` | Operator powers ch7 ON and confirms immediately. |
| `ON_READY` | Restore the same view. |
| `SPINUP_DONE` | Script waits 25 s after `ON_READY`, then marks the end of spin-up. |
| `PASS_DONE` | Hold restored ch7 ON for at least 20 s; this marker ends the measured interval. |

The script then asks the operator to confirm every station is ON and stop the recording. If the operator pauses for a long time, the file stops growing, or the active recording becomes stale, the script aborts and does not issue any power command.

## Offline analysis

After the recording is stopped and the file is stable, run the analyzer against the TXT, its matching marker CSV, and the private **candidate mapping** calibration draft:

```powershell
python .\pico\tools\analyze_ch7_controlled.py "<recording.txt>" "<markers.csv>" --calibration "<private-candidate-calibration.json>"
```

The output JSON is private and defaults beside the recording as `*.ch7-analysis.private.json`. It refuses to overwrite an existing output and checks that the recording and marker hashes do not change during analysis. It prints only filenames and SHA-256 hashes; it does not print station serials, room coordinates, or HMD pose traces. Keep the output and raw capture outside Git.

### Capture quality status

Stable analysis windows exclude 2 s at each boundary:

- Baseline ON: `[BASELINE_READY + 2 s, OFF − 2 s)`
- OFF: `[OFF_READY + 2 s, ON − 2 s)`
- Restored ON: `[SPINUP_DONE + 2 s, PASS_DONE − 2 s)`

`CAPTURE_QUALITY_PASS` requires the recorded minimum holds (20 s, 20 s, 25 s spin-up, 20 s), at least 15 s per trimmed window, at least 200 frames for each of C0/C3/C4/C5 and 100 `P 0` poses per phase, no malformed relevant records, and stationary pose coverage. Stationarity uses 10 Hz samples grouped into one-second bins; at least 8 bins and 75% of measured bins must have 80% of samples within 5 cm / 5° of that bin's robust pose center.

Pose overlap is computed from individual 5 Hz samples using one-to-one matches, not a whole-window median. Position/orientation pairs must meet 5 cm / 5° for the main coverage result; both directions must cover at least 70% for quality PASS. The preferred 2 cm / 3° coverage is reported separately and targets 50%. When overlap fails, capture quality is `CAPTURE_QUALITY_INSUFFICIENT`; ROI counts remain descriptive and are not classified as optical evidence.

Frames are counted from actual per-camera `U F` records. For ROI counts the report includes full-phase frame totals, frames with a nearby `P 0` pose, and denominators restricted to one-to-one matched-pose intervals. A frame must have a nearest `P 0` row within 20 ms to count as pose-eligible. The analyzer does not alter or infer timestamps.

### Frozen ROI rules and interpretation

For C4 and C5 independently, ROI centers are clustered **only** from the trimmed initial ON baseline, using blob peak ≥100, 12 px clustering radius, at least five baseline hit frames and at least 1% of baseline camera frames. Up to eight non-duplicate baseline ROIs are frozen per camera. Evaluation uses those centers and a 12 px radius in all phases; OFF-only detections cannot create an ROI. The JSON preserves each selected ROI's center, threshold, selection QPC/frame-sequence range, phase hits and eligible-frame counts.

- `ON_OFF_ON_CANDIDATE` requires adequate capture quality and matched frame denominators, repeated baseline and restored hits, and a low OFF hit rate. It means a power-correlated optical candidate, **not a verified channel-7 emitter**.
- `REJECT_OFF_PERSISTENT` identifies a baseline-selected ROI that remains present in matched OFF frames; it is rejected as a ch7-specific hypothesis and retained as a negative-control candidate.
- If no baseline ON ROI reaches the frozen minimum, the camera reports `NO_BASELINE_ROI_FROZEN`; no ROI is synthesized from OFF or restored data.
- If a baseline-selected OFF-persistent point is available, it is an empirical negative-control candidate. Its physical identity as a lamp or unrelated source is not asserted.

Power correlation and modeled FOV are separate results. The only geometry comparisons are:

| Hypothesis | C4 | C5 |
|---|---|---|
| Candidate | factory cam2 | factory cam3 |
| Placement guess | factory cam3 | factory cam2 |

Both use the existing private factory Omni/Radtan calibration and fixed diagnostic `HeadFromBody` rotation `-Y,+X,+Z` with zero translation. The analyzer uses the median channel-7 raw `S` position from baseline and evaluates station-center projection at matched recorded poses. It performs no calibration, station-position, timestamp, ROI, or association optimization. A projection is not a model of Lighthouse sweep-plane/emitter rays and cannot identify the signal source; no physical camera mapping or `HeadFromBody` gate is promoted.

## Validation and safety boundary

The synthetic suite covers an ON/OFF/ON candidate, OFF-persistent control, OFF-only point exclusion, no frozen baseline ROI, non-overlapping views, short phases, missing camera frames, malformed records/markers, hash reporting, private-field exclusion, and CLI no-overwrite behavior. The PowerShell test parses the script under PowerShell 7 and checks its marker-only contract; no capture was run.

`CAPTURE_QUALITY_PASS` means the recording is suitable for the predefined comparison only. Even a repeated C4/C5 ON/OFF/ON pattern would be an optical power-state association candidate, not proof of a physical station-center ray, exact exposure/SOF timing, verified camera-to-factory mapping, or safe Lighthouse synchronization.

All gates remain unchanged: `observe_only=true`; `mapping_verified=false`; `pose_verified=false`; `exact_time=false`; `shared_buffer_identity_verified=false`; `frame_meta_bridge_verified=false`; `physical_event_verified=false`; `live_lighthouse_correction_allowed=false`.
