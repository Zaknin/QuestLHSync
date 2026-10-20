# P3-A7 — Frame Metadata Identity & Join Feasibility

**Дата:** 2026-10-20
**Baseline:** `d231cb4ca26606cf59f09d51e454438a072de237`
**Scope:** offline review of already acquired, SHA-pinned userspace binaries, the existing P2 K0 capture, and project-owned reader source. No ADB, Pico, camera, process inspection, root, logcat, or Lighthouse operation was performed.

## Решение

**NO-GO для следующего аппаратного metadata-join эксперимента при текущих ограничениях.** Существующий `PicoFrameReader --clock-scan` записывает K0 camera ID, ring `seq` и timestamp из одного K0 slot. Статическая цепочка показывает, что `FrameMetaDate+8` вероятно попадает в тот же slot offset, который reader называет `seq`; однако между этим store и последующим чтением вызывается `DataBuffer::unlockForWrite`, а matching `libpvrtrackingbuffer.so` отсутствует среди локальных артефактов. Поэтому равенство K0 `seq` и QuickCamera request ID не доказано. Кроме того, единственный сохранённый путь запуска reader использует `adb shell su -c`, так что доступ без root не подтверждён.

Точный результат для требуемого интерфейса: **`METADATA_JOIN_INTERFACE_UNAVAILABLE`** — нет проверенного rootless output, который однозначно выдаёт K0 frame identity, QuickCamera metadata request ID и timestamp как один join и позволяет определить источник timestamp при fallback. Исторические 1,204 K0 observations дают полезную per-record пару `camera/seq/timestamp`, но не доказывают namespace `seq` и не содержат отдельного timestamp-source ID или fallback marker.

## Изученные артефакты и provenance

Использованы существующие SHA-pinned файлы; ELF не извлекались с устройства повторно и не публикуются вместе с этим отчётом.

| Артефакт | SHA-256 | Использование |
|---|---|---|
| `libpvrtrackingcamera.so` | `cf9e507f412ec33d62c2f720669fcdd093f1822c9cbf3adefd0a26a6b4d072ee` | `DeQueueFrame`, `PvrCameraFrame::processCameraFrame`, `OnBufferReady`, PVR frame-item construction |
| `libpvrtrackingservice.so` | `45194b15539875ea1ce01fb702d34773b708d248a3409d369877ac199849b8de` | `CameraManager::onFrameAvailable`, `writeToSm`, K0 slot stores |
| `quickcamera.core.so` | `fb22355acd35b9772a5538a7d1c49175641165ad0368e7c47e5831f5f1727017` | CSL handler, 38-entry timestamp ring, fence callback and fallback |
| QuickCamera HIDL module | `c3157e66d842dcdca148f1b98328bd5e7ce80c4ab9bbbacba895465556314f47` | `sBufferReady` index-only callback and buffer descriptor path |
| Existing reader source `pico/src/PicoFrameReader.java` | `d65873c729b9d8cb8fb6c2f90745cfbba1724be278e7f13fec75b2722c9da2b2` | K0 shared-memory read fields and output framing |
| Existing K0 capture `pico/build/qtimer-p2-private-20261016-204644/k0.csv` | `be4ff0e03a500dfb5b7c5c487c3355893a84d1004393e112ee62a5c3be16a88a`; 163,434 bytes | Offline analysis only; file is ignored by Git under `build/` |

Additional code facts and evidence boundaries are preserved in [P2 K0 source/slot audit](P2-K0-SourceAndSlot130-20261016.md), [P2 clock-provenance closeout](P2-Closeout-P3-Clock-Provenance-20261017.md), [P3-A4 timestamp semantics](P3-A4-Timestamp-Semantics.md), [P3-A4 HIDL/PVR bridge](P3-A4-HIDL-PVR-Bridge-20261017.md), [P3-A4C dequeue copy](P3-A4C-PVR-DeQueue-Metadata-Copy-20261017.md), and the M2.7B–M2.9 reports. The installed provider remains pinned separately in M2.7B: `/vendor/lib64/camx_core.so`, SHA-256 `7502d93342e5efe4d96a53c08ca7dfc7778d0ca5c728a9a0905be2611c0f1a77`, Build ID `c83b58a36b8273c0a458bc26c28f5af4`.

## Source-to-sink identity trace

| Stage | Statically established field movement | Identity meaning and boundary |
|---|---|---|
| CRM payload → installed provider → `CSLMessage` | The acquired provider copies CRM request ID to `CSLMessage+0x08`, frame ID to `+0x10`, and timestamp bits to `+0x18`. The provider's event branches and dispatch are binary-static evidence from the acquired ELF. | These are CRM/CSL fields at this bridge. Public CamX source remaps CSL sync IDs to pipeline request IDs; equality with a pipeline, PVR, or K0 identifier is not implied. Runtime event/callback remains unobserved. |
| `CSLMessage` → QuickCamera handler and ring | QuickCamera handler reads request ID `+0x08` and timestamp `+0x18`; it indexes a 38-slot ring by request ID modulo 38 and stores the timestamp. Its INFO logger passes `+0x10` as `frameCount` and `+0x20` as `linkhdl`. | Static field flow identifies `frameCount` with the provider's CRM `frame_id` word for this path. The ring is keyed by request ID, not frame ID. No accepted runtime log row exists. |
| Ring → `CSLFenceCallback` → metadata | Direct path writes the timestamp from the current request's ring slot at metadata `+0x00`; metadata `+0x08` receives the current callback/request ID. After the 5 ms timed wait, the fallback can load `(current_request_id-1) mod 38` for metadata `+0x00`, while metadata `+0x08` still names the current request. | **Current metadata request ID** and **timestamp-producing request ID** can differ. The producer does not write a separate source request ID or fallback bit in the traced record. Static branch existence does not establish occurrence. |
| Metadata buffer → PVR `FrameMetaDate` | PVR `DeQueueFrame(void**,FrameMetaDate*)` copies raw metadata `+0x00`, `+0x08`, `+0x10`, `+0x14`, `+0x18` with no timestamp conversion in the traced successful path. | PVR field-copy behavior is binary-static verified. Exact producer/PVR backing-store identity and runtime values remain unverified. |
| `FrameMetaDate` → `PvrCameraFrame` item | `processCameraFrame` loads `FrameMetaDate+0x00/+0x08`; the first word is duplicated to frame item `+0x18/+0x20`, while the second is stored at frame item `+0x30`. It separately calls the PVR frame listener. | The static field layout makes frame-item `+0x30` a candidate carrier of the current metadata request ID. It does not contain the CRM `frame_id` based on the traced `FrameMetaDate` producer fields. |
| HIDL ready notification and PVR dequeue | HIDL `sBufferReady` supplies a 32-bit buffer index. PVR `OnBufferReady` does not carry `FrameMetaDate`; later `VideoQueueUtil::DeQueVbQueueBuffer` supplies a queue key used to find the corresponding mapped buffer record and metadata offset. | Buffer index/queue key is delivery plumbing, not proven equal to CRM request ID, CRM frame ID, K0 sequence, or camera ID. The kernel QBUF/DQBUF roundtrip contract remains partial. |
| PVR frame item → K0 ring | The service `writeToSm` stores frame-item `+0x18/+0x20/+0x28` at K0 slot `+114/+122/+130`. In the same function, `item+0x30` is loaded into `x14` and stored at `x22+0x31`. The known timestamp store offsets place `x22` at slot `+97`, so this store targets K0 slot `+146`. | The `+146` word is what the existing Java reader calls `seq`. This is a concrete **pre-unlock static candidate** that the current metadata request ID is written to the slot's sequence word. `DataBuffer::unlockForWrite` is then called; its implementation is in `libpvrtrackingbuffer.so`, which is not present in the local acquired artifacts. Whether unlock changes/overwrites that word, and thus whether the post-commit K0 `seq` equals the metadata request ID, is **UNKNOWN**. |
| K0 reader → per-record output | `PicoFrameReader --clock-scan` selects a stable K0 slot and writes `cam`, `seq` (slot `+146`), `vendor_ns` (slot `+122`), `image_ts114_ns` (slot `+114`), `ring_ts84_ns`, `ring_ts130_ns`, `mono_ns`, and `boot_ns` in the same CSV record. PFR1 mode carries camera ID, `seq`, slot `+122`, and one Android `System.nanoTime()` copy-time field alongside image bytes. | This establishes a K0-local record/clock observation pair in the existing reader. It does **not** independently decode `seq` as CRM/QuickCamera request ID, return CRM frame ID, expose the timestamp source request ID/fallback, or bracket callback delivery. |

The distinct identities therefore remain:

| Identity | Current conclusion |
|---|---|
| CRM event request ID | Copied to CSL `+0x08`; no runtime join to K0 |
| CRM frame ID / QuickCamera log `frameCount` | Static field flow through CSL `+0x10`; not shown in `FrameMetaDate` or in the K0 reader output |
| Current `FrameMetaDate` request ID | Written at metadata `+0x08`; copied to PVR item `+0x30`; candidate store to K0 `+146` before `unlockForWrite` |
| Timestamp-producing request ID | Current request in direct branch; previous modulo-38 slot after fallback. No separate emitted source ID |
| K0 `seq` | Same-slot sequence value returned by reader; post-unlock identity as QuickCamera request ID is unresolved |
| PVR/K0 camera ID | Reader returns requested K0 IDs `0,3,4,5`; physical sensor/orientation and request namespace are not thereby proven |
| Frame delivery identity | Queue buffer index/key selects mapped buffer; not exported with timestamp in K0 CSV and not proven equal to the IDs above |

## Existing read-only output and permissions

The existing project reader accesses the `pvrtracking` Binder service (`GetCameraShareMemory`, transaction 19), maps the returned K0 `SharedMemory` read-only, and samples the K0 ring. This is a project-owned reader, not a hook or `/proc` reader. However, the saved `capture_qtimer_bridge.ps1` launches `app_process` and queries PVR clock dumps through `adb shell su -c`; the historical capture therefore does **not** demonstrate a rootless ADB-shell permission path. No rootless invocation result or standard public Android API for the same K0 ring is available in the reviewed artifacts.

The static Camera2 helper only enumerates camera IDs and reads static characteristics; it does not open a camera or create a per-frame stream. The historical M2.8C/D callback-log paths did not yield a usable record and must not be repeated. Their static INFO format lacks K0 camera ID/sequence, explicit CRM event ID, a timestamp source request ID, and a fallback branch marker. No available non-root output currently provides all of these:

| Field | Existing evidence/output | Status for a permitted rootless join |
|---|---|---|
| Camera ID | K0 reader parameter/output `cam` | K0 layer only; no proven CRM/link-to-camera identity |
| Frame identity | K0 reader `seq` at slot `+146` | Available as an opaque same-slot sequence; request-ID interpretation blocked by missing post-unlock implementation |
| Raw timestamp | K0 slot `+122` (`vendor_ns`), with `+114` as duplicate candidate | Available in historical K0 CSV; clock epoch/event identity and live producer mapping remain unknown |
| Current metadata request ID | Candidate same K0 `+146` store; not a separately named field in CSV | Not independently decoded or verified after unlock |
| CRM frame ID | CSL `+0x10` / static log `frameCount` | No verified K0 or rootless per-frame output |
| Timestamp source request ID | Not retained separately by the fallback path | Unavailable |
| Fallback indicator | No producer metadata field or accepted runtime log row | Unavailable |
| Delivery bracket | Reader records observation clock point/midpoint; PFR1 has one copy-time sample | No before/after per-frame delivery bracket; observed read time is not callback or exposure time |

`METADATA_JOIN_INTERFACE_UNAVAILABLE` applies to the requested **rootless runtime join**, not to the existence of the K0-local sequence/timestamp CSV. A timestamp and K0 record key coexist in the old data, but request namespace, fallback source, and eligible rootless acquisition are not established.

## Offline analysis of the existing 1,204-frame capture

The verified input was the existing `k0.csv` above, not a new capture. It contains 1,204 metadata rows: 301 each for K0 IDs C0/C3/C4/C5. Existing analyzers were run against this exact SHA-256 input:

| Check | Observed result |
|---|---|
| Per-camera K0 sequence | First `528673`, last `529273`; all 300 adjacent deltas are `+2`; no duplicate, reorder, or missing `+2` sequence step in this 11.965 s window |
| Sequence groups across cameras | 301 shared sequence values; all four cameras have the same sequence at each group. This is a K0 grouping observation, not CRM request/frame ID proof |
| `slot+114` vs `slot+122` | Exact equality in all 1,204 rows (`image_ts114_equals_ts122_fraction=1.0`) |
| `slot+122` ordering | Strictly increasing per camera; median adjacent step `39.999896 ms` (about 25.07 samples/s). Existing analyzer reported no malformed/incomplete rows |
| Cross-camera `slot+122` spread for a shared sequence | Maximum `53 ns`; exactly equal across all four in 67.1% of the 301 groups |
| `slot+130` ordering and correction | All nonzero/strictly increasing; for every row, `slot+122 - slot+130 = 225,997 ns` exactly; one unique adjustment and zero adjacent adjustment changes |
| Reset/wrap evidence | No reversal, duplicate, or reset is visible during this short capture. This does not establish counter width, wrap policy, reboot behavior, or suspend behavior |
| Physical event or K0 sequence namespace | Not established by numerical ordering/equality |

Commands used (offline only):

```text
python -m pico.tools.analyze_vendor_clock pico/build/qtimer-p2-private-20261016-204644/k0.csv --json
python -m pico.tools.audit_k0_slot130 --before pico/build/qtimer-p2-private-20261016-204644/before.txt --csv pico/build/qtimer-p2-private-20261016-204644/k0.csv --after pico/build/qtimer-p2-private-20261016-204644/after.txt --summary
python -m pico.tools.audit_k0_slot130_variation --csv pico/build/qtimer-p2-private-20261016-204644/k0.csv
```

`slot+130` is a code-derived timestamp candidate. The observed fixed subtraction moves the stored value earlier by `0.225997 ms`; the native formula uses a frame code (`E=4` in these accepted rows), but neither the code nor the exact constant establishes exposure midpoint, exposure start, or a valid synchronization correction. The separate PVR QTIMER-like clock comparison is not used here to infer CRM event identity.

## GO / NO-GO and minimum missing evidence

**NO-GO for a new hardware metadata-join experiment under the present no-root constraint.** Do not repeat the existing 1,204-frame K0 scan: it already proves ordering and same-record co-observation of K0 `seq` and K0 timestamp, and another identical scan would not identify the sequence namespace or fallback source.

The smallest evidence that could change this decision is:

1. A matching, SHA-pinned `libpvrtrackingbuffer.so` implementation (or equivalent source) resolving what `DataBuffer::unlockForWrite` does to K0 slot `+146` after `writeToSm` stores frame-item `+0x30` there.
2. A demonstrated unprivileged reader path for the existing PVR Binder/K0 ring. The historical `su -c` workflow is not evidence that Android shell can read it.
3. Same-record output that explicitly distinguishes `k0_sequence` from `metadata_request_id` if they are different, and reports `camera_id`, slot `+122` raw value, plus before/after **reader observation** clocks. It must not label this bracket as callback delivery time.
4. To identify the timestamp source under the 38-slot fallback, an independently available source-request ID or explicit fallback marker tied to the same output record. The current K0 ring/reader does not expose one. CRM frame ID also needs a verified route into that record before it can be joined.

For physical timing, a separate optical reference observing the actual K0 image sequence and an independent timebase remains the useful alternative. It can test timestamp-to-optical-event behavior for the measured setup; it cannot retroactively prove CRM/CSL ID equality or fallback source, and by itself does not validate pose-clock mapping, camera geometry, drift, uncertainty, or Lighthouse correction. No such experiment is launched or proposed for immediate execution in this offline phase.

## Final status and gates

```text
metadata_join_interface=METADATA_JOIN_INTERFACE_UNAVAILABLE
next_metadata_join_experiment=NO_GO
exact_time=false
mapping_verified=false
pose_verified=false
shared_buffer_identity_verified=false
frame_meta_bridge_verified=false
physical_event_verified=false
live_lighthouse_correction_allowed=false
```

No new analyzer or collector was added. The private K0 file and proprietary ELF remain ignored/local; only bounded derived results are documented.
