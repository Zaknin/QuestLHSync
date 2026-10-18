# P3-A6-M1 — Read-Only Inventory Collector

Дата: 2026-10-18. Репозиторий `C:\Dev\PicoLHSync`, branch `feature/pico-support`.

## Статус

**PREPARED OFFLINE; NOT RUN ON PICO.** Подготовлен PowerShell 7 collector и mock-based regression suite. В этой задаче не выполнялись ADB-команды, подключение к Pico, запуск camera/PVR services, SteamVR или tracking pipeline. Настоящих runtime observations нет; R1 остаётся `UNKNOWN/BLOCKED`.

Инструментальный контракт описывает только действие `read-only-inventory`. Approval не создан, аппаратное выполнение не одобрено. `-DryRun`/`--dry-run` не читает approval, не создаёт evidence и не вызывает ADB executor.

## Файлы

- [`collect_p3a6_inventory.ps1`](../tools/collect_p3a6_inventory.ps1) — CLI для Windows PowerShell 7; без ADB-операций внутри самого сценария dry-run.
- [`P3A6Inventory.psm1`](../tools/P3A6Inventory.psm1) — collector, native executor, ограниченный allowlist команд и приватная упаковка evidence.
- [`p3a6_execution_gate_cli.py`](../tools/p3a6_execution_gate_cli.py) — stdin-only bridge, вызывающий существующий [`p3a6_execution_gate.py`](../tools/p3a6_execution_gate.py). Логика и критерии gate не менялись.
- [`p3a6_inventory_collector.tests.ps1`](../tests/p3a6_inventory_collector.tests.ps1) — 18 PowerShell сценариев с injected mock ADB executor.
- [`test_p3a6_inventory_collector.py`](../tests/test_p3a6_inventory_collector.py) — запускает collector harness через PowerShell 7 и отдельно проверяет CLI dry-run.

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

Сценарий запросит интерактивную строку `P3-A6 APPROVE <approval_id> read-only-inventory`. Она снижает риск случайного запуска, но сама по себе не удостоверяет личность и не заменяет отдельную прямую инструкцию владельца. Gate повторно запускается **перед каждой ADB-командой**; проверяются scope, срок, лимит времени, количество команд и лимит записей.

Коллектор не вызывает `adb devices` и не запрашивает serial. Сначала он выполняет только `adb get-state` (или `adb -t <id> get-state`, если явно указан `-TransportId`). Без выбранного transport неоднозначность нескольких устройств должна быть отклонена самим ADB; при nonzero результате collector классифицирует `more than one device` как `BLOCKED_MULTIPLE_DEVICES`, не записывает raw stderr и не запускает shell-команды. При выбранном transport точное состояние должно быть единственной строкой `device`. Transport ID используется только для вызовов текущего процесса и не сохраняется в evidence. Модель из `ro.product.model` — защитная проверка против ошибки выбора, а не криптографическая аттестация Pico; владелец должен заранее выбрать/подтвердить правильный ADB transport. Если локальная версия ADB не сообщает неоднозначность через `get-state`, это ограничение будет видно как blocked/error, а не как успешный пустой inventory.

Успешное завершение возвращает exit code `0`; partial — `5`; blocked/error — `4`. Timeout, ADB error, неоднозначный/unready transport, не Pico 4 Pro, permission denial, исчерпание лимита или unsupported output не превращаются в пустой `COMPLETE`.

## Разрешённые наблюдения и методы

| Поле | Метод | Сохранённые значения |
|---|---|---|
| Product check | `adb -t <transport> shell getprop ro.product.model` | Только нормализованное `Pico 4 Pro`; неожиданное значение отбрасывается и останавливает run |
| Build fingerprint | `adb -t <transport> shell getprop ro.build.fingerprint` | Строка, прошедшая строгую character/length allowlist |
| Android release | `adb -t <transport> shell getprop ro.build.version.release` | Строка версии |
| Kernel release | `adb -t <transport> shell uname -r` | Строка версии |
| QuickCamera/PVR processes | `ps -A -o PID,NAME`; статус завершения проверяется до фильтра `quickcamera|pvr` на target; не читаются args/cmdline | Только соответствующие process name и PID; ошибка/пустой вывод — `UNAVAILABLE` и останов |
| Open video descriptors | Для найденных PID читаются symlinks `/proc/<pid>/fd/*`; принимаются только `/dev/video[0-9]+` | PID, имя процесса, fd number и node path |
| fdinfo | Для найденного camera fd читаются `/proc/<pid>/fdinfo/<fd>` | Только allowlisted `pos`, `flags`, `mnt_id`, `ino`; flags допускаются в hex или Linux octal формате |

Процессы только перечисляются. Collector не запускает Camera2/PVR session, сервис или pipeline. При отказе доступа к `/proc`/fdinfo он сохраняет уже полученные allowlisted записи, ставит partial status и прекращает дальнейшие device commands; access failure может быть вызван SELinux либо обычными Unix permissions, и collector не пытается различать их через audit logs. Нет root, `su`, remount, install/push, reboot, hooks, process-memory reads, `dumpsys`, `logcat` или debug logging.

Native executor принимает только точные inventory command shapes и собранный из безопасного PID allowlisted probe; остальные аргументы, включая `adb root`, отклоняются до запуска процесса. `adb get-state` не запрашивает список устройств и serial. Если ADB возвращает serial в тексте ошибки при неоднозначности, raw stderr используется только transiently для классификации и отбрасывается; он не включается в console result, archive, marker, exception или test report. Явно заданный числовой transport ID также не сохраняется.

`ps -A -o PID,NAME`, `awk`, `readlink`, `getprop` и procfs доступность конкретной PICO OS заранее не доказаны. Ошибка `ps` или пустой ответ фиксируется как `UNAVAILABLE`, не как успешная инвентаризация с нулём процессов. Если команда отсутствует/запрещена, соответствующее поле фиксируется как unavailable/permission denied и run завершается без fallback к более широкому сбору.

## Права и условия будущего сеанса

- На Windows нужны PowerShell 7, Python с доступным из PATH модулем `pico.tools.p3a6_execution_gate_cli`, одна однозначная копия `adb.exe` в PATH, доступ к `LOCALAPPDATA` и возможность задать private DACL на новую run-папку. Collector не запрашивает elevation; если ACL создать нельзя, он блокирует запуск до ADB.
- На Pico владелец должен заранее включить и авторизовать обычный USB debugging/ADB shell, выбрать правильное устройство и разрешить только действие `read-only-inventory`. Root, `su` и обход SELinux не нужны и не запрашиваются. Отказ в `/proc` или fdinfo останавливает сбор и сохраняется как partial evidence.
- Первый вызов `adb.exe` может запустить стандартный host-side ADB server, если его ещё нет. Collector не устанавливает и не меняет Pico-службы; выполнение shell-команд начинается только после approval gate и проверки модели. Если запуск host ADB server сам по себе запрещён политикой владельца, ADB должен быть заранее поднят отдельно и этот режим отдельно одобрен.
- Устройство должно вернуть `Pico 4 Pro` через `ro.product.model`; это проверка выбора, не криптографическая идентификация/attestation. При неоднозначном `adb get-state` collection завершается до shell-команд; collector не перечисляет serial для выбора устройства.

## Private evidence package

По умолчанию пакет пишется в `$env:LOCALAPPDATA\PicoLHSync\private-evidence\<run-id>`. Разрешён только путь под `LOCALAPPDATA`, вне repository; проверяются reparse points. Для уникальной run directory задаётся защищённый DACL с доступом текущему владельцу и SYSTEM, без наследования. Если путь или ACL не удаётся закрепить, ADB не запускается.

Папка содержит:

- `evidence.zip` с единственным `evidence.json`;
- `final.marker.json`, созданный последним и содержащий SHA-256 архива.

Evidence фиксирует schema/run/approval/action, UTC start/end, elapsed time, эффективные caps, per-field status/value/method/time/build identity, выбранные process/PID/video fd/fdinfo, access limitations, PowerShell/tool source SHA-256, count consistency и privacy flags. Пустые или не прочитанные поля остаются `NOT_OBSERVED`, `PERMISSION_DENIED` или `UNAVAILABLE`; raw stderr и необработанный ADB output не сохраняются. В evidence всегда остаются `false`:

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

## Mock-тесты

`python -m unittest pico.tests.test_p3a6_inventory_collector -v` запускает настоящий PowerShell collector с mock responses и проверяет:

- отсутствующее/неверное/expired approval и expiry между командами;
- action scope escape, wrong runtime model и несколько устройств;
- timeout/partial output, ADB error, duration/record limits;
- `/proc`/fdinfo permission denial с прекращением последующих device commands, исчезнувший PID, ошибка `ps` и allowlisted fdinfo;
- нулевой executor call для dry-run и запрет `adb root` native allowlist;
- отсутствие serial/personal-looking данных в archive, неизменные false gates, ACL, ZIP SHA-256/final marker.

Все выше — offline synthetic/mock results; тесты не запускают `adb.exe` и не создают experimental PASS.
