# P3-B — Windows QPC + OpenVR host-only probe

**Date:** 2026-10-17; readiness rechecked 2026-10-20. **Status:** implemented, synthetic tests PASS; latest host check `HOST_RUNTIME_NOT_READY` (binding imports, SteamVR runtime processes absent; no HMD query or baseline run). **Mode:** OBSERVE ONLY.

## Scope / architecture

The independent host script is at pico/tools/openvr_qpc_probe.py. It uses the project's existing **unofficial** Python openvr binding with the **official** OpenVR IVRSystem::GetDeviceToAbsoluteTrackingPose API. Initialization uses VRApplication_Background, not Scene or Compositor; initialize SteamVR normally before running the probe. Origin defaults to TrackingUniverseStanding, optionally TrackingUniverseSeated; prediction_seconds is always 0.0.

For each call: Windows QueryPerformanceCounter **before** → getDeviceToAbsoluteTrackingPose(origin, 0.0, maxDevices) → QPC **after**. QueryPerformanceFrequency is read once and all raw tick values/frequency are preserved as integers. Returned device flags, tracking result, valid 3×4 transforms, linear/angular velocities and separate class/model/manufacturer/tracking-system identity are recorded. No serial-number property is requested. Device properties are read separately, **outside** the QPC bracket.

**Meaning:** OpenVR's prediction=0 reports the runtime's estimate of pose at call time, NOT a physical camera/IMU sensor timestamp. QPC before/after brackets the API call, not the pose's acquisition or processing instant. The bracket midpoint and API latency CANNOT be relabeled as a sensor exposure timestamp, Pico↔Windows time offset, or proof of tracking accuracy. This tool does not access Pico and cannot unblock clock/geometry correction gates.

References:
- https://github.com/ValveSoftware/openvr/wiki/IVRSystem%3A%3AGetDeviceToAbsoluteTrackingPose
- https://github.com/cmbruns/pyopenvr (unofficial Python binding; already used by pico/tools/steamvr_hmd_info.py)

## Test matrix / evidence classification

| Test | Expected | Evidence |
| --- | --- | --- |
| Mock pose | Correct integer QPC bounds, origin, zero prediction, matrix and velocities | SYNTHETIC PASS |
| Invalid/disconnected | Keep validity/connection/result; never expose unusable matrices | SYNTHETIC PASS |
| NaN/corruption | Reject affected sample; no false host PASS | SYNTHETIC PASS |
| Reversed QPC / cross-sample regression | Reject affected sample | SYNTHETIC PASS |
| OpenVR call exception | Keep call QPC bracket and record diagnostic | SYNTHETIC PASS |
| Init failure / cleanup | Fail closed; shutdown exactly once if initialized | SYNTHETIC PASS |
| SMB atomic publication | Read-back SHA-256 of .part and final file; manifest; .sha256 last, including BLOCKED | SYNTHETIC PASS |
| SMB corrupt read-back | Refuse final commit and .sha256 | SYNTHETIC PASS |
| Real SteamVR + Pimax | Host-device identity and QPC latency observed | `HOST_RUNTIME_NOT_READY` on 2026-10-20; no baseline run |
| Pico exposure/host clock mapping | Independent producer, synchronization, geometry evidence | BLOCKED |

Mock tests from the repo root (do not need Windows or SteamVR):

    python -m unittest pico.tests.test_openvr_qpc_probe -v

## Owner Pimax run (opt-in)

Install Python dependency once if missing:

    python -m pip install openvr

From C:\Dev\PicoLHSync after git pull, with Pimax Crystal and SteamVR active:

    python .\pico\tools\openvr_qpc_probe.py

Defaults: 10 seconds, 20 Hz, standing origin, prediction=0. Limits: --seconds from 1 to 60, --hz from 1 to 60, --origin standing or seated. If startup fails or HMD is unavailable, evidence status is BLOCKED; partial success is PARTIAL; successful valid connected HMD pose queries are PASS_HOST_QUERY (a HOST QUERY status, NOT a physical timing validation). Even failures with generated diagnostics are published.

Canonical **evidence** destination only: \\192.168.23.63\Torrents\Codex\PicoLHSync\P3-B. Each run publishes JSONL, manifest, and SHA-256 sidecar. Write .part → independent SHA-256 readback → atomic rename → manifest verification → .sha256 sidecar **last**. If SMB is inaccessible publication fails with **no alternate-root fallback**. An alternate root requires explicit --output-root. Google Drive /Codex is a downstream mirror.

The probe does not mutate Pico SLAM, firmware, services, calibration, QuestLHSync F timestamps, SteamVR driver or runtime poses. It does not use compositor focus-changing WaitGetPoses, inject a virtual HMD, or call any OpenVR write API. Safety flags remain: observe_only=true, exact_time=false, live_lighthouse_correction_allowed=false, mapping_verified=false, pose_verified=false.

The output contains private 6DoF room/tracking poses: do not commit the JSONL, manifest containing hardware references, raw binaries, factory calibration, or owner recordings into GitHub. The owner can share only the console status and SHA-256, then we can inspect the downstream Google Drive /Codex copy when synced.

## Host runtime readiness check — 2026-10-20

The installed Python `openvr` module imported successfully. A read-only process inventory found none of the standard SteamVR runtime processes (`vrserver`, `vrmonitor`, `vrcompositor`, `vrstartup`). Therefore no OpenVR initialization or HMD-connected query was attempted; the HMD state is **NOT OBSERVED**. The host is marked **`HOST_RUNTIME_NOT_READY`**. The probe was not launched, SteamVR was not started, and no P3-B JSONL/manifest/sidecar or runtime baseline was produced. The existing probe source is unchanged. Safety gates remain false.

## P3-A follow-up when Pico is available

Enumerate the actually installed QuickCamera/HIDL producer libraries for the exact same Pico OS 5.11.2 build in read-only mode. Confirm candidates via real dependency and filesystem inventory; copy matching binaries privately for offline static tracing of first FrameMetaDate metadata word. No guessed paths, vendor code changes, SLAM changes or premature AImageReader path claims. Do not reopen the 2376ns A/B coefficient subtask without new concrete evidence.
