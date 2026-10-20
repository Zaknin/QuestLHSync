# P3-D — HeadFromBody recovery and native replay decision

Date: 2026-10-20
Branch: `feature/pico-support`
Audited base: `f72434b4a71bac19088ea729539139cda85cfb78`
Outcome: **`HEAD_FROM_BODY_SOURCE_UNAVAILABLE`**; no new native replay run.

## Scope and safety

This was an offline audit of the existing P3-C station-record handling, local private calibration/fitting artifacts, installed PICO Connect files/configuration and the repository's bundled OpenVR driver header. No ADB, Pico, camera, SteamVR, Lighthouse, or installed executable was launched. Private recordings and calibration values remain outside Git; this report contains aggregate counts only.

## P3-C station record audit

The two stored `S` schemas encode different coordinate frames:

- Original source pose: `S serial channel x y z qw qx qy qz`. These are the raw source poses intended for `SetStationsRaw`.
- Recording-writer transformed pose: `S serial x y z qw qx qy qz channel`. These coordinates have already passed through the writer's transform and must not be fed back as raw source poses.

The four local recordings were classified without printing station IDs or coordinates:

| Recording | Raw channel-first | Transformed channel-last | Ambiguous | Other | Unique IDs in each schema | Cross-format IDs |
|---|---:|---:|---:|---:|---:|---:|
| `qlhs-20261015-191506.txt` | 308 | 28 | 0 | 0 | 4 / 4 | 4 |
| `qlhs-20261015-202205.txt` | 192 | 20 | 0 | 0 | 4 / 4 | 4 |
| `qlhs-20261015-202605.txt` | 1,652 | 164 | 0 | 0 | 4 / 4 | 4 |
| `qlhs-20261015-212939.txt` | 1,876 | 188 | 0 | 0 | 4 / 4 | 4 |

Every channel-last `x` token in these files had decimal formatting. In the previously used `sscanf("%63s %d ... %c")` parser, the decimal suffix made the final channel remain after the seven floating-point conversions; `%c` consumed it, so the conversion count exceeded the accepted count and the real channel-last rows were rejected. This is why the recorded P3-C replay metrics are retained as unaffected by these rows.

There was still a real parser edge case: with an integer-formatted channel-last `x`, `%d` can consume `x` as the channel, the following seven `%lf` conversions consume the remaining numeric fields including the channel, and `%c` sees end-of-record. The old code then sees the same conversion count as a valid raw record. The offline red regression reproduced extra station entries from this fixture before the correction. The real four logs did not contain this integer-formatted case.

`src/tools/replay.cpp` now tokenizes the exact nine-field record and checks both layouts independently. It accepts only a uniquely valid channel-first record into the `raw` map passed to `SetStationsRaw`; a uniquely channel-last record is counted and rejected, ambiguous records are counted separately and rejected, and malformed/unknown-channel records are counted without entering the solver. Aggregate output contains counts only, not serials. The non-Pico parser remains unchanged.

## HeadFromBody artifact recovery

The relevant local private-evidence and project build roots contained no fitting artifacts with `HeadFromBody`/body-to-head/correspondence names and no NumPy/pickle/notebook/matrix fitting files. The only P3-C candidate artifacts carrying a `HeadFromBody` field were `calibration-candidate.json` and `calibration-placement-guess.json`; both contain `HeadFromBody: null`, `pose_verified: false` and `mapping_verified: false`. The corresponding `make_placement_guess.py` helper exposes no fitting/solve operation, so its name and placement output are not a numeric fit.

The local `pico-calibration.tar` contains factory sensor YAML files, including camera calibration entries, but no head/body transform. The available factory extrinsic `T_BS` is `BodyFromCamera`; it cannot substitute for `HeadFromBody` and must not be inverted or relabeled to manufacture one. The required composition remains:

```text
HeadFromCamera = HeadFromBody × BodyFromCamera
```

Without an independently supported `HeadFromBody`, that product cannot be evaluated. No rigid-transform or reprojection round-trip was claimed.

Because there is no numeric fit artifact, the fit's input correspondences, frame axes, handedness, unit convention, objective, residuals, or any held-out set cannot be recovered. The intended transform name is `HeadFromBody` (body coordinates mapped into head coordinates); a valid matrix must be explicitly tied to both coordinate definitions and have metric translation before use. The installed OpenVR interface's pose translations are expressed in meters, but that API fact does not supply or authenticate a value for the factory `Body` frame.

## PICO Connect and OpenVR inspection

The installed PICO Connect product reports version `10.6.6.0`. Read-only inspection covered its OpenVR driver manifest, `openvr_driver/resources/settings/default.vrsettings`, HMD input profile and bundled OpenXR streaming profile. The default driver settings contain only a controller shake setting; the HMD input profile declares a `/pose/raw` pose action but carries no numeric body/head calibration.

Static byte-string checks of the installed `body_tracking.exe`, `driver_pico.dll`, `ps_steamvr_driver_sdk.dll`, `PICO Connect.exe` and `pico_connect_core.dll` found none of the searched human-readable `DriverPose_t` transform field names. The inspected vendor-shipped pose/settings files contain no numeric `HeadFromBody`/`BodyFromCamera` calibration field. This is limited negative string/configuration evidence: compiled code could contain numeric constants without those names, so it does not prove that the binaries have no internal offset. No binary was executed or disassembled to infer a hidden transform.

The repository's `third_party/openvr/headers/openvr_driver.h` declares `DriverPose_t` fields `qWorldFromDriverRotation`, `vecWorldFromDriverTranslation`, `qDriverFromHeadRotation` and `vecDriverFromHeadTranslation`. This is an API data contract, not a numerical pose value. The header describes the driver-local reference as potentially an internal IMU/reference point rather than the head itself. No runtime `DriverPose_t` value was read, and there is no evidence that PICO Connect's driver-local body frame is the same frame as the factory CamX `Body` used by `T_BS`. A future numeric OpenVR pose field alone would therefore still need a frame-definition bridge before it could be combined with factory extrinsics.

## Replay decision and next physical experiment

`--pico-offline --pico-head-from-body` was not run: there is no supported numeric transform to pass. The identity control remains diagnostic only. The focused 474-second replay and the 418-second holdout remain pending until an independently measured transform exists; the 418-second session must not be used to fit that transform.

Recommended next experiment: one rigid-body optical metrology calibration, under separate authorization, that directly measures the factory body frame against the OpenVR HMD head frame. Attach a metrology target whose pose is surveyed into the manufacturer/factory body coordinate frame (using identified camera optical frames or an authoritative body datum), collect simultaneous external target poses and OpenVR HMD poses over at least six diverse static orientations/translations, solve one rigid `HeadFromBody`, and validate closure on withheld poses. Preserve the factory camera identity/mapping as a separate input; do not infer it from station IDs. If the factory body datum cannot be physically tied to the target, the required prerequisite is manufacturer body-frame definition or an independent camera-frame survey. This geometric experiment can validate the pose transform; it does not prove timestamp provenance, physical exposure timing, or readiness for Lighthouse correction.

## Verification and gates

- `cmd /c build_replay.bat` — exit 0; `qlhs_replay.exe` and `qlhs_nettest.exe` built. The script emitted its existing `'Fastboot++\' is not recognized` warning before successful compilation.
- Focused regression `PicoNativeReplayTests.test_pico_station_parser_rejects_channel_last_and_ambiguous_records` — PASS. It runs the actual replay executable, exercises raw, channel-last, integer-`x` ambiguous, explicit ambiguous and malformed records, confirms only the raw station reaches status, verifies aggregate counters, and checks that synthetic IDs are absent from output.
- `python -m unittest pico.tests.test_p3c_native_replay -v` — **12 tests, PASS**.
- `python -m unittest discover -s pico/tests -p 'test_*.py'` — **298 tests, PASS**.
- `git diff --check` — PASS.
- No hardware experiment or new private evidence package was created.

All safety gates remain `false`: `exact_time`, `mapping_verified`, `pose_verified`, `shared_buffer_identity_verified`, `frame_meta_bridge_verified`, `physical_event_verified`, and `live_lighthouse_correction_allowed`.
