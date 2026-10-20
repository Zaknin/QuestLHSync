# PicoLHSync — consolidated status and execution policy (2026-10-20)

**Branch:** `feature/pico-support`
**Baseline reviewed:** `6f43cf3a602c0ad8a62e314e784016d7b0cf8d31`
**Current decision:** the owner explicitly **removed the rootless-only requirement**. Root access is an allowed experimental tool on this owner-controlled Pico 4 Pro. Do not infer that an earlier rootless NO-GO is a project-wide NO-GO.

## 1. Active authorization and safety policy (supersedes older no-root recommendations)

- Root and `su -c` are permitted for necessary on-headset research, normal project camera reader execution, existing service/Binder access, inspection of libraries, logs, memory maps, and bounded diagnostics. No requirement to prove an equivalent unprivileged interface first. No per-command approval JSON or interactive yes cycle for ordinary authorized work.
- Keep operations proportionate, document commands and outputs, and prefer reversible experiments. Root itself is not an error or a blocker.
- Continue to protect the device from unintended firmware, SLAM, sensor configuration, factory-calibration, or tracking-service changes; back up and plan any necessary state-changing experiment before applying it. Root permission does not establish measurement correctness.
- Pico live lighthouse pose correction must remain disabled until independent geometry, timing, and safety validation. `OBSERVE ONLY`; `exact_time=false`, `mapping_verified=false`, `pose_verified=false`, `shared_buffer_identity_verified=false`, `frame_meta_bridge_verified=false`, `physical_event_verified=false`, `live_lighthouse_correction_allowed=false`.
- Historical `PROC_ACCESS_DENIED`, `METADATA_JOIN_INTERFACE_UNAVAILABLE`, and `NO-GO rootless` reports remain truthful for the original restricted procedures, **but no longer prohibit rooted follow-up**. Do not rewrite archival observations.
- Do not repeat identical captures or previously unproductive M2.8B/C/D probes without a new, decision-relevant question.

## 2. Working end-to-end subsystem (real hardware)

- Owner-controlled rooted **Pico 4 Pro**, Android 10 / Pico OS 5.11.2, fingerprint `Pico/Phoenix_ovs/PICOA8110:10/5.11.2/smartcm.1725996131:user/dev-keys`.
- Four active K0 cameras **C0/C3/C4/C5**, 640×480 RAW8 at approximately 25 Hz each, read from existing `pvr.ITrackingService` Binder transaction 19 into read-only SharedMemory. P1 reader / native QuestLHSync bright-spot detector / original `F` and `T` transport were tested over Pico Wi-Fi.
- PICO Connect headset identification in Windows OpenVR is validated; preliminary observing-only PC driver path and session recorder exist. No live lighthouse correction is enabled.
- Private manufacturer Omni/Radtan intrinsic/extrinsic assets were examined; optics adapter and draft camera order **C0→cam0, C3→cam1, C4→cam2, C5→cam3** exist but mapping / `HeadFromBody` are not independently accepted.
- Optical recordings demonstrate station-correlated spots. Controlled OFF/ON experiments identify stationary candidates associated with lighthouse channels **1, 7, 10, 13**. In a focused ~474s session there were **47,404 camera frames, 86,520 candidate blobs, 32,859 HMD pose records**, and 20 operator QPC markers. These spots are not guaranteed physical station emitter centers.

## 3. Major unresolved *practical* challenge — geometry and validation

- Existing station-center-constrained fits using three sessions (~969s total) gave a provisional camera PC-receive-to-pose shift of around **−94..−102 ms** (approximately −96 ms). This is an effective fitted alignment under uncertain source IDs, motion, timestamp, and clock drift — not exposure time.
- Q telemetry previously suggested roughly **3–5ms** median copy→PC-receive transport and **~25.8–27.7ppm** Pico↔PC rate drift on long recordings. These do not explain all of the −96ms offset alone.
- In a held-out 10-second-block split, joint fit with provisional −96ms achieved median reprojection **1.24px**, p90 **3.18px**; without the shift the cited baseline was median 2.05px, p90 6.99px. This is conditional on preliminary correspondences, not an unbiased real-world pose accuracy score.
- Crucial counterexample: leave-one-base-out medians were **9.27px (ch1), 44.67px (ch7), 8.07px (ch10), 36.0px (ch13)**. A separate station-center point-geometry check gave ~**0.19m 3D RMS** residual. This is the strongest reason to keep correction disabled. Reflections, wrong emitter-center assumption, association, body/head geometry, pose times, and rolling-shutter/exposure can confound one another.
- **P3-E update:** the original native solver accepted a fixed discrete candidate `HeadFromBody` rotation (`BodyToHead_-Y+X+Z`, diagnostic translation zero) on the 78 s selection recording, the 474 s focused recording, and the 418 s held-out recording. Identity control had no accepted alignment or lock; the candidate also retained accepted alignments for `all` and `upper` camera sets. This is repeatable offline geometry evidence, not a measured 6DoF transform: factory Body axes/translation, camera mapping, time model, and physical pose validity remain unverified. See [P3-E Geometry Bootstrap](P3-E-Geometry-Bootstrap.md).
- **Next required geometry experiment:** independently determine and validate the full 6DoF factory-Body-to-OpenVR-Head transform over varied poses with withheld validation. The zero-translation candidate cannot be installed as calibration. Use a vendor pose source only if its contract explicitly identifies factory `Body`; otherwise the frame tie requires a surveyed datum. No calibration or live change is authorized by the offline replay result.

## 4. Camera clock and metadata: what is proven, what is not

- Real 1204-row K0 timing capture: **301 observations per camera**; same grouping across four cameras, `seq` advances +2, `slot+114 == slot+122` throughout, `slot+122 − slot+130 = 225997ns` throughout, cadence ~40ms. Captured sequence has no drop in this window; this alone is not request namespace or optical-event proof.
- `slot+84` is **BOOTTIME at DataBuffer::lockForWrite**, not exposure. Normal reader intentionally chooses completed penultimate slot; same-frame lock→Java-copy observations median ~43.9ms, including roughly one 40ms frame period. Do not relabel this duration as sensor latency.
- Original installed `camx_core.so` acquired and SHA-pinned (`7502d93342e5efe4d96a53c08ca7dfc7778d0ca5c728a9a0905be2611c0f1a77`). Static CRM DQEVENT→CSLMessage field copies and callback dispatch identified. `quickcamera.core.so` registers callback and uses a request-indexed 38-slot timestamp ring. Its timeout fallback may use prior request's timestamp while current request ID stays in output.
- Original installed `libpvrtrackingbuffer.so` acquired and SHA-pinned (`ded0387ce77e4d358bc99c267f27ca49a0e40fc9651689d67a0cd56ba1386748`). `DataBuffer::unlockForWrite()` publishes **header ring index +0x0c** and does not overwrite **K0 slot+146** on traced successful path. Thus **`FrameMetaDate+8 → frame item+0x30 → slot+146 (`seq`)` is BINARY_STATIC_VERIFIED after publication**, not independently runtime-joined to callback logs.
- The publicly pinned ByteDance Phoenix online CSID path scales hardware QTIMER ticks as `ticks*10000/192` to nanoseconds; online/offline/BOOT_TS/frame-header alternatives exist. **EXACT_KERNEL_MAPPING_UNAVAILABLE**, so do not apply source-family clock semantics to running target blindly.
- Unknown: runtime selection of CRM event ID and timestamp producer, exact physical exposure event, fallback occurrence/source request ID, full cross-layer CRM frame-ID join, and a verified camera-clock↔SteamVR-pose-time transform. Root can be used to obtain useful new evidence, but no number of additional static source reports alone validates exposure or optics.

## 5. Host part

- `pico/tools/openvr_qpc_probe.py` already records Windows QPC bracketing around read-only `GetDeviceToAbsoluteTrackingPose(..., 0.0, ...)` queries. Synthetic tests pass. On 2026-10-20 the Python binding imported but SteamVR runtime was not running; real host baseline **HOST_RUNTIME_NOT_READY**, not failed software. Run during a regular VR session rather than creating more tooling.
- `prediction=0` does not provide physical sensor sampling time, and QPC brackets API call timing, not camera exposure time.

## 6. Near-term strategy / decision gate

**Recommended priority: deliver a useful observe-only, end-to-end geometry/timing validation on EXISTING data before more generic reverse engineering.**

1. Reproduce the best existing station-center solver and examine leave-one-station-out failure on private full captures with grouped, time-separated folds and station OFF negative controls; determine whether associations are real emitter centers or IR reflections.
2. Fit bounded relative pose time shift/drift jointly only as nuisance calibration parameters, compare against zero-shift and blinded held-out sessions. Do not hardcode −96ms or `slot+130` as a physical timestamp.
3. If existing data cannot discriminate reflected landmarks from station centers, design **one targeted** new rooted observation or optical setup that answers exactly that, not another generic K0 sweep.
4. During a natural SteamVR session, capture one existing host QPC baseline. Only after a validated offline model is available, consider controlled shadow replay then separately gated live correction.

**Go for further experiments:** a specific new observable or discriminating test is identified; bounded capture uses root as needed. **No-go for live correction:** bad held-out metric geometry/pose consistency or uncertain station association. Keep historical NO-GO decisions in their historical scope.

## Canonical reading order

- `pico/README.md` — P1 real capture, P2 geometry, PICO Connect sessions and timings.
- `pico/research/P3-A7-Frame-Metadata-Identity-and-Join.md` — library-acquisition and static K0 request sequence.
- `pico/research/P3-A6-M2.9-Exact-Kernel-Timestamp-Provenance.md` — source applicability limitations.
- `pico/research/P3-B-OpenVR-QPC-Host-Probe-20261017.md` — ready host-only read-only probe.
- `pico/research/P3-A4-Proof-Matrix.md`, `pico/research/P3-A6-Acceptance-Matrix.md` — claims, evidence and unchanged gates.

**Note:** This document changes *forward-looking permissions and prioritization*, not the truth of any historical read-only experiment or static proof.
