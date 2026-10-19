# P3-A6-M2 — Read-Only Camera Node Inventory Handover

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

The full SOF provenance audit is [`P3-A6-M2.3-Node-Identity-and-SOF-Provenance.md`](P3-A6-M2.3-Node-Identity-and-SOF-Provenance.md). Local project/source search found no matching `cam_req_mgr` source/header or definitions for `V4L_EVENT_CAM_REQ_MGR_SOF` / `V4L_EVENT_CAM_REQ_MGR_SOF_BOOT_TS`; no web or device access was used. Event payload, ID semantics, clock domain, version differences and Pico applicability remain **BLOCKED/UNKNOWN**. Existing Pico ELF research separately shows a QTIMER-labeled CSL message and previous-ring-slot fallback, but does not tie either to these kernel events or to physical SOF/exposure start.

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

Будущая команда (не запускалась):

```powershell
pwsh -NoProfile -File C:\Dev\PicoLHSync\pico\tools\collect_p3a6_camera_node_inventory.ps1 -ApprovalFile "$env:LOCALAPPDATA\PicoLHSync\approvals\<fresh-M2-approval>.json"
```

Команда должна запускаться в интерактивном PowerShell 7; на запрос `Confirm operation (yes/no)` допустим только ответ `yes`. Если владелец заранее выбрал transport ID, можно добавить `-TransportId <numeric-id>`.

Эта фаза может подтвердить только список node metadata на момент чтения. Она не устанавливает fd ownership, `VideoQueueUtil` ioctl attribution, queue behavior, QBUF/DQBUF ID roundtrip, frame delivery, physical SOF или exposure start. Не запускать process-FD follow-up без отдельного scope и approval.
