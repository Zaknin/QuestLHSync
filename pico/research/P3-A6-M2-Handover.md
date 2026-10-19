# P3-A6-M2 — Read-Only Camera Node Inventory Handover

## Current SOF provenance status — M2.6

M2.5 pinned Phoenix source continues to prove its own CSID→IFE→ISP→CRM path and generic V4L2 queue/dequeue contract. M2.6 additionally verified the specified public CamX source revision's complete direct-ioctl CRM-event→CSLMessage→callback implementation and AArch64 layout. The SHA-pinned Pico QuickCamera ELF registers its own callback and reads matching message offsets; its `DT_NEEDED` declares `camx_core.so`. The matching provider ELF is absent from the existing private artifacts, and no build mapping or runtime-loaded path ties the public CamX source to Pico.

Public CamX source conversion and the Pico QuickCamera callback are structurally compatible, but this is not proof that Pico's missing `camx_core.so` implements that source contract. Therefore exact kernel event → Pico CSL callback identity remains **BLOCKED**, and runtime occurrence remains **NOT OBSERVED**. Physical SOF/exposure semantics and all timing/mapping/Lighthouse gates remain false. See [P3-A6-M2.6-CamX-CRM-to-CSL-Bridge.md](P3-A6-M2.6-CamX-CRM-to-CSL-Bridge.md) and the prior [M2.5 Phoenix ABI audit](P3-A6-M2.5-Phoenix-Pinned-ABI-and-CSL-Bridge.md). No runtime instrumentation or hardware action is authorized by this offline audit.

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
