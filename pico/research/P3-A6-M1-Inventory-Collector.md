# P3-A6-M1 — Read-Only Inventory Collector

Дата: 2026-10-19. Репозиторий `C:\Dev\PicoLHSync`, branch `feature/pico-support`.

## Статус

**Последний owner-run M1.5: PARTIAL; M1.6 change: OFFLINE ONLY.** PowerShell 7 collector и mock/POSIX regression suite подготовлены. Владелец сообщил фактический M1.5 результат: process inventory сработал, но первая чужая `/proc/<pid>/fd` проверка вернула `PROC_ACCESS_DENIED`; подробности записаны ниже без приватного evidence package. В M1.6 в этом репозитории не запускались ADB-команды, ADB server или Pico; R1 остаётся `UNKNOWN/BLOCKED`.

Инструментальный контракт описывает только действие `read-only-inventory`. Approval не создан, аппаратное выполнение не одобрено. `-DryRun`/`--dry-run` не читает approval, не создаёт evidence и не вызывает ADB executor.

## Файлы

- [`collect_p3a6_inventory.ps1`](../tools/collect_p3a6_inventory.ps1) — CLI для Windows PowerShell 7; без ADB-операций внутри самого сценария dry-run.
- [`P3A6Inventory.psm1`](../tools/P3A6Inventory.psm1) — collector, native executor, ограниченный allowlist команд и приватная упаковка evidence.
- [`p3a6_execution_gate_cli.py`](../tools/p3a6_execution_gate_cli.py) — stdin-only bridge, вызывающий существующий [`p3a6_execution_gate.py`](../tools/p3a6_execution_gate.py). Логика и критерии gate не менялись.
- [`p3a6_inventory_collector.tests.ps1`](../tests/p3a6_inventory_collector.tests.ps1) — PowerShell сценарии с injected mock ADB executor, synthetic fixtures и exact native-allowlist assertions; M1.6 добавляет короткое подтверждение.
- [`p3a6_posix_shell_integration.tests.ps1`](../tests/p3a6_posix_shell_integration.tests.ps1) — исполняет сгенерированные process/FD probes в локальном WSL `/bin/sh` на синтетическом proc fixture, проверяя байты вывода и настоящий PowerShell parser.
- [`test_p3a6_inventory_collector.py`](../tests/test_p3a6_inventory_collector.py) — запускает PowerShell mock harness, POSIX integration harness и отдельно CLI dry-run.

## M1.2 correction — pinned Windows ADB executable

Native executor запускает только точный путь `$env:LOCALAPPDATA\Android\Sdk\platform-tools\adb.exe`. Перед запуском проверяются непустой абсолютный `LOCALAPPDATA`, нормализованный путь с именем `adb.exe` под ожидаемой `platform-tools` directory и существование обычного файла. Поиск через `Get-Command`, перебор ADB из PATH и fallback на другие копии не используются. Если pinned SDK executable отсутствует или путь нельзя проверить, команда завершается fail-closed до `Process.Start`; это не считается отказом command allowlist.

Offline regression fixture помещает два разных фиктивных `adb.exe` в PATH и отдельный placeholder по pinned SDK path. Она проверяет, что resolver возвращает полный pinned путь, allowlisted вызов не отклоняется из-за PATH duplicates, а при отсутствующем SDK executable возвращается `ExecutableUnavailable` без PATH fallback. Placeholders не являются ADB binaries и не обращаются к ADB server или устройству; аппаратная проверка не запускалась.

## M1.3 correction — preserve native ADB argument vectors

Private incident archive was checked locally: its SHA-256 matched `final.marker.json`; only the requested collection status and model field status/reason were inspected. No private archive, raw output, hash, or per-run values are included in this repository.

The no-transport reproduction confirmed the cause in PowerShell 7: assigning `if (...) { @('shell') }` to `$prefix` enumerates the single item into `System.String`; adding the property array then produces a malformed scalar argument instead of the three-item vector. `$prefix` and `$stateArgs` now use explicit `[string[]]` initialization and conditional reassignment. All four later prefix-plus-command constructions cast to `string[]`, including the metadata queries and process/FD shell probes.

The PowerShell mock executor invokes the actual `Test-P3A6AllowedAdbArguments` before any responder can return synthetic ADB output. Responders route only exact vector shapes; tests compare exact vectors for `get-state`, all four identity properties, fingerprint, Android release, kernel release, and generated process/FD probes both without a transport and with `-t 42`. A vector rejected by the native allowlist cannot be satisfied by a permissive mock response.

This is only an offline collector fix. It does not establish a successful device query or change any hardware gate. Offline readiness is `GO` for one separately authorized M1 retry; it is not a hardware `PASS`.

## Точный будущий контракт запуска

### Offline dry-run

```powershell
pwsh -NoProfile -File "C:\Dev\PicoLHSync\pico\tools\collect_p3a6_inventory.ps1" --dry-run
```

Ожидается JSON с `status=DRY_RUN`, exit code `3`, ноль ADB-вызовов и отсутствие evidence package. Обычный синтаксис PowerShell `-DryRun` также поддерживается.

### После отдельного разрешения владельца

Approval JSON должен находиться в приватном профиле Windows и соответствовать схеме `p3a6.hardware_approval.v1`: `device="Pico 4 Pro"`, ровно `approved_actions=["read-only-inventory"]`, UTC issue/expiry с окном не более 24 часов, `max_duration_seconds` и `max_observations`. Для первого сеанса рекомендуется ровно `60` секунд и `200` записей; collector применяет меньший предел из approval и собственных hard caps 60/200.

Минимальная форма approval (создаётся владельцем отдельно; время нужно заменить свежими UTC timestamp, это не выданное разрешение):

```json
{
  "schema": "p3a6.hardware_approval.v1",
  "approval_id": "P3A6-M1-REPLACE-WITH-RUN-ID",
  "device": "Pico 4 Pro",
  "approved_actions": ["read-only-inventory"],
  "max_duration_seconds": 60,
  "max_observations": 200,
  "issued_at_utc": "YYYY-MM-DDTHH:MM:SSZ",
  "expires_at_utc": "YYYY-MM-DDTHH:MM:SSZ"
}
```

Если подключено ровно одно устройство, будущая команда:

```powershell
pwsh -NoProfile -File "C:\Dev\PicoLHSync\pico\tools\collect_p3a6_inventory.ps1" `
  -ApprovalFile "$env:LOCALAPPDATA\PicoLHSync\p3a6-approval.json" `
  -OutputRoot "$env:LOCALAPPDATA\PicoLHSync\private-evidence"
```

После загрузки approval сценарий показывает `Device`, `Action`, эффективные пределы и запрашивает `Confirm operation (yes/no):`. Принимается только точное lowercase `yes` из интерактивного ввода. `no`, пустой ввод, `YES`, произвольный текст и перенаправленный/недоступный stdin блокируются до вызова ADB executor. Только после `yes` PowerShell формирует внутреннюю строку `P3-A6 APPROVE <approval_id> read-only-inventory`; владельцу не нужно вводить ID. Approval ID остаётся в приватном evidence. `yes` — только accident-prevention prompt, не аутентификация и не security boundary. Python gate/schema и его scope/expiry/limit проверки не меняются; gate повторно запускается **перед каждой ADB-командой**.

Коллектор не вызывает `adb devices` и не запрашивает serial. Сначала он выполняет только `adb get-state` (или `adb -t <id> get-state`, если явно указан `-TransportId`). Без выбранного transport неоднозначность нескольких устройств должна быть отклонена самим ADB; при nonzero результате collector классифицирует `more than one device` как `BLOCKED_MULTIPLE_DEVICES`, не записывает raw stderr и не запускает shell-команды. При выбранном transport точное состояние должно быть единственной строкой `device`. Transport ID используется только для вызовов текущего процесса и не сохраняется в evidence. Затем выполняются ровно четыре фиксированных identity `getprop` запроса. Принимается только точный owner-bound tuple `A8110 / PICOA8110 / Phoenix_ovs / Pico`; mismatch блокирует дальнейший inventory, а отсутствующее, malformed или multiline значение сохраняется только как статус/причина без raw output. Это проверка software-reported identity для выбора transport, не криптографическая аттестация и не доказательство конкретного аппаратного варианта. Если локальная версия ADB не сообщает неоднозначность через `get-state`, это ограничение будет видно как blocked/error, а не как успешный пустой inventory.

Успешное завершение возвращает exit code `0`; partial — `5`; blocked/error — `4`. Timeout, ADB error, неоднозначный/unready transport, mismatch exact Android property tuple, missing/malformed identity field, permission denial, исчерпание лимита или unsupported output не превращаются в пустой `COMPLETE`.

## Разрешённые наблюдения и методы

| Поле | Метод | Сохранённые значения |
|---|---|---|
| Android identity tuple | Четыре фиксированных запроса `getprop` для model/device/name/manufacturer | Только одиночные значения в ограниченном ASCII allowlist с методом/UTC временем; mismatch блокирует сбор до build/process probes |
| Build fingerprint | `adb -t <transport> shell getprop ro.build.fingerprint` | Строка, прошедшая строгую character/length allowlist |
| Android release | `adb -t <transport> shell getprop ro.build.version.release` | Строка версии |
| Kernel release | `adb -t <transport> shell uname -r` | Строка версии |
| QuickCamera/PVR processes | `ps -A -o PID,NAME`; статус завершения проверяется до фильтра `quickcamera|pvr` на target; не читаются args/cmdline | Только соответствующие process name и PID; ошибка/пустой вывод — `UNAVAILABLE` и останов |
| Open video descriptors | Для найденных PID читаются symlinks `/proc/<pid>/fd/*`; принимаются только `/dev/video[0-9]+` | PID, имя процесса, fd number и node path |
| fdinfo | Для найденного camera fd читаются `/proc/<pid>/fdinfo/<fd>` | Только allowlisted `pos`, `flags`, `mnt_id`, `ino`; flags допускаются в hex или Linux octal формате |

Процессы только перечисляются. Collector не запускает Camera2/PVR session, сервис или pipeline. При отказе доступа к `/proc`/fdinfo он сохраняет уже полученные allowlisted записи, ставит partial status и прекращает дальнейшие device commands; access failure может быть вызван SELinux либо обычными Unix permissions, и collector не пытается различать их через audit logs. Нет root, `su`, remount, install/push, reboot, hooks, process-memory reads, `dumpsys`, `logcat` или debug logging.

Native executor принимает только точные inventory command shapes и собранный из безопасного PID allowlisted probe; остальные аргументы, включая `adb root`, отклоняются до запуска процесса. `adb get-state` не запрашивает список устройств и serial. Если ADB возвращает serial в тексте ошибки при неоднозначности, raw stderr используется только transiently для классификации и отбрасывается; он не включается в console result, archive, marker, exception или test report. Явно заданный числовой transport ID также не сохраняется.

`ps -A -o PID,NAME`, `awk`, `readlink`, `getprop` и procfs доступность конкретной PICO OS заранее не доказаны. Ошибка `ps` или пустой ответ фиксируется как `UNAVAILABLE`, не как успешная инвентаризация с нулём процессов. Если команда отсутствует/запрещена, соответствующее поле фиксируется как unavailable/permission denied и run завершается без fallback к более широкому сбору.

## P3-A6-M1.1 — POSIX shell и ADB argument contract

В probe был воспроизведён протокольный дефект: `printf '%s\n' "$1"` печатал в FD/FDINFO/FDINFO_STATUS значения буквальные `\t`. Исправлено на отдельные фиксированные `printf` formats с табами в format string; все поля передаются отдельными `%s` arguments. Непроверенные значения не становятся format string или управляющими последовательностями. Parser по-прежнему требует точные поля, табы и allowlisted значения.

Проверка AOSP Android 10 выявила отдельную границу quoting: Android 10 ADB client собирает remote command соединением `shell` argv через пробелы без escaping; adbd передаёт полученную строку в `/system/bin/sh -c`. Поэтому многострочный probe передаётся как один POSIX single-quoted argument (с безопасным `'\''`-разрывом для внутренних одинарных кавычек). Native command allowlist принимает только точные generated probes в этом quoted form и отклоняет прежнюю unquoted форму. AOSP refs: [Android 10 ADB client `commandline.cpp`](https://android.googlesource.com/platform/system/core/+/refs/heads/android10-mainline-resolv-release/adb/client/commandline.cpp), [Android 10 adbd `shell_service.cpp`](https://android.googlesource.com/platform/system/core/+/android10-release/adb/daemon/shell_service.cpp). AOSP Toybox Android 10 help документирует `ps -A` и `-o` с полями `PID`/`NAME` ([source](https://android.googlesource.com/platform/external/toybox/+/refs/heads/android10-dev/generated/help.h)); vendor-совместимость конкретной PICO OS этим не установлена.

Локальный integration harness собрал фактический argv shape `shell sh -c <quoted multiline script>`, воспроизвёл Android 10 ADB join через пробелы и передал итоговую команду настоящему WSL `/bin/sh`. PowerShell `ProcessStartInfo.ArgumentList` передал remote command как один аргумент с newlines и shell quotes; этот host-side boundary проверен на WSL, не на `adb.exe`. В FD probe используются только синтетические `/tmp/...` proc/fdinfo files и test `readlink`; реальный `/proc` не читался. Зафиксированы сырые stdout bytes: FD разделён байтами `0x09`, последовательность `\\t` отсутствует, затем те же bytes успешно прошли настоящий `Convert-P3A6ProbeOutput` и сохранили node/allowlisted fdinfo. Process probe прогнан с фиксированным `ps -A -o PID,NAME`: valid header/rows дают `OBSERVED`; nonzero exit с частичным stdout и неправильный header дают только `UNAVAILABLE`. Fixture проверяет, что probe делает ровно один вызов этой команды на каждый запуск; fallback не добавляется.

Это доказывает local POSIX parsing/quoting на WSL и поведение AOSP-совместимого argv join, но не выполняет ADB client/server, не запускает Android `/system/bin/sh` или vendor Toybox на Pico и не доказывает совместимость конкретной прошивки. WSL fixture не является device observation или experimental PASS. Перед первым одобренным запуском следует ожидать `UNAVAILABLE`/`BLOCKED`, если target shell, `ps`, `awk`, `readlink` или procfs имеют другую семантику.

## Права и условия будущего сеанса

- На Windows нужны PowerShell 7, Python с доступным из PATH модулем `pico.tools.p3a6_execution_gate_cli`, `adb.exe` по точному пути `$env:LOCALAPPDATA\Android\Sdk\platform-tools\adb.exe`, доступ к `LOCALAPPDATA` и возможность задать private DACL на новую run-папку. Другие ADB-копии в PATH не учитываются. Collector не запрашивает elevation; если pinned executable отсутствует или ACL создать нельзя, он блокирует запуск до ADB.
- На Pico владелец должен заранее включить и авторизовать обычный USB debugging/ADB shell, выбрать правильное устройство и разрешить только действие `read-only-inventory`. Root, `su` и обход SELinux не нужны и не запрашиваются. Отказ в `/proc` или fdinfo останавливает сбор и сохраняется как partial evidence.
- Первый вызов `adb.exe` может запустить стандартный host-side ADB server, если его ещё нет. Collector не устанавливает и не меняет Pico-службы; выполнение shell-команд начинается только после approval gate и проверки модели. Если запуск host ADB server сам по себе запрещён политикой владельца, ADB должен быть заранее поднят отдельно и этот режим отдельно одобрен.
- Устройство должно вернуть точный tuple `A8110 / PICOA8110 / Phoenix_ovs / Pico`; это owner-bound software identity check, а не криптографическая attestation. Целевой аппарат Pico 4 Pro на international Pico OS — установленный owner-confirmed project fact. Evidence field `pico_4_pro_hardware_variant_status=NOT_VERIFIED` ограничен тем, что Android properties сами по себе не дают независимой attestation; он не оспаривает установленный hardware факт владельца. При неоднозначном `adb get-state` collection завершается до shell-команд; collector не перечисляет serial для выбора устройства.

## Private evidence package

По умолчанию пакет пишется в `$env:LOCALAPPDATA\PicoLHSync\private-evidence\<run-id>`. Разрешён только путь под `LOCALAPPDATA`, вне repository; проверяются reparse points. Для уникальной run directory задаётся защищённый DACL с доступом текущему владельцу и SYSTEM, без наследования. Если путь или ACL не удаётся закрепить, ADB не запускается.

Папка содержит:

- `evidence.zip` с единственным `evidence.json`;
- `final.marker.json`, созданный последним и содержащий SHA-256 архива.

Evidence фиксирует schema/run/approval/action, UTC start/end, elapsed time, эффективные caps, per-field status/value/method/time/build identity, выбранные process/PID/video fd/fdinfo, access limitations, PowerShell/tool source SHA-256, count consistency и privacy flags. Четыре Android identity properties сохраняются как отдельные технические поля с их `getprop` методами, временем и build identity после её получения. Identity object содержит owner-declared target `Pico 4 Pro`, статус tuple и раздельные статусы Phoenix-family / Pico 4 Pro hardware variant. `Phoenix-family VERIFIED` означает только точный software-reported tuple; `pico_4_pro_hardware_variant_status=NOT_VERIFIED` означает, что Android tuple не является самостоятельной hardware attestation, а не неизвестность или пересмотр owner-confirmed Pico 4 Pro. `cryptographic_attestation=false`. `A8110` и Android properties не являются уникальным или криптографическим доказательством варианта Pro. Пустые или не прочитанные поля остаются `NOT_OBSERVED`, `PERMISSION_DENIED` или `UNAVAILABLE`; raw stderr и malformed/multiline output не сохраняются. В evidence всегда остаются `false`:

```text
exact_time=false
mapping_verified=false
pose_verified=false
shared_buffer_identity_verified=false
frame_meta_bridge_verified=false
live_lighthouse_correction_allowed=false
physical_event_verified=false
```

Private archive не предназначен для публикации в GitHub. В репозиторий входят только schema/method/code/tests.

## Граница доказательства

Наличие открытого `/dev/videoN` в QuickCamera/PVR process — лишь fd inventory. Оно не устанавливает, что этот fd принадлежит `VideoQueueUtil` или использовался для `ioctl`; каждый `video_fd` помечается `NOT_ATTRIBUTED_TO_VIDEOQUEUEUTIL_IOCTL`. Поэтому M1 не повышает R1 выше `UNKNOWN/BLOCKED` и не доказывает QBUF/DQBUF ID roundtrip.

Инвентаризация не измеряет CSL request ID, QTIMER, fallback, `FrameMetaDate`, Android monotonic clock или delivery latency. Она не доказывает backing allocation identity/cache coherency и не задаёт физический SOF/exposure start. Для них нужны отдельные разрешённые исследования; физическое событие требует version-matched semantics или внешнего аппаратного reference.

## Regression и integration tests

`python -m unittest pico.tests.test_p3a6_inventory_collector -v` запускает настоящий PowerShell collector с mock responses и проверяет:

- отсутствующее/неверное/expired approval и expiry между командами;
- action scope escape, mismatch каждого Android identity property и несколько устройств;
- missing и multiline identity output для каждого из четырёх tuple fields, без сохранения raw values;
- timeout/partial output, ADB error, duration/record limits;
- `/proc`/fdinfo permission denial с прекращением последующих device commands, исчезнувший PID, ошибка `ps` и allowlisted fdinfo;
- нулевой executor call для dry-run, запрет `adb root` и обязательное POSIX quoting native allowlist;
- две фиктивные ADB-копии в PATH при pinned SDK path, выбор точного полного пути и fail-closed при отсутствующем SDK executable;
- фактический native argument allowlist до mock response, точные векторы всех команд без transport ID и с `-t 42`, включая process/FD probes;
- отсутствие serial/personal-looking данных в archive, неизменные false gates, ACL, ZIP SHA-256/final marker.
- реальный WSL `/bin/sh` запуск сгенерированных FD/process probes, проверка raw tab bytes, parser roundtrip, Android 10 argv join, `ps` success/error/header framing и отсутствия fallback.

Все проверки offline; integration использует только синтетический proc fixture и локальный WSL shell. `adb.exe`, ADB server, Pico и её camera/PVR pipeline не запускались. Результаты не создают experimental PASS и не повышают R1–R9.

Результат проверки M1.1 (2026-10-18): `python -m unittest discover -s pico/tests -v` — **198/198 PASS**; targeted `python -m unittest pico.tests.test_p3a6_inventory_collector -v` — **2/2 PASS**; PowerShell mock harness — **18/18 PASS**; POSIX integration harness — **PASS**; `git diff --check` — **PASS**. Эти тесты проверяют только локальное поведение и синтетические fixtures.

Результат проверки M1.2 (2026-10-18): `python -m unittest discover -s pico/tests -v` — **198/198 PASS**; targeted `python -m unittest pico.tests.test_p3a6_inventory_collector -v` — **2/2 PASS**; PowerShell mock harness — **19/19 PASS**; прямой WSL POSIX integration harness — **PASS**; `git diff --check` — **PASS**. PATH fixtures содержат только текстовые placeholders; запуск завершается до исполнения fixture. ADB client/executable, ADB server, Pico и camera/PVR pipeline не запускались.

Результат проверки M1.3 (2026-10-18): `python -m unittest discover -s pico/tests -v` — **198/198 PASS**; PowerShell mock harness — **20/20 PASS**; прямой WSL POSIX integration harness — **PASS**; `git diff --check` — **PASS**. До исправления строгий mock harness падал на точном model vector без transport ID, потому что native allowlist отклонял его до responder. После исправления no-transport и `-t 42` vectors проходят тот же allowlist. Это synthetic/offline доказательство; аппаратная инвентаризация не повторялась.

## P3-A6-M1.4 — owner-bound Phoenix-family identity tuple

Владелец наблюдал `ro.product.model=A8110`, `ro.product.device=PICOA8110`, `ro.product.name=Phoenix_ovs`, `ro.product.manufacturer=Pico`. Native command allowlist добавляет ровно эти три фиксированных product keys. Collector требует точного case-sensitive совпадения всего tuple; `A8110` отдельно, `PICOA81*`, похожие names, другие manufacturer/device значения, пропущенные поля и multiline output не принимаются. Well-formed mismatch сохраняет ограниченные значения как observed field evidence и останавливается со статусом `BLOCKED_UNEXPECTED_DEVICE`. Missing/malformed member сохраняется как `UNAVAILABLE` + reason и останавливается со статусом `BLOCKED_INVALID_DEVICE_IDENTITY`; multiline/raw output не попадает в evidence. Все `BLOCKED_*` runs помечаются `collection_status=BLOCKED` независимо от количества уже выполненных read-only identity запросов.

`phoenix_family_status=VERIFIED` значит только точное совпадение owner-bound Android property tuple. Pico 4 Pro на international Pico OS — установленный owner-confirmed hardware факт. Отдельное поле `pico_4_pro_hardware_variant_status=NOT_VERIFIED` указывает лишь, что Android properties и `A8110` не являются самостоятельной hardware attestation; оно не отменяет owner confirmation. `cryptographic_attestation=false`. Per-field evidence включает точную property query, время и build identity (после чтения fingerprint). Execution gate, exact argument vectors, pinned SDK ADB, private storage, caps 60 seconds/200 records, POSIX protocol и все false safety gates сохранены.

Проверки M1.4 исполняют точный tuple, неверные/prefix/case-variant значения, пустые, malformed и multiline ответы для каждого поля, identity-command error, metadata/provenance, разделение owner target и family/hardware statuses, все command vectors с transport/no-transport и действующий native allowlist до synthetic responder. Они являются offline-only и не создают hardware evidence.

Результат offline проверки M1.4 (2026-10-19): `python -m unittest discover -s pico/tests -v` — **198/198 PASS**; PowerShell mock collector — **25/25 PASS**; прямой WSL POSIX integration — **PASS** (FD byte/parser, Android 10 argv join, `ps` framing/errors). Полный Python suite также выполнил collector и POSIX integration tests. ADB, ADB server и Pico не запускались; аппаратный статус, queue attribution и последующие runtime acceptance не изменялись.

## P3-A6-M1.5 — colon в Android process name

Владелец сообщил о реальном process-list entry на Pico OS: `ps -A -o PID,NAME` завершился с exit 0, awk доступен, заголовок и PID корректны; среди 13 QuickCamera/PVR совпадений одно имя на позиции 13 содержит буквальный `:` и не содержит slash/brackets или дополнительных колонок. Сбор M1.4 остановился на этой записи со статусом `PARTIAL_UNEXPECTED_OUTPUT` после 9 ADB-команд и 8 records. Эти аппаратные сведения предоставлены владельцем; в M1.5 они не перепроверялись.

Парсер принимает теперь имена из того же ограниченного набора `[A-Za-z0-9_.@-]` с единственным добавленным символом `:` и прежним пределом 1–256 символов. PID по-прежнему ограничен 1–10 цифрами. Whitespace внутри имени, slash, brackets, control characters и прочие shell/protocol punctuation не принимаются. Collector не нормализует имя: `com.picovr.quickcamera:service` сохраняется точно и тот же PID проходит существующую read-only `/proc/<pid>/fd`/fdinfo процедуру. Ошибочная строка или неожиданный process-protocol record по-прежнему прекращают сбор как `PARTIAL_UNEXPECTED_OUTPUT`; malformed input не записывается и не приводит к FD probe.

Offline регрессия подаёт 13 synthetic matching process rows, помещая colon-name на позиции 13. Она проверяет process inventory count, точное сохранение имени в private evidence, FD probes PID 123–135 включая PID 135, native allowlist до каждого mock ответа и точные process/FD vectors с default transport и `-t 42`. Отдельные негативные cases проверяют slash в имени и неизвестную protocol запись. Collector evidence revision обновлена до `P3-A6-M1.5-v1`.

Результат offline проверки M1.5 (2026-10-19): PowerShell mock collector — **28/28 PASS**; полный `python -m unittest discover -s pico/tests -v` — **198/198 PASS**; прямой WSL POSIX integration — **PASS**; `git diff --check` — **PASS**. До исправления новая 13-row regression воспроизводимо завершилась `PARTIAL_UNEXPECTED_OUTPUT`; после исправления завершилась без этого статуса и все 13 synthetic PID дошли до mock FD probes. Никакая synthetic проверка не является аппаратной верификацией. В этой задаче ADB executable/client/server, Pico, camera service и tracking pipeline не запускались; approval не создавался.

Следующий M1 аппаратный повтор готов только как отдельный запуск с действительным approval и owner confirmation через неизменённый execution gate. Результат M1.5 показывает совместимость parser с сообщённым форматом имени, но не подтверждает доступность `/proc` на текущей прошивке, фактическую FD-таблицу, ioctl attribution или любые R1/runtime claims. Все safety gates остаются `false`, Lighthouse correction выключена.

## P3-A6-M1.5 owner-reported hardware outcome

Владелец подтвердил, что target hardware — **Pico 4 Pro на international Pico OS**; это установленный проектный факт. Реальный M1.5 run завершился `PARTIAL_PERMISSION_DENIED` после 10 ADB-команд и 10 records. Phoenix software tuple, build fingerprint, Android release и kernel release были observed; process list содержал 13 QuickCamera/PVR процессов. Первая `/proc/<pid>/fd` операция вернула `PROC_ACCESS_DENIED`, поэтому collector остановился: video FD records — 0. Этот итог остаётся **PARTIAL**, не PASS.

Отказ первой проверки не доказывает доступность или недоступность descriptor directories у остальных 12 процессов. Никакой retry/обход прав не выполняется автоматически; M2 proposal рассматривает отдельный per-process read-only scope с обычным ADB shell и явными per-PID denial records. Приватное evidence остаётся вне GitHub и не включено в этот handover.

## P3-A6-M1.6 — короткое interactive confirmation

Collector revision: `P3-A6-M1.6-v1`. CLI печатает target/action/effective limits и принимает только точное интерактивное `yes`; все альтернативы и неинтерактивный EOF блокируются до ADB. Строка для Python gate создаётся только после принятого `yes`; gate сам по-прежнему требует точный approval ID/action token и вызывается перед каждой командой. Тесты подтверждения: accepted `yes` запускает полный synthetic collector и сохраняет approval ID/action в evidence; `no`, пустой ввод, `YES`, unexpected text, пробел после `yes` и noninteractive EOF дают ноль ADB executor calls. Python gate отдельно подтверждает, что короткий `yes` не является его внутренним approval token. Результаты 2026-10-19: PowerShell harness **29/29 PASS**, полный Python suite **199/199 PASS**, прямой WSL POSIX integration **PASS**, `git diff --check` **PASS**. Никакого изменения approval schema, caps, privacy fields или safety gates нет.

## P3-A6-M2 — separate read-only node inventory

M2 preparation is implemented in a separate runner/module: [`collect_p3a6_camera_node_inventory.ps1`](../tools/collect_p3a6_camera_node_inventory.ps1), [`P3A6CameraNodes.psm1`](../tools/P3A6CameraNodes.psm1), with detailed handover in [`P3-A6-M2-Handover.md`](P3-A6-M2-Handover.md) and research rationale in [`P3-A6-M2-Read-Only-Camera-Metadata-Proposal.md`](P3-A6-M2-Read-Only-Camera-Metadata-Proposal.md). Its exact action is `read-only-camera-node-metadata`, limits are 30 seconds/40 observations/16 candidates per source, and interactive confirmation requires exact lowercase `yes`. It reads only fixed sysfs `name/index/dev` attributes and bounded `/dev/videoN` metadata; it never opens a node. `metadata_fields_complete` means those three sysfs fields were observed, not that the physical node identity is established. Overall status is `COMPLETE` only when both sources and every metadata record are observed; empty, denied, unavailable, partial or limited sources retain any independent values but yield `PARTIAL_LIMITATIONS`. M1 approval does not authorize M2. Final offline verification: M2 harness 336 assertions PASS, Python suite 201/201 PASS, M1 PowerShell harness 29/29 PASS, legacy WSL POSIX integration PASS and `git diff --check` PASS. No ADB, Pico, camera service, `/proc`, root or Lighthouse was used, and M2 hardware status remains NOT RUN. Process-FD follow-up is a separate, unimplemented scope requiring fresh approval. M1.5 owner-reported result remains `PARTIAL_PERMISSION_DENIED` and is unchanged by M2 synthetic tests.
