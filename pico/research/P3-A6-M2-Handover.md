# P3-A6-M2 — Read-Only Camera Node Inventory Handover

Дата: 2026-10-19. Реализация и проверка выполнены **offline only** в `C:\Dev\PicoLHSync`, branch `feature/pico-support`, от baseline `1bbb542ff90a1ac60876bc1991aff68270864a2e`. ADB client/server, Pico, camera services, `/proc`, root, tracing, SteamVR и Lighthouse не использовались. Approval record не создавался.

## Итог

Подготовлен самостоятельный runner [`collect_p3a6_camera_node_inventory.ps1`](../tools/collect_p3a6_camera_node_inventory.ps1) и модуль [`P3A6CameraNodes.psm1`](../tools/P3A6CameraNodes.psm1). M2 использует отдельное approval action `read-only-camera-node-metadata`; M1 action и runner не расширялись. Перед каждой командой collector перепроверяет общий Python gate, а pinned native ADB executor выполняет свою повторную gate-проверку и exact native allowlist.

Runner принимает только интерактивное точное lowercase `yes`. Только после этого создаётся внутренний token `P3-A6 APPROVE <approval_id> read-only-camera-node-metadata`. Это accident-prevention UX, не authentication. Срок/устройство/action проверяются общим gate непосредственно перед каждым разрешённым ADB invocation. Эффективный hard cap — 30 seconds, 40 node observations, максимум 16 candidates на источник.

Allowlist содержит только `get-state`, шесть фиксированных `getprop` keys, `uname -r` и точные `shell sh -c` bytes двух встроенных POSIX probe templates. Допускается default ADB transport или явный `-t <nonzero numeric id>`. Pinned executable: `$env:LOCALAPPDATA\Android\Sdk\platform-tools\adb.exe`; collector не перечисляет остальные ADB установки.

Sysfs probe читает только `/sys/class/video4linux/videoN/name`, `index`, `dev`, включая допустимые sysfs class symlinks. `/dev/videoN` проверяется на fully numeric suffix, symlink и character-node type; только metadata command `ls -ldn` анализируется, без открытия node. Недоступные, пустые, malformed или over-limit источники получают явный status; пустой inventory возвращает `PARTIAL_LIMITATIONS`, не success.

Статусы источника/полей: `OBSERVED`, `NOT_OBSERVED`, `UNAVAILABLE`, `PERMISSION_DENIED`, `LIMIT_REACHED`. Отдельная отсутствующая sysfs attribute не удаляет другие observations; `metadata_fields_complete` означает только, что все три разрешённых поля `name/index/dev` наблюдены, и не утверждает hardware identity. Итог `COMPLETE` выставляется только если оба источника `OBSERVED` и все найденные metadata fields/node metadata наблюдены; пустой, недоступный, ограниченный или частичный источник оставляет сохранённые значения, но даёт `PARTIAL_LIMITATIONS`. Parser отклоняет malformed/multiline records, неверные numeric values, лишние поля, duplicate node/attributes и записи после source terminator.

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

SHA-256 исходников этой offline реализации: module `d5a31a97933185a92ac66277a1a9d941358491858a15eccabbf1d16e9bc45dda`; runner `63ed273c01de3bbb098773546b2cadbd803e6d5a7d8d31c4c0e4297b20358066`. Точные probe hashes приведены ниже; production probe templates не менялись.

## Probe source hashes

Хэш считается от точных canonical UTF-8 bytes без BOM, с LF line endings и одним заключительным LF; лимит — числовой literal, поэтому hash зависит от значения лимита.

| Script | Node limit | SHA-256 |
|---|---:|---|
| Sysfs template | 1 | `12890626c75ae07a861d519e714a679a826d996bd7ba27c6f226d6633a0d84e0` |
| Sysfs template | 16 | `a018bff12958c99ef3fc74b2b370c6f337a12bd0ab0b85f0e5683bf46d53a47a` |
| `/dev` template | 1 | `d4de43029e123a1dfe3248a54bffcb5578abbcdd86199eafde800139115d50ab` |
| `/dev` template | 16 | `696ea24441a66d81d0b53303851c8c0d1d4bf1c62d1adf503daad1bae642c399` |

## GO / BLOCKED

**GO — только для одного отдельно одобренного node-metadata run. Hardware status сейчас NOT RUN.** Перед этим владелец должен создать отдельный действующий approval с exact action, target, expiry, `max_duration_seconds <=30`, `max_observations <=40`, выбрать единственный/default ADB transport и лично подтвердить `yes` в prompt. Если approval отсутствует/истёк, transport неоднозначен, identity tuple не совпала, любой command неуспешен или Toybox output несовместим — collector остановится без fallback и выдаст BLOCKED/PARTIAL.

Будущая команда (не запускалась):

```powershell
pwsh -NoProfile -File C:\Dev\PicoLHSync\pico\tools\collect_p3a6_camera_node_inventory.ps1 -ApprovalFile "$env:LOCALAPPDATA\PicoLHSync\approvals\<fresh-M2-approval>.json"
```

Команда должна запускаться в интерактивном PowerShell 7; на запрос `Confirm operation (yes/no)` допустим только ответ `yes`. Если владелец заранее выбрал transport ID, можно добавить `-TransportId <numeric-id>`.

Эта фаза может подтвердить только список node metadata на момент чтения. Она не устанавливает fd ownership, `VideoQueueUtil` ioctl attribution, queue behavior, QBUF/DQBUF ID roundtrip, frame delivery, physical SOF или exposure start. Не запускать process-FD follow-up без отдельного scope и approval.
