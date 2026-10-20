# P3-A6-M2 — Read-Only Camera Node Inventory Handover

> **ACTIVE OWNER POLICY — 2026-10-20:** Root/`su -c` is permitted for future PicoLHSync experiments on the owner-controlled Pico. The rootless-only condition has been withdrawn. The older `NO-GO for rootless metadata join` below documents the restricted experiment only and **is no longer a project-wide blocker**. Use the [consolidated project status and execution policy](P3-20261020-Consolidated-Status-and-Execution-Policy.md) for next-phase priorities. Historical data/results unchanged; live correction gates remain false.


## Current frame metadata join decision — P3-A7 (2026-10-20)

**NO-GO for another rootless hardware metadata-join run.** The existing 1,204-row capture already supplies K0 camera ID, slot `+146` `seq`, slot `+122` timestamp, and reader-clock fields. A new identical scan would not add an independent callback record, source-request ID, or fallback marker.

The missing provider was found at `/system/lib64/libpvrtrackingbuffer.so` on the exact owner-bound fingerprint/ABI, pulled without root, verified by matching remote-before/local/remote-after SHA-256, and published privately with Build ID `6897f1d0f297abb9a2fc9b70e290397a`. Static analysis closes the post-unlock edge: the pinned PVR service stores `FrameMetaDate+8` (through item `+0x30`) at K0 slot `+146`; `unlockForWrite` publishes the separate ring index at shared-header `+0x0c` and leaves slot `+146` unchanged. Thus `K0 seq == current metadata request ID` is **BINARY_STATIC_VERIFIED for the traced successful path**, not runtime-observed for any individual frame. The DataBuffer ring index is not this per-slot field. CRM frame ID remains distinct.

The existing reader still has no demonstrated rootless invocation; its saved launcher uses `adb shell su -c`. It does not emit CRM frame ID, timestamp-producing request ID, fallback marker, or a callback-delivery bracket. Because the 38-slot fallback may source timestamp bits from the previous request while slot `+146` labels the current request, the reader cannot attribute the timestamp to its producing request. Status remains **`METADATA_JOIN_INTERFACE_UNAVAILABLE`** for the rootless runtime join.

Do not repeat the identical K0 capture or M2.8B/C/D probes. Reopen the runtime path only if an unprivileged reader is demonstrated and returns same-record camera ID, `seq`, raw `+122` value and before/after reader-observation clocks. A separate source-request ID/fallback marker and CRM frame-ID route would still be needed for those joins. An independently time-referenced optical reference is a separate future method for physical-event semantics, not an immediate next run.

Offline analysis of the existing capture found 301 rows each for C0/C3/C4/C5; every adjacent per-camera `seq` delta is +2, with no duplicate/reorder/gap in the observed sequence; +114 equals +122 in all 1,204 rows; +122 is strictly increasing with median step 39.999896 ms; same-sequence cross-camera spread is at most 53 ns; and +122−+130 is exactly 225,997 ns for every row. These are capture-local numeric patterns only: they do not establish CRM identity, timestamp source, SOF, exposure, or a valid correction. Full source hashes and analyzer commands are in [`P3-A7-Frame-Metadata-Identity-and-Join.md`](P3-A7-Frame-Metadata-Identity-and-Join.md).

Safety gates remain false: `exact_time=false`, `mapping_verified=false`, `pose_verified=false`, `shared_buffer_identity_verified=false`, `frame_meta_bridge_verified=false`, `physical_event_verified=false`, `live_lighthouse_correction_allowed=false`.

## Current exact timestamp provenance status — M2.9 (2026-10-20)

Offline source-to-sink audit is complete for the available evidence. The pinned Phoenix commit `ceafd3afc0208c03e0eb7a1a60939d147f92d72a` proves its own CSID SOF → QTIMER conversion → optional BOOTTIME/frame-header → IFE/ISP → CRM event path. The installed Pico provider ELF statically copies the CRM timestamp field to `CSLMessage+0x18`; QuickCamera reads it and uses a 38-slot request ring. These source/binary facts do not identify the exact running kernel build, runtime event ID/source, runtime callback, units/epoch at the target, or a physical exposure event.

The public PICO-documentation tree at commit `99face1b92ccf8350e30268089e2da5b2682010e` contains only `kernel/README.md` for its kernel material. The README's reconstructed-kernel log reports `4.19.81-perf+`, AArch64 and a `smartcm`/Clang 8 banner, but the zImage/vmlinux bytes, hash, target fingerprint, generated config, DTB and build mapping are absent. Local project artifacts likewise contain no matching kernel image/config/DTB/Build ID. Exact mapping status is **`EXACT_KERNEL_MAPPING_UNAVAILABLE`**; the source-family relation remains **COMPATIBLE_BUT_UNVERIFIED**. Do not continue searching similar Qualcomm trees unless a concrete target kernel/firmware artifact appears.

For the pinned Phoenix online path, the closest defensible value description is QTIMER ticks from CSID current-SOF registers, scaled as `ticks*10000/192` into integer nanoseconds, with a lazily sampled BOOTTIME offset. Offline contexts use BOOTTIME directly; optional frame-header timestamps are another path. The provider's event 0/2 marker pairs structurally align with public CamX Qtimer/Mono semantics, but the exact target kernel mapping and runtime branch are unknown. The label `CSLTimestampTypeQtimer` is not a unit/epoch contract; QuickCamera's `monoTimestamp` diagnostic argument is the ring value again, not an Android clock sample. The 5 ms fallback can write a prior ring slot while metadata names the current request.

**Recommendation: NO-GO for Lighthouse correction or using this timestamp as exact physical time.** Stop the broad kernel-source search. The next technically meaningful route is a focused future B+C design: first identify a normal, non-protected PVR metadata surface that provides raw timestamp plus request/frame/fallback-source correlation; then compare that same stream with an independently time-referenced optical event and paired monotonic/host-clock brackets. No such experiment was run or authorized here. An optical result would still need a separate pose-clock, geometry, drift and uncertainty validation before synchronization use.

The detailed report is [`P3-A6-M2.9-Exact-Kernel-Timestamp-Provenance.md`](P3-A6-M2.9-Exact-Kernel-Timestamp-Provenance.md). Proof and acceptance rows were updated without changing historical M2.8 outcomes. All gates remain false: `exact_time=false`, `mapping_verified=false`, `pose_verified=false`, `shared_buffer_identity_verified=false`, `frame_meta_bridge_verified=false`, `physical_event_verified=false`, `live_lighthouse_correction_allowed=false`.

## Historical callback/timestamp status — M2.8D (2026-10-20)

One owner-authorized M2.8D attempt verified the target fingerprint and ABI, then stopped at the fixed shell-v2 output marker before running logcat capability or snapshot. The runner archived the status as `ADB_TRANSPORT_BLOCKED`, but its control flow shows it received expected exit 23 and zero stderr before the marker failed. Offline code now classifies this as `OUTPUT_FRAMING_BLOCKED / SHELL_V2_MARKER_MISMATCH`; the exact output difference is unknown because stdout was intentionally not retained. CRLF was a hypothesis, not a confirmed hardware root cause. The manifest-only canonical package and sidecar independently verified and remain unchanged. The initial `PUBLICATION_BLOCKED` console message was caused by receipt construction accessing a missing provider-only `files` key after the sidecar had committed; this was reproduced and fixed with a sidecar-last regression, without changing or republishing the package. No callback record was collected, so callback occurrence is **NOT OBSERVED / NOT EVALUABLE**, not absent. No retry was made.

The fixed M2.8D probe remains the only reviewed design in this phase: pinned SDK ADB, digest-bound target, exact build identity/ABI, fixed stdin script under `shell -T`, at most 15 seconds, 40 records, 16 process candidates, six commands and 64 KiB output. Synthetic WSL shell/awk tests do not establish Android Toybox or target-side shell compatibility. Do not continue a logcat retry series; the next useful work is offline exact-kernel timestamp provenance and build/config applicability. A new hardware run would require explicit task authorization and reviewed hashes. The report is [`P3-A6-M2.8D-Callback-Log-Verification.md`](P3-A6-M2.8D-Callback-Log-Verification.md).

## Historical callback/timestamp status — M2.8C

M2.8C found a callback-specific INFO diagnostic in the pinned `quickcamera.core.so`, but its one default-level logcat snapshot was rejected by the host framing guard (`OUTPUT_FRAMING`, 3,540 bytes, zero accepted rows). The exact original framing subcondition and filter support were not retained; this is **not** evidence that the log or callback was absent. Raw output was not saved. The M2.8C-R offline reconstruction and framing tests are complete and documented in [P3-A6-M2.8C-Callback-and-Timestamp-Provenance.md](P3-A6-M2.8C-Callback-and-Timestamp-Provenance.md); they do not recover the original bytes or prove Android shell compatibility.

The static format includes a Qtimer label, request ID, frame count, timestamp and `monoTimestamp`; it has no CRM event ID or `bNotify`. The `frameCount` argument is the 64-bit word at `CSLMessage+0x10`; `+0x20` supplies `linkhdl`. The straight-line `monoTimestamp` argument reloads the same request-ID ring slot written from the message timestamp. Units, epoch, exact kernel event identity, runtime event occurrence, frame-ID namespaces, fallback occurrence, physical SOF/exposure and Lighthouse suitability remain unproven. No `/proc` method was retried.

## Historical SOF provenance status — M2.8B

M2.7B verified the installed /vendor/lib64/camx_core.so path, SHA-256 and Build ID for the owner-bound firmware. Static ELF inspection now confirms that quickcamera.core.so declares DT_NEEDED camx_core.so and imports the matching unversioned CSLRegisterMessageHandler export. The acquired provider statically subscribes/dequeues CRM events, builds CSLMessage fields and dispatches the registered callback; QuickCamera statically registers and reads compatible fields.

This closes the installed-provider acquisition/static bridge gap but does not establish runtime mapping or callback identity. One M2.8B bounded read-only attempt verified the owner-bound fingerprint and ABI, then stopped when `/proc/<pid>/maps` for the first matching candidate `pvrtrackingservice` returned `PROC_ACCESS_DENIED`. No mapping rows were obtained; other matching processes were not tested. Installed-file stat metadata was observed in the same probe window, but there was no process mapping to compare. Runtime-loaded provider identity therefore remains UNKNOWN, not absent. The canonical evidence is independently verified and documented in [P3-A6-M2.8B-Runtime-Provider-Mapping-Verification.md](P3-A6-M2.8B-Runtime-Provider-Mapping-Verification.md).

The next useful step is offline review for an existing unprivileged system diagnostic that returns exact process-attributed mapped path plus device/inode without changing behavior. A name-only memory summary cannot satisfy the M2.8B PASS criterion. No repeat maps query, privilege escalation, SELinux change, camera start, logging change or runtime instrumentation is recommended under this result. Even a future mapping PASS would prove only a file mapping during its sample window, not callback/event occurrence, request/frame identity, clock domain, physical SOF/exposure or Lighthouse suitability.

Дата: 2026-10-19. Initial M2 implementation/verification was offline only at baseline `1bbb542ff90a1ac60876bc1991aff68270864a2e`; the owner-reported later M2.2 device result is recorded below. The M2.3 code changes and source audit used baseline `33e28e4cdca2089925e28ad8b14fe7d41d9c08e7` and were offline only. No ADB, Pico, camera service, `/proc`, root, tracing, SteamVR, Lighthouse or approval record was used for M2.3.

## Итог

Подготовлен самостоятельный runner [`collect_p3a6_camera_node_inventory.ps1`](../tools/collect_p3a6_camera_node_inventory.ps1) и модуль [`P3A6CameraNodes.psm1`](../tools/P3A6CameraNodes.psm1). M2 использует отдельное approval action `read-only-camera-node-metadata`; M1 action и runner не расширялись. Перед каждой командой collector перепроверяет общий Python gate, а pinned native ADB executor выполняет свою повторную gate-проверку и exact native allowlist.

Runner принимает только интерактивное точное lowercase `yes`. Только после этого создаётся внутренний token `P3-A6 APPROVE <approval_id> read-only-camera-node-metadata`. Это accident-prevention UX, не authentication. Срок/устройство/action проверяются общим gate непосредственно перед каждым разрешённым ADB invocation. Эффективный hard cap — 30 seconds, 40 node observations, максимум 16 candidates на источник.

Allowlist содержит только `get-state`, шесть фиксированных `getprop` keys, `uname -r` и точные `shell sh -c` bytes двух встроенных POSIX probe templates. Допускается default ADB transport или явный `-t <nonzero numeric id>`. Pinned executable: `$env:LOCALAPPDATA\Android\Sdk\platform-tools\adb.exe`; collector не перечисляет остальные ADB установки.

Sysfs probe читает только `/sys/class/video4linux/videoN/name`, `index`, `dev`, включая допустимые sysfs class symlinks. `/dev/videoN` проверяется на fully numeric suffix, symlink и character-node type; только metadata command `ls -ldn` анализируется, без открытия node. Недоступные, пустые, malformed или over-limit источники получают явный status; пустой inventory возвращает `PARTIAL_LIMITATIONS`, не success.

Статусы источника: `OBSERVED`, `NOT_OBSERVED`, `UNAVAILABLE`, `PERMISSION_DENIED`, `LIMIT_REACHED`. Sysfs field statuses: `OBSERVED`, `ATTRIBUTE_MISSING`, `PERMISSION_DENIED`, `INVALID`; `/dev` node-level outcomes остаются bounded. Отдельный пропуск, отказ или некорректное значение sysfs attribute не удаляет другие observations; `metadata_fields_complete` означает только, что все три разрешённых поля `name/index/dev` наблюдены, и не утверждает hardware identity. Итог `COMPLETE` выставляется только если оба источника `OBSERVED` и все найденные metadata fields/node metadata наблюдены; пустой, недоступный, ограниченный или частичный источник оставляет сохранённые значения, но даёт `PARTIAL_LIMITATIONS`. Parser отклоняет malformed/multiline records, неверные numeric values, лишние поля, duplicate node/attributes и записи после source terminator.

Evidence package содержит разрешённые raw technical values, UTC observations, owner-bound Android identity tuple, build/kernel identity, per-source status/method/build identity, эффективные limits/counts, collector/runner/probe SHA-256, ZIP archive SHA-256 и final marker. Windows run directory получает ACL только владельцу и LocalSystem. Серийные номера, accounts, wireless IDs, images/video, frame data, `/proc` и raw system logs не собираются. Неизменяемые safety gates остаются `false`.

Android tuple `A8110/PICOA8110/Phoenix_ovs/Pico` записывается как Phoenix-family software identity check, не cryptographic attestation. Факт Pico 4 Pro / international Pico OS остаётся owner-confirmed project context и не выводится из tuple.

## Синтетическая проверка

PowerShell harness запускает неизменённые production probe templates в локальном WSL `/bin/sh` против временных synthetic roots. Исполняются пустые/недоступные корни, symlink-backed sysfs nodes, несколько entries, отдельные отсутствующие/нечитаемые/multiline/control-character attributes, malformed name, лимиты 16 и overflow, `/dev` symlink/regular-file rejection, ls failure/incompatible/multiline records, POSIX quoting, literal tab-byte output и round-trip в настоящий PowerShell parser.

Для разбора `ls` добавлен локальный test-only fake command и test-only variant shell script, bypassing только `-c` fixture check. Его изменённые bytes явно отклоняются production native allowlist. Это проверяет framing/parser на Toybox-shaped output, но **не проверяет установленный Toybox Pico OS**. В реальной команде остаётся строгая проверка `-L`, `-c`, `ls -ldn` и fail-closed parsing без fallback.

Mock ADB responder сравнивает каждый элемент точного string-array vector и сначала пропускает его через production native allowlist. Проверены default transport и `-t 42`, шесть exact properties, build/release/kernel, оба shell probes, identity mismatch stop, budget/timeout failure, private archive/hash, а также missing/expired/wrong-scope approvals и все отказные confirmation paths. Все synthetic approval objects создаются только в памяти теста; approval file не пишется.

## M2.1 — исправление node-budget allocation

В baseline `7e7b8cd5c628540584dd732e691b27f91885221e` static audit обнаружил, что probe budget делился пополам между источниками: после 16 sysfs nodes при общем лимите 40 `/dev` probe получал искусственный предел 12. Расчёт исправлен на `min(16, remainingBudget)`. Каждый источник теперь может использовать до 16 записей, а общий approval budget продолжает ограничивать суммарные observations.

Добавлена regression, исполняющая collector с точными vectors через production native allowlist и strict mock output: 16 валидных sysfs nodes плюс 16 валидных `/dev` nodes дают `COMPLETE`, 32 observations и `OBSERVED` для обоих источников; искусственного `LIMIT_REACHED` нет. Успешная regression ранее падала (`PARTIAL_ADB_ERROR`) из-за vector с лимитом 12. Существующие проверки реального overflow выше 16 nodes, исчерпанного общего observation budget, пустых источников, malformed protocol и partial per-source status сохранены.

M2.1 offline verification: PowerShell M2 harness **353 assertions PASS**; `python -m unittest discover -s pico/tests -v` — **201/201 PASS**; прямой M1 PowerShell harness — **29/29 PASS**; WSL POSIX integration — **PASS**; `git diff --check` — **PASS**. Все проверки synthetic/local; ADB client/server, approval file, Pico и camera services не использовались.

Synthetic evidence не является результатом на Pico. В полном Python suite M2 runner действительно запускается с mock output; отдельный dry-run test проверяет отсутствие ADB-вызовов.

SHA-256 модуля для M2.1 revision: `d5a31a97933185a92ac66277a1a9d941358491858a15eccabbf1d16e9bc45dda`; runner `63ed273c01de3bbb098773546b2cadbd803e6d5a7d8d31c4c0e4297b20358066`. Точные probe hashes приведены ниже; production probe templates не менялись.

## M2.2 — Android ADB output compatibility и parser diagnostics

M2.2 исходил из commit `db3f95bc5fb1335c200deb37d28a209f5b246be1` в branch `feature/pico-support`.

Локально проверена указанная private evidence directory. В `evidence.json` указаны `PARTIAL_UNEXPECTED_OUTPUT`, 9 ADB commands и 0 observations; source statuses остались `NOT_OBSERVED`. Evidence не содержит raw stdout или parser error code, поэтому по ней нельзя подтвердить, что аппаратный stdout имел CRLF, либо установить другую точную parser rejection. Private evidence не копировалась и не публиковалась.

Статически подтверждено, что прежний parser безусловно отвергал любой `CR` до разбора строк. Это могло отклонить корректный CRLF output, но в данном hardware incident остаётся гипотезой. Другой определённый источник отказа на девятой команде при доступной evidence/source review не установлен. Новая версия классифицирует line endings, валидирует CR только как часть CRLF, после этого нормализует ровно `CRLF` delimiters в `LF`. Standalone CR и embedded non-protocol controls отвергаются; протокол fields, characters, lengths, node limits и terminator requirements остаются строгими.

Collector revision повышен до `P3-A6-M2-v2`. Private evidence хранит только `failed_source`, `normalized_line_ending_classification`, число полностью принятых protocol records до ошибки и фиксированный parser error code. Raw stdout, malformed line contents, unrelated paths и private identifiers не записываются. Успешные источники также сохраняют только классификацию delimiters и parsed-record count. ADB allowlist, sysfs/`/dev` probe bytes, 30-second/40-observation caps, 16-node-per-source bound, confirmation flow и safety flags не изменялись.

Тесты включают LF, CRLF Android-shaped probe output, mixed valid delimiters, standalone CR, embedded controls, missing terminator, unexpected records, strict schema, интеграционное сохранение `UNEXPECTED_RECORD`/`OUTPUT_FRAMING` и отсутствие malformed stdout в evidence. Эти fixtures являются offline synthetic data и не устанавливают фактический формат ADB stdout на Pico.

M2.2 parser-correction offline verification: PowerShell M2 harness **397 assertions PASS**; `python -m unittest discover -s pico/tests -v` — **201/201 PASS**; прямой M1 PowerShell harness — **29/29 PASS**; WSL POSIX integration — **PASS**; `git diff --check` — **PASS**. ADB/device operations were not part of that correction task; the separate owner-reported M2.2 Pico inventory result is recorded below.

SHA-256 текущего M2.2 collector module: `ad188e7f2eb50a7c78ca5fd4cf3ea45357a7e6c60903e478ee3f3154417422b8`; runner SHA остаётся `63ed273c01de3bbb098773546b2cadbd803e6d5a7d8d31c4c0e4297b20358066`. All four fixed probe hashes match the previous revision, confirming that the production POSIX templates are unchanged.

## M2.2 hardware observation and M2.3 correction

The owner-reported M2.2 hardware run completed both sources on the Pico 4 Pro: six sysfs entries, six `/dev` character-node entries, CRLF from each probe, 12 observations and 10 ADB commands. Result remains **`PARTIAL_LIMITATIONS`** because two sysfs `name` values were unavailable. The observed sysfs labels/dev values were `cam-req-mgr 81:0`, `hub_cam-req-mgr 81:1`, `cam_sync 81:2`, `hub_cam_sync 81:3`, an unavailable name at `81:32` with `index=0`, and an unavailable name at `81:33` with `index=1`. `/dev` reported mode `crw-rw-rw-`, UID 1000 and GID 1006 for all six character nodes. No historical `videoN` IDs were retained in the serialized values. They are not inferred from record order or minor numbers and the original result/status is unchanged.

M2.3 baseline: `33e28e4cdca2089925e28ad8b14fe7d41d9c08e7`. Evidence schema is `p3a6.m2.node_inventory.v2`; collector revision is `P3-A6-M2-v3`. Parser/evidence now retain each exact validated `videoN` as `node_id`. Bounded sysfs field statuses distinguish `ATTRIBUTE_MISSING`, `PERMISSION_DENIED` and `INVALID`; failed values are empty in the wire protocol and `null` in parsed evidence. `PERMISSION_DENIED` means the fixed path was not readable/openable in the shell context; it does not identify DAC versus SELinux. Malformed raw values are discarded. Evidence adds a `node_correlations` summary: major groups are explicitly marked ambiguous where multiple nodes share a major, and an individual pair is emitted only for a unique exact `major:minor` on both sources. This proves neither process ownership nor PVR ioctl/queue attribution.

The historical M2.3 node/SOF audit is [`P3-A6-M2.3-Node-Identity-and-SOF-Provenance.md`](P3-A6-M2.3-Node-Identity-and-SOF-Provenance.md); the current Phoenix follow-up is [`P3-A6-M2.4-Phoenix-Kernel-SOF-to-CSL-Audit.md`](P3-A6-M2.4-Phoenix-Kernel-SOF-to-CSL-Audit.md). At the time of M2.3/M2.4, the source bytes were unavailable. M2.5 subsequently verified the pinned source ABI and in-tree SOF dataflow, but did not resolve runtime build applicability or the userspace CRM-to-CSL bridge. Existing Pico ELF research separately shows a QTIMER-labeled CSL message and previous-ring-slot fallback; neither is tied to the kernel event or physical SOF/exposure start. See the M2.5 audit for current statuses.

M2.3 implementation SHA-256: `4c718118378e6be05de9ece4afa53bd481df46e286b9b1137db98506417602ca`; pinned ADB runner is unchanged. Current fixed probe hashes are listed separately below.

M2.3 offline verification: PowerShell M2 harness **410 assertions PASS**; `python -m unittest discover -s pico/tests` — **201/201 PASS**; M1 PowerShell harness — **29/29 PASS**; dedicated WSL POSIX integration — **PASS**; `git diff --check` — **PASS**. New POSIX coverage verifies an absent attribute, unreadable attribute, unsearchable parent directory, malformed/multiline/overlong values, explicit `videoN` retention, ambiguous shared-major grouping and unique exact `major:minor` matching. No device/approval action occurred. These counts are offline regression evidence, not a new hardware result.

## M2.2 probe source hashes (historical)

Хэш считается от точных canonical UTF-8 bytes без BOM, с LF line endings и одним заключительным LF; лимит — числовой literal, поэтому hash зависит от значения лимита.

| Script | Node limit | SHA-256 |
|---|---:|---|
| Sysfs template | 1 | `12890626c75ae07a861d519e714a679a826d996bd7ba27c6f226d6633a0d84e0` |
| Sysfs template | 16 | `a018bff12958c99ef3fc74b2b370c6f337a12bd0ab0b85f0e5683bf46d53a47a` |
| `/dev` template | 1 | `d4de43029e123a1dfe3248a54bffcb5578abbcdd86199eafde800139115d50ab` |
| `/dev` template | 16 | `696ea24441a66d81d0b53303851c8c0d1d4bf1c62d1adf503daad1bae642c399` |

## M2.3 current fixed probe hashes

| Script | Node limit | SHA-256 |
|---|---:|---|
| Sysfs template | 1 | `eb5f867d1dc16974ef32804e09e92c1a2baf4fbb16835ca628de792033b890ac` |
| Sysfs template | 16 | `2a1b5554e195b39082fe0f56b3e531a8005cb591281e44702c5453a50be90a4b` |
| `/dev` template | 1 | `d4de43029e123a1dfe3248a54bffcb5578abbcdd86199eafde800139115d50ab` |
| `/dev` template | 16 | `696ea24441a66d81d0b53303851c8c0d1d4bf1c62d1adf503daad1bae642c399` |

## GO / BLOCKED

M2.2 hardware metadata inventory is **`PARTIAL_LIMITATIONS`**, not PASS; the two unavailable sysfs names and six `/dev` records are owner-reported observations. No additional node-only hardware run is recommended solely to recover historical `videoN` IDs, since they cannot be reconstructed from the saved evidence. A later separately approved run would use the v3 parser to preserve IDs and bounded field statuses.

For SOF provenance, **continue targeted offline, build-matched Qualcomm kernel source/header research. A runtime SOF/exposure attribution experiment remains BLOCKED** until the exact event contract and Pico applicability are established and a safe numeric-only observation method is separately reviewed. No new approval or hardware action was performed here.

M2.4 offline verification: `python -m unittest discover -s pico/tests` — **201/201 PASS**; `pwsh -NoProfile -File .\pico\tests\p3a6_inventory_collector.tests.ps1` — **29/29 PASS**; `pwsh -NoProfile -File .\pico\tests\p3a6_camera_nodes.tests.ps1` — **410 assertions PASS**; `pwsh -NoProfile -File .\pico\tests\p3a6_posix_shell_integration.tests.ps1` — **PASS**; `git diff --check` — **PASS**. Documentation-only research; no ADB, device, camera or approval action occurred. These regressions do not establish Phoenix source contents or running-kernel applicability.

Будущая команда (не запускалась):

```powershell
pwsh -NoProfile -File C:\Dev\PicoLHSync\pico\tools\collect_p3a6_camera_node_inventory.ps1 -ApprovalFile "$env:LOCALAPPDATA\PicoLHSync\approvals\<fresh-M2-approval>.json"
```

Команда должна запускаться в интерактивном PowerShell 7; на запрос `Confirm operation (yes/no)` допустим только ответ `yes`. Если владелец заранее выбрал transport ID, можно добавить `-TransportId <numeric-id>`.

Эта фаза может подтвердить только список node metadata на момент чтения. Она не устанавливает fd ownership, `VideoQueueUtil` ioctl attribution, queue behavior, QBUF/DQBUF ID roundtrip, frame delivery, physical SOF или exposure start. Не запускать process-FD follow-up без отдельного scope и approval.


## M2.5 — Phoenix pinned kernel ABI and CSL bridge (2026-10-19)

The official ByteDance Phoenix kernel commit ceafd3afc0208c03e0eb7a1a60939d147f92d72a was acquired and checked offline. The evidence package records byte sizes, Git blob IDs and SHA-256 for all eight requested camera sources, Makefile, README, pvr_kernel_config, exact pinned V4L2/UAPI dependencies, and minimal CSID register/version tables. No Qualcomm analogue was substituted.

The pinned source proves its internal CSID SOF register → QTIMER nanoseconds/derived BOOTTIME → IFE manager → ISP context → CRM V4L2 event queue path. Same-commit V4L2 core source verifies the generic ioctl dispatch: SUBSCRIBE_EVENT reaches the CRM subscription callback, and DQEVENT reaches the V4L2 event queue and copies the event back to the ioctl caller. AArch64 Clang assertions pass: cam_req_mgr_message is 56 bytes; frame request_id and timestamp are at message offsets +0x08 and +0x18, fitting the 64-byte V4L2 data payload. Those offsets match QuickCamera CSLMessageHandler reads in the SHA-pinned ELF, but the outer prefix differs (CRM session handle vs CSL message type); no userspace consumer and conversion into the CSL message were found. Source applicability to the owner-reported Android 10 / 4.19.81-perf+ build is COMPATIBLE_BUT_UNVERIFIED, not exact. Physical SOF/exposure meaning remains BLOCKED.

Current evidence and per-edge classifications are in P3-A6-M2.5-Phoenix-Pinned-ABI-and-CSL-Bridge.md. P3-A4-Proof-Matrix.md now uses SOURCE_VERIFIED, BINARY_STATIC_VERIFIED, ABI_COMPATIBLE_UNPROVEN, RUNTIME_UNKNOWN and BLOCKED for the new edges. P3-A6-Acceptance-Matrix.md keeps runtime mapping and physical timing blocked/unknown. Historical M2.4 wording is marked as a time-bounded snapshot.

M2.5 offline verification: Python unittest suite 201/201 PASS; M1 PowerShell harness 29/29 PASS; M2 PowerShell harness 410 assertions PASS; local WSL POSIX integration PASS; git diff --check PASS. No device, ADB, camera, root, ioctl, tracing or instrumentation operation occurred.

Canonical evidence publication: PUBLISHED and independent read-back verified at \\192.168.23.63\Torrents\Codex\PicoLHSync\P3-A, base name p3a6-m2.5-phoenix-ceafd3af-20261019T100630Z-3ed7bc2f. ZIP and external manifest hashes matched their final .sha256 sidecar; the publisher placed the sidecar last and no .part files remained. The package retains BLOCKED diagnostics and includes no proprietary ELF or full disassembly.

Final canonical artifact SHA-256 values, independently read back with PowerShell: ZIP `9d8dd6224680bb253535d781dd7565119a5adb50701e97322e6f72220d678a14`; external manifest `d532b75fd4caee6d1f5b247791c10344697f76d5ff6a195aaab5adc3187d6591`; sidecar `9e56ddd1da0d7499954bec5d2aa33ca956b175837d7b9fb87fb84a40f147a31f`. The archive contains 31 pinned source files and a BLOCKED diagnostic marker; readback verified the exact source count, manifest status, both payload hashes, sidecar-last timestamp ordering, and absence of `.part` files.

All gates remain false: exact_time, mapping_verified, pose_verified, shared_buffer_identity_verified, frame_meta_bridge_verified, physical_event_verified and live_lighthouse_correction_allowed. Next work should first seek an exact build/config/device-tree mapping and the missing CSL bridge source; runtime instrumentation is not justified by this source-only pass.

## M2.6 — CamX CRM-to-CSL bridge audit (2026-10-19)

At baseline `241d61d4e066ea1f8f4ae79209bf7f1c535211cd`, exact bytes for the three requested `comprehensive9/vendor_qcom_proprietary` files at revision `36fc163a534963a5b3af52186af5efcc63401ad2` were fetched from pinned raw URLs. GitHub Contents blob IDs matched local `git hash-object`; byte lengths and SHA-256 values are recorded in [P3-A6-M2.6-CamX-CRM-to-CSL-Bridge.md](P3-A6-M2.6-CamX-CRM-to-CSL-Bridge.md). The minimal `camxtypes.h` dependency was also pinned for layout validation.

The public source verifies a direct `VIDIOC_SUBSCRIBE_EVENT` ioctl, poll followed by direct `VIDIOC_DQEVENT`, CRM payload decoding, per-link dispatch, and construction of `CSLMessage`. SOF maps to `CSLTimestampTypeQtimer` / `bNotify=FALSE`; SOF_BOOT_TS maps to Mono/boot-time / `bNotify=TRUE`. Timestamp values are copied unchanged at this bridge. `Pipeline::CSLMessageHandler` maps CSL sync IDs back to pipeline request IDs using a modulo table; the identifiers must not be assumed equal. AArch64 Clang++ assertions against the exact header pass: `CSLMessage` is size 48/alignment 8, with request ID `+0x08` and timestamp `+0x18`.

The SHA-pinned Pico `quickcamera.core.so` has a static `CSLRegisterMessageHandler` call whose relocated callback pointer resolves to its own handler, reads the compatible offsets and includes the same diagnostic format. It declares `DT_NEEDED camx_core.so`; the HIDL implementation declares a dependency on `quickcamera.core.so`. These are ELF declarations, not runtime loader proof. No `camx_core.so` bytes or Build ID exist in the already available private artifact set. Per the bounded search rule, no unrelated Qualcomm variants were pursued. The public CamX/Phoenix-to-Pico kernel event edge remains **BLOCKED**; runtime occurrence is **NOT OBSERVED**.

M2.6 source-to-sink statuses: public CamX bridge `SOURCE_VERIFIED` for its own revision; QuickCamera handler/callback `BINARY_STATIC_VERIFIED`; cross-source ABI `ABI_COMPATIBLE_UNPROVEN`; matching Pico provider and exact event identity `BLOCKED`; runtime event selection/frequency `RUNTIME_UNKNOWN`. Offline verification: Python 201/201 PASS, M1 PowerShell 29/29 PASS, M2 PowerShell 410/410 PASS, WSL POSIX integration PASS, and `git diff --check` PASS. Canonical publication receipt for this audit is recorded below.

Canonical M2.6 evidence publication: **PUBLISHED**, independently read back at `\\192.168.23.63\Torrents\Codex\PicoLHSync\P3-A`, base `p3a6-m2.6-camx-36fc163a-20261019T105742Z-16f06b2c`. The ZIP contains the report, manifest and four exact public source files; it includes no proprietary ELF or full disassembly. ZIP SHA-256 `7b7df28adb7a058a3bf2692d153463bfb9d08539f05dbc73cec9e18781726708` (80,539 bytes); external manifest SHA-256 `560138650c534fdbcee414332ba669a5d9f7efb8af581c00e3d872645c7811b4` (3,162 bytes); `.sha256` sidecar SHA-256 `bd1fb235426a489d6d98a94b9c638f39b349655d40f8e251ec725aecc4f91038` (250 bytes). Sidecar entries match independent final-file hashes. Read-back confirmed all four embedded source hashes, ZIP integrity, sidecar last-write ordering, and no `.part` files. The publisher raised `KeyError: 'errors'` while constructing its return object after the final files and sidecar had been committed; independent read-back verified the committed artifacts, so publication is confirmed while the publisher response error is retained here as a diagnostic.

All gates remain false: `exact_time=false`, `mapping_verified=false`, `pose_verified=false`, `shared_buffer_identity_verified=false`, `frame_meta_bridge_verified=false`, `physical_event_verified=false`, `live_lighthouse_correction_allowed=false`.

## M2.7A — provider acquisition preparation (offline only)

Baseline `5ec6768c3f5a23a9ad24f4f8fa85d8bf4a3800c2`. A separate Python runner and synthetic/WSL tests are prepared for future `read-only-camx-core-provider-acquisition`. This is not an M2.7B run: no ADB/ADB server/Pico was used, no approval was created, no ELF was obtained, and no SMB publication was attempted. Existing M2.6 canonical artifacts were not changed or republished.

The runner searches actual candidates under the six existing P3-A library roots, preserves every observed/resolved path, and fails closed on more than 16 candidates. It requires the exact owner-bound fingerprint, A8110/PICOA8110/Phoenix_ovs/Pico tuple, and `arm64-v8a`; no property tuple is treated as cryptographic attestation. It uses the pinned SDK ADB executable, explicit serial or transport ID, exact per-command argument allowlist, exact lowercase interactive `yes`, and a fresh approval for action `read-only-camx-core-provider-acquisition`. The common execution gate is rechecked immediately before every native ADB call.

The effective bounds are 60 seconds, 200 ADB-call observations, 160 native invocations, 16 candidates, 64 MiB per ELF, 128 MiB aggregate transfer and 64 KiB returned ADB stdout. All candidate sizes are queried before any pull so an aggregate overflow does not select an arbitrary subset. For each acquired ELF the runner validates path resolution, remote SHA-256 before and after, local size/hash and ELF64/AArch64. Local NDK `llvm-readelf` records Build ID, dynamic exports/undefined symbols and `DT_NEEDED`; bridge symbol hits are static-analysis locators, not proof of a full callback bridge. Temporary local staging is removed after canonical package publication or failure.

The generated POSIX script executed against temporary WSL fixtures with regular and symlink candidates, literal tab bytes and parser round-trip. This does not establish exact Android 10/PICO Toybox support for `find`, `readlink -f`, `wc -c`, or `sha256sum`, nor firmware access/SELinux permissions. No fallback is permitted. A future runner can only publish via the existing canonical P3-A SMB publisher, with the sidecar last; no publication took place during this preparation.

The existing `canonical_commit()` receipt bug for diagnostic reports lacking an `errors` key is fixed with `.get('errors', [])`. A regression verifies a successful receipt and finalization order ZIP → manifest → `.sha256`; this task did not call the canonical publisher or re-publish M2.6 files.

Future separately approved command (documented only; not executed):

```powershell
python .\pico\tools\p3a_m27b_camx_provider.py --approval-file "$env:LOCALAPPDATA\PicoLHSync\approvals\<fresh-M2.7B-approval>.json" --serial "<explicit-target>"
```

Alternative: replace the selector with `--transport-id <selected-positive-number>`. Expected result is a private package containing all verified candidate ELF files and a manifest, or an explicit `PARTIAL`/`BLOCKED` diagnostic package. The next hardware action requires the owner's separate explicit approval; do not reuse M1/M2 approval.

The M2.6 bridge claim is unchanged: provider bytes and Build ID remain absent; kernel-event identity and runtime load remain **BLOCKED / NOT OBSERVED**. M2.7A offline synthetic success does not raise `M2-SOF-09` or any timing/mapping/physical-event gate.

M2.7A verification totals: Python `unittest discover -s pico/tests` **223/223 PASS**; M1 PowerShell **29/29 PASS**; M2 PowerShell **410 PASS**; existing M1 WSL POSIX integration **PASS**; M2.7B WSL POSIX integration **PASS**; dry-run **DRY_RUN_ONLY**; `git diff --check` **PASS**. All are local synthetic/offline checks.

### M2.7A final review and publication readiness

Final offline review found that failed canonical `.part` read-back could leave a temporary file and a repeated package name could replace prior canonical outputs. `canonical_commit()` now validates the package basename, rejects existing finals/temporary files, creates temporary files exclusively, cleans only `.part` files created by the current call on failure, and returns a receipt only after final sidecar read-back. A regression verifies collision refusal preserves prior ZIP/manifest/sidecar bytes, traversal names fail, corrupt read-back leaves no `.part`, and successful receipt ordering remains ZIP → manifest → `.sha256`.

The pinned SDK ADB resolver now rejects a path that resolves outside the configured SDK location; regression coverage includes an unrelated `adb.exe` in PATH, a simulated redirected pinned path, and missing SDK. Final status is **M2.7A offline preparation GO; M2.7B NOT AUTHORIZED / NOT RUN**. No ADB, approval, Pico, proprietary ELF, or SMB action occurred. Timing, mapping, pose, shared-buffer, frame-meta, physical-event, and Lighthouse gates remain false.

## M2.7B — initial owner-authorized acquisition result (2026-10-19)

The owner subsequently granted direct authorization in the current task for a single-purpose unattended M2.7B run. The runner now has `--owner-authorized-run`, with no approval JSON or interactive `yes`; it uses only the pinned SDK ADB binary and one fixed digest-bound target supplied in a process-local environment variable. The mode is audit metadata, not cryptographic authorization; any future use requires fresh direct owner authorization. The M2.7B changes do not add the raw target address to their runner/tests/docs; pre-existing legacy project defaults were not changed.

Three bounded attempts were published to the canonical private root. Each stopped after one exact `adb connect` call with Windows TCP refused (10061); no `get-state`, identity property query, library discovery, path/hash/size probe or pull was executed. There is no evidence that `camx_core.so` is absent: no provider path was observed. The first two manifests record the pre-diagnostic `BLOCKED_CONNECT_OUTPUT`; the third contains a bounded redacted response preview. Independent read-back matched each ZIP and manifest digest against its sidecar, archive validation passed, the sidecar was written last and no `.part` files remained. Detailed receipts are in [P3-A6-M2.7B-CamX-Provider-Analysis.md](P3-A6-M2.7B-CamX-Provider-Analysis.md).

The runner and offline regression now distinguish connection refused from authentication/other connection failures while staying fail-closed. This diagnostic correction was tested synthetically; no fourth hardware attempt was made because three immediate attempts showed the target endpoint actively refusing connections. AOSP Android 12 source documents the `host:connect` request and connection-status response families, but is only upstream context, not a claim about the installed host ADB version.

Initial M2.7B result: **BLOCKED before device identity and candidate discovery**. This was superseded by the connectivity recovery and acquisition attempt below. The three initial package records remain preserved unchanged.

Final offline verification after the runner/parser changes: Python `unittest discover -s pico/tests` **230/230 PASS**, M2.7B-specific Python tests **28/28 PASS**, M1 PowerShell **29/29 PASS**, M2 PowerShell **410 PASS**, M1 WSL POSIX integration **PASS**, M2.7B WSL POSIX integration **PASS**, dry-run **DRY_RUN_ONLY**, `py_compile` **PASS**, `git diff --check` **PASS**. Hardware status at that point was **BLOCKED before connection**; no ELF was acquired and no timing/mapping/physical-event/Lighthouse gates changed.

## M2.7B — connectivity recovery and acquisition follow-up (2026-10-19)

The Windows reachability check returned 0/2 ping replies and TCP/5555 closed. A dynamic ARP entry existed, but there was no trusted MAC binding to identify it as Pico. The pinned SDK ADB client found a usable USB transport; its serial is intentionally omitted. The USB build fingerprint matched the exact owner-bound firmware before the transport-only `adb -s <USB_SERIAL> tcpip 5555` command was sent. ADB then connected to the owner-specified TCP endpoint, `get-state` returned `device`, and the same fingerprint matched over TCP. This verifies software identity across both transports but is not cryptographic attestation.

The existing acquisition runner verified model `A8110`, device `PICOA8110`, name `Phoenix_ovs`, manufacturer `Pico`, the expected build fingerprint and ABI `arm64-v8a`. It completed 9 ADB commands/observations and returned `PARTIAL_DISCOVERY`, with 0 candidates. Root statuses were `/system=SCANNED`, `/system_ext=ABSENT`, `/vendor=FIND_ERROR`, `/odm=FIND_ERROR`, `/product=FIND_ERROR`, `/apex=FIND_ERROR`. Since stderr is suppressed by the fixed probe, the cause of each `FIND_ERROR` is unknown. The scanned `/system` root produced no candidate. No candidate size/hash, pull, or ELF analysis ran; do not claim the library is absent.

One partial package was published and independently verified, with sidecar last: `p3a-m27b-camx-core-20261019T152544Z-1144ffab`; ZIP SHA-256 `bf50c1424c04c9cad683d9b48ac3837e2c48533c1231f11ad1e39ad8bbe18270`, manifest SHA-256 `8499ef1fd7b4c747af003350de7040174a88d32632ad8abe2b2d8b2bce820d72`, sidecar SHA-256 `3de26862858df4557f59d43ca1a1adc5f557e83bbbad62fe541574d3b3f1ba0a`. The archive contains only the manifest. No duplicate package was created for the repeated network check.

Status at this historical stage: **PARTIAL / BLOCKED at fixed-root discovery**. This was superseded by the recovery and provider acquisition below. All timing, mapping, pose, shared-buffer, frame-meta, physical-event and Lighthouse gates remain `false`.

## M2.7B final recovery, acquisition and static provider bridge (2026-10-19)

The client-side defect was fixed: validated stdout candidates survive a nonzero `find` status, while the affected root remains `FIND_ERROR`/`SCAN_INCOMPLETE` and overall discovery remains incomplete. Search is restricted to expected library paths, fixed library subtrees and eligible APEX `lib64` directories. No full-partition scan or permission bypass was added. Python and local `/bin/sh` integration fixtures verify exit-1 candidate retention, independent root status, symlinks, parser round-trip, malformed paths, limits and script-hash regeneration.

Using the existing TCP transport and pinned SDK ADB, one owner-authorized acquisition run verified the software tuple `A8110 / PICOA8110 / Phoenix_ovs / Pico`, exact owner-bound fingerprint and ABI `arm64-v8a`. The fixed search areas completed; vendor/system/product/APEX were scanned, and ODM/system_ext were absent. Exactly one candidate was found: `/vendor/lib64/camx_core.so`. The 8,664,624-byte ELF64/AArch64 passed remote pre-pull, local and remote post-pull SHA-256 equality (`7502d93342e5efe4d96a53c08ca7dfc7778d0ca5c728a9a0905be2611c0f1a77`); Build ID is `c83b58a36b8273c0a458bc26c28f5af4`.

Canonical private package `p3a-m27b-camx-core-20261019T160013Z-37143c21` passed independent read-back. ZIP SHA-256 `79ac8ad9d175544232b0a6a2d276610ebd9bd20b50f1bd0a061dfaeab65c791f`; manifest SHA-256 `b1dd3a87ef1f549c703b22ece43479f2b4d8cc331e1a2a67a174b0d454263222`; sidecar-file SHA-256 `5e304e466634f92270311a9de3ed1bd955e94bfdc159e46caf8ffbbf1b95bb4c`. Embedded and external manifest bytes match; the sidecar matches the ZIP and was written last. Proprietary bytes remain private.

Offline static analysis of a temporary hash-verified copy establishes provider binary code for CRM V4L2 event subscription/dequeue, CRM field extraction, `CSLMessage` construction and registered callback dispatch. QuickCamera's pinned registration and compatible field reads provide a static structural bridge. Provider runtime loading, event delivery, live request-ID correlation, fallback occurrence and selected timestamp source remain `RUNTIME_UNKNOWN`; exact running-kernel source mapping and physical SOF/exposure meaning remain unproven. No camera activation, image collection, runtime tracing or Lighthouse operation occurred. Detailed addresses and hashes are in [P3-A6-M2.7B-CamX-Provider-Analysis.md](P3-A6-M2.7B-CamX-Provider-Analysis.md).

Final M2.7B status: **PACKAGE_READY; offline provider static analysis complete**. Final offline verification: Python **234/234**, M1 PowerShell **29/29**, M2 PowerShell **410 assertions**, M1 and M2.7B WSL POSIX integrations **PASS**, `py_compile` **PASS**, dry-run **DRY_RUN_ONLY**, and `git diff --check` **PASS**. `exact_time`, `mapping_verified`, `pose_verified`, `shared_buffer_identity_verified`, `frame_meta_bridge_verified`, `physical_event_verified` and `live_lighthouse_correction_allowed` remain `false`.

## M2.8C-R — offline logcat framing recovery (2026-10-19)

The M2.8C published baseline had documents but not its Python collector/parser, fixed POSIX probe, synthetic tests, or WSL integration fixture. A targeted local repo/temp search did not find those sources. The M2.8C-R files are reconstructed from the documented interface and are explicitly not byte-identical to the lost probe. The original raw 3,540-byte response was not saved; therefore the initial `BLOCKED_OUTPUT_FRAMING` subcause stays `UNKNOWN` and the historical result is unchanged.

Added offline-only reconstructed artifacts:

- `pico/tools/p3a_m28c_logcat.py`: strict protocol parser and exact inspectable argv; no ADB executor.
- `pico/tools/p3a_m28c_logcat_probe.sh`: fixed `ps -A -o PID,NAME` and `logcat -b main -d -v threadtime -t 256` probe, bounded to 16 process candidates, 40 normalized records and 64 KiB.
- `pico/tests/test_p3a_m28c_logcat.py` and `pico/tests/p3a_m28c_posix_integration.tests.ps1`: parser and real local WSL `/bin/sh`/`awk` integration fixtures.

Host failures return one of `OUTPUT_LINE_LIMIT`, `INVALID_CONTROL_CHARACTER`, `INVALID_LINE_ENDING`, `MALFORMED_PROTOCOL_RECORD`, `MISSING_PROTOCOL_TERMINATOR`, `OUTPUT_TRUNCATED`, `REMOTE_FILTER_UNVERIFIED`, `LOGCAT_UNSUPPORTED_OPTION`, or `REMOTE_COMMAND_FAILURE` with safe counts and optional line/offset only. The reconstructed remote probe buffers and allowlists output, discarding event rows when logcat fails. Stderr remains separate from stdout; the parser returns only a safe code for stderr failures. Synthetic tests include CRLF and invalid framing, 3,540-byte input, raw-record injection, overlong lines, exact 40/41 limits, separate stderr, nonzero status, unsupported options, and AWK/process errors.

Static QuickCamera argument analysis corrected an earlier M2.8C report statement. At `0x376b4`, x9/x10 load message `+0x08/+0x10`; later stack setup passes the `+0x10` value as the `frameCount` format argument. The `+0x20` load at `0x376d8` is passed as `linkhdl`. The acquired provider's recorded static flow copies CRM `frame_id` to message `+0x10`, so these fields have a static dataflow relation. This does not imply runtime callback occurrence, pipeline/PVR ID equality, or `FrameMetaDate` identity. `monoTimestamp` reloads the same request-ID modulo-38 ring slot as the timestamp on the direct log path; it is not an independent Android monotonic measurement. The log requires message type 0, timestamp type 0, and existing INFO gates; `bNotify` is read after the log call.

WSL verifies this reconstructed source against local POSIX shell/awk only. Android 10 Toybox `awk`, `logcat` option behavior, and exact ADB remote shell quoting remain unverified. No Android incompatibility was proven offline, and no ADB/Pico/logcat run occurred in M2.8C-R. The next technically useful experiment is one fresh bounded default-log snapshot only after those compatibility points are resolved and separately authorized; success could establish a callback-specific log record with logged request/frame/timestamp fields, but cannot establish CRM event ID, timestamp clock domain/units, runtime provider identity, fallback, physical SOF/exposure, PVR metadata join, or Lighthouse suitability.

The historical M2.8C hardware outcome and canonical packages remain unchanged. All timing, mapping, pose, shared-buffer, frame-meta, physical-event and Lighthouse gates remain `false`.

M2.8C-R final offline checks: Python **265/265 PASS** including **16/16** new parser/argv tests; M1 PowerShell **29/29 PASS**; M2 PowerShell **410 assertions PASS**; M1, M2.7B, M2.8B and M2.8C WSL POSIX integrations **PASS**; `git diff --check` **PASS**. The M2.8C probe and parser are reconstructed files, not original source recovery; there was no ADB or hardware activity.

## M2.8A — Runtime provenance preparation (2026-10-19)

Offline review re-read the already acquired provider from the canonical private ZIP and the pinned QuickCamera ELF. Provider identity remains `/vendor/lib64/camx_core.so`, size 8,664,624, SHA-256 `7502d93342e5efe4d96a53c08ca7dfc7778d0ca5c728a9a0905be2611c0f1a77`, Build ID `c83b58a36b8273c0a458bc26c28f5af4`. QuickCamera is 332,368 bytes, SHA-256 `fb22355acd35b9772a5538a7d1c49175641165ad0368e7c47e5831f5f1727017`, Build ID `5deb124dd763e9ebee78d01e4105d1f8`.

ELF metadata confirms QuickCamera has DT_NEEDED camx_core.so and an unversioned undefined CSLRegisterMessageHandler; the provider has the matching unversioned global export and SONAME camx_core.so. Both have Android platform symbol-version needs. This is static linkage compatibility, not proof of Android linker namespace resolution or runtime loading. Exact PICO linker configuration and process mapping are absent.

Current proof layers are separated: installed provider identity = HARDWARE ACQUISITION VERIFIED; runtime-loaded provider path = RUNTIME_UNKNOWN; callback occurrence = NOT OBSERVED; ID 0/2 marker branches = BINARY_STATIC_VERIFIED but runtime event correlation UNKNOWN; cross-layer request/frame IDs = PARTIAL STATIC with runtime equality UNKNOWN; timestamp clock domain = UNKNOWN; fallback occurrence and FrameMetaDate runtime data = NOT OBSERVED. Event 2 with zero request ID is skipped in the inspected provider path; this remains a static branch fact, not an event-generation guarantee.

The recommended next step is a new action-specific, read-only map snapshot for already-running QuickCamera/PVR processes. A fixed probe may retain only validated PID/name and exact allowlisted library mapping fields from `/proc/<pid>/maps`, and compare provider mapping device/inode with a contemporaneous stat of the installed path. Proposed cap: 15 seconds and 40 returned observations. M1.5 procfs FD denial makes maps permission denial a significant possibility; stop without privilege escalation. PASS proves only that the provider file was mapped in that process at the sample time. It does not prove callback execution, SOF/BOOT_TS events, ID joins, fallback, FrameMetaDate content, timestamp clock, physical SOF/exposure, pose, or Lighthouse suitability.

Without an already active ordinary camera stream, no new frame SOF events should be expected. A bounded read of already existing default-level logs could reveal only naturally emitted records; it must not change log settings, clear logs, or start a camera. Offline verification after the M2.8A documentation/matrix edits: Python 234/234, M1 PowerShell 29/29, M2 PowerShell 410, M1 WSL POSIX integration PASS, M2.7B WSL POSIX integration PASS, and git diff --check PASS. No runtime experiment, ADB, camera, ptrace, memory read, root, approval creation, tracing, SteamVR, or Lighthouse action occurred in M2.8A. All safety gates remain false. See [P3-A6-M2.8A-Runtime-Provenance-Preparation.md](P3-A6-M2.8A-Runtime-Provenance-Preparation.md).
