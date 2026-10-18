# P3-A6-M0 — Runtime Validation Plan

Дата: 2026-10-18. Репозиторий `C:\Dev\PicoLHSync`, branch `feature/pico-support`, исходный HEAD `97977e868ac5d0a3e743d6323266db2b666a6a06`.

## Статус M0

**OFFLINE PREPARATION READY; HARDWARE NOT RUN.** В этой фазе не было обращения к Pico, ADB, SSH, SteamVR или Lighthouse correction. Подготовлены offline-анализатор синтетических наблюдений, fixture, fail-closed authorization checker и три документа P3-A6. P3-A6-M1 добавил Windows PowerShell 7 read-only inventory collector с mock executor; он не запускался на устройстве. Аппаратное выполнение остаётся закрыто до отдельного прямого разрешения владельца.

P3-A5 остаётся источником статических результатов. Этот план не повышает hardware/runtime статусы и не меняет proof gates.

| Контракт из P3-A5 / P3-A4 matrix | Исходный статус | Что нужно для следующей проверки |
|---|---|---|
| Node, связанный с `VideoQueueUtil` ioctl fd | `UNKNOWN` | Связать наблюдаемый outer `ioctl(fd,0xc01856c0,...)` с `/proc/<pid>/fd/<fd>`; process inventory сам по себе показывает только кандидаты |
| QBUF ID → DQBUF lookup key | `PARTIAL`; kernel handler `BLOCKED` | Сравнить QBUF `m.userptr` raw u64, DQBUF raw u64 и low-u32 key, фактически используемый userspace; наблюдать payload на границах ioctl |
| Producer CPU mapping ↔ PVR FD backing allocation | `UNKNOWN / BLOCKED` | Сопоставить оба mapping/FD с одним kernel-exported allocation identity; одинаковые размер, fd number или содержимое недостаточны |
| Request ID, QTIMER-labeled timestamp, metadata | Static source flow установлен; runtime значения не наблюдались | Сначала использовать уже существующие диагностические записи; поля без существующего экспорта требуют отдельного разрешения на read-only instrumentation |
| Fallback | Static branch возможен; runtime frequency неизвестна | Нужен явный branch marker либо доказанная связь timestamp-source request ID с текущим request ID; повторы timestamp сами по себе не доказывают fallback |
| Clock relation / физическое событие | `UNKNOWN` / `NOT PROVEN` | Сопоставить одни и те же request IDs, фиксировать clock source и QTIMER scale; физический SOF/exposure проверять отдельным внешним методом |

## Подготовленные offline средства

- [`pico/tools/p3a6_observation_analyzer.py`](../tools/p3a6_observation_analyzer.py) принимает только `p3a6.synthetic_observations.v1` с `dataset_kind="synthetic"`; неизвестные поля, реальные данные, файлы свыше 16 MiB и наборы свыше 10 000 записей отклоняются.
- [`pico/tools/p3a6_execution_gate.py`](../tools/p3a6_execution_gate.py) валидирует отдельное, точное, ограниченное по времени и объёму разрешение. Он не выполняет команд и не подключается к устройству. Подтверждение должно быть дано владельцем отдельно; текстовый токен — защита от случайного запуска, а не криптографическая проверка личности.
- [`pico/tools/collect_p3a6_inventory.ps1`](../tools/collect_p3a6_inventory.ps1) и [`pico/tools/P3A6Inventory.psm1`](../tools/P3A6Inventory.psm1) выполняют только одобренную M1 inventory; каждую ADB-команду предваряет общий Python gate. Контракт, приватное evidence и ограничения описаны в [`P3-A6-M1-Inventory-Collector.md`](P3-A6-M1-Inventory-Collector.md). Mock-тесты не являются runtime evidence.
- [`pico/tests/fixtures/P3-A6-synthetic-observations.json`](../tests/fixtures/P3-A6-synthetic-observations.json) демонстрирует sign-extended QBUF ID, DQBUF mismatch, sequence gap, повтор QTIMER value, fallback marker и синтетический +100 ppm пример.
- [`pico/tests/test_p3a6_runtime_analyzer.py`](../tests/test_p3a6_runtime_analyzer.py) проверяет только синтетические кейсы и gate.

Запуск fixture:

```powershell
python -m pico.tools.p3a6_observation_analyzer pico/tests/fixtures/P3-A6-synthetic-observations.json --output $env:TEMP/p3a6-synthetic-report.json
```

Результат маркируется `OFFLINE_SYNTHETIC_ONLY`, `experimental_verdict=NOT_RUN`; даже `SYNTHETIC_PASS` относится только к искусственным входным данным. Analyzer всегда сохраняет false: `exact_time`, `mapping_verified`, `pose_verified`, `shared_buffer_identity_verified`, `frame_meta_bridge_verified`, `physical_event_verified`, `live_lighthouse_correction_allowed`.

## Будущие этапы — только после отдельного разрешения

### M1 — Read-only системная инвентаризация

После отдельного одобрения владелец может запустить только read-only inventory: build fingerprint/версия ОС и kernel, имена/PID QuickCamera/PVR, открытые `/dev/video*` fds и доступные fdinfo. Collector не читает existing log tags; их snapshot относится к отдельному M2 action. Не запускать camera session ради инвентаризации. Если PVR не держит node в обычном состоянии, фиксировать `NOT_OBSERVED` и остановиться; не запускать pipeline автоматически.

Список `/proc/<pid>/fd` может показать несколько camera/request-manager nodes и сам по себе не связывает конкретный fd с объектом `VideoQueueUtil`. Точную связь даёт только уже существующий однозначный log либо отдельно одобренное наблюдение syscall: PID/TID, fd и outer request `0xc01856c0`, после чего fd сопоставляется с `/proc/<pid>/fd/<fd>`. В трассу syscall не включать память кадров.

### M2 — Passive observation уже существующего runtime

Снять только подходящие уже имеющиеся log records (например, связанные с известной строкой `CSLTimestampTypeQtimer`) и список доступных trace sources. Не включать verbose/debug logging, не запускать Perfetto/atrace/ftrace и не сохранять полный logcat. Сначала проверить, содержит ли существующий поток request ID, timestamp, явный fallback marker и allowlisted `FrameMetaDate` числовые поля. Если поля не экспортируются, обозначить их как `UNKNOWN`, а не извлекать предположениями.

Не записывать изображения/видео, frame pixels, пользовательский звук, аккаунты, serial, Wi-Fi identity или неотносящиеся к задаче логи. Сохранять только технические события по приватной схеме в `P3-A6-Risk-and-Permissions.md`.

### M3 — Отдельно разрешённая instrumentation, если M1/M2 недостаточно

Для queue contract на syscall boundary потребуются только `fd`, outer ioctl code, и 8-byte `m.userptr` поля до QBUF и после DQBUF. P3-A5 установила layout wrapper: 24-byte envelope, nested payload pointer, V4L2 buffer field offset `+0x40`; сам PVR wrapper payload не переписывает. Возможный read-only ptrace observer читает envelope/payload при входе и после возврата syscall, затем записывает low-u32 lookup key. Это останавливает/планирует процесс и может менять timing; применять только после отдельного согласования именно этого метода, root/ptrace доступности и лимитов. Kernel tracing — альтернативный, также отдельно разрешаемый вариант, только если соответствующий tracepoint/handler существует в этой прошивке. Не устанавливать agent, APK или service.

Для backing identity получать только FD/mapping identity метаданные: producer mapping address/length, связанные allocation FD, PVR FD/mapping и kernel-exported dma-buf/exporter/inode identity, если target kernel это предоставляет. Не читать buffer bytes. `/proc/<pid>/maps`, `map_files`, `fdinfo`, `DMA_BUF_IOCTL_INFO`, sysfs/debugfs и доступ к другим процессам могут быть недоступны или отличаться в PICO OS 5.11.2. Не использовать root как предпосылку и не обходить SELinux. При отсутствии общей идентичности результат `BLOCKED`, не content-probe.

Если согласован read-only memory observation для timestamp fields, считывать только известные `FrameMetaDate` поля/байты metadata region, не image region; указывать, что поле снято без подтверждённой синхронизации и могло обновляться одновременно. Не подменять callback, не писать в память и не менять camera pipeline.

### M4 — Offline обработка и сверка

Хранить экспериментальную сырую запись в приватном месте, затем вручную составить synthetic-compatible copy только если все наблюдения намеренно синтетические. Реальные runtime records текущий analyzer отвергнет. Для реальных результатов применять критерии acceptance matrix вручную либо реализовать отдельный анализатор после отдельной ревизии schema. Не выдавать synthetic-тесты за runtime PASS.

Queue correlation требует raw значения: QBUF `m.userptr` обязан быть sign-extended ID из 32-bit field; DQBUF сравнивается как raw u64 и отдельно по low-u32, который читает caller. Любое успешное dequeue с иным low-u32 — mismatch; лишь нулевой mismatch в ограниченной выборке подтверждает observed run, но не универсальную kernel guarantee.

Frame sequence gaps и повторы QTIMER выявляются отдельно. Sequence gap означает потерянное событие только если происхождение и монотонная семантика sequence field доказаны. Fallback frequency не выводить из одной статической ветки или повторов.

### M5 — Отдельная физическая временная проверка

Системное наблюдение может измерить время появления записи/кадра у observer. `QTIMER` label, log timestamp, host receive time и DQBUF arrival не доказывают sensor SOF или exposure start. Для физического события требуется version-matched описание timestamp semantics либо отдельный оптический reference experiment (например, синхронизированный LED/photodiode с измерительным прибором). Это отдельная hardware-задача и не входит в M0/M1.

## Clock/latency модель

Сохранять `qtimer_value` в raw units и точное происхождение Android clock. Не называть QTIMER значением в наносекундах, пока единицы и масштаб не подтверждены для конкретного build. `android_mono_before_ns`/`android_mono_after_ns` — скобка измерения на одном явно указанном Android clock; `observer_delivery_mono_ns` — время callback/delivery, только если оно уже экспортируется в том же clock domain. Не подставлять Windows/ADB host receive time как Android frame-delivery time.

Analyzer строит affine relation `QTIMER raw value → midpoint Android monotonic observation` и отдельно → observer delivery. Он сообщает bracket width, residual и scale. `drift_ppm` вычисляется только при независимом, проверенном `expected_qtimer_ns_per_unit`; иначе выводится `BLOCKED_NO_CALIBRATED_QTIMER_SCALE`. Wrap/reset или немонотонный input блокирует один общий fit. Само значение delivery минус timestamp — суммарное наблюдаемое смещение/задержка, включающее неизвестную event epoch, queueing и scheduling; это не точный возраст кадра.

Сравнивать `CLOCK_MONOTONIC` с `CLOCK_BOOTTIME` допустимо только как разные явно названные серии: не объединять их под общей меткой `Android monotonic`, а suspend/resume помечать как разрыв серии.

## Execution gate

Первый device-facing шаг запрещён до отдельного прямого разрешения владельца. Одна запись должна назвать Pico 4 Pro и **ровно одно** `approved_action`, UTC окно не длиннее 24 часов, `max_duration_seconds` (1–600), `max_observations` (1–10 000), необходимые права и stop conditions. Confirmation token формата `P3-A6 APPROVE <approval_id> <exact_action>` принимается только вместе с действительным approval record. Для ptrace/kernel tracing и чтения процесса нужна отдельная запись/инструкция; разрешение на инвентаризацию не распространяется на instrumentation.

Gate только валидирует record, он не запускает device action и не заменяет явное сообщение владельца. Сейчас approval record не существует и hardware phase не разрешена.

## Рекомендация

Offline preparation достаточно только для рассмотрения ограниченной **read-only inventory** сессии. Сначала нужно отдельное одобрение владельца на конкретную device session; отдельная passive-log задача требует отдельного scope. До такого одобрения Pico не подключать. Инвентаризация node не даёт ioctl attribution и не закрывает R1. Остальные контракты потребуют отдельной instrumentation/kernel evidence и kernel-exposed allocation identity; возможно, passive доступ этого не даст. Физический SOF/exposure требует независимого аппаратного reference и отдельной оценки.
