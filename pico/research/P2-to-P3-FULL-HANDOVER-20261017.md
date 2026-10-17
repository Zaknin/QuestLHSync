# PicoLHSync / QuestLHSync — HANDOVER P2 → P3 (17 октября 2026)

**Проект:** Pico4 Stuff; новый диалог в этом же ChatGPT-проекте. **Репозиторий:** `Zaknin/QuestLHSync`, ветка `feature/pico-support`, локально `C:\Dev\PicoLHSync` на Windows 11 (PowerShell 7.6.6). **Оборудование:** rooted Pico 4 Pro, PICO OS 5.11.2 / Android 10; Pico на момент передачи выключена, Pimax Crystal и SteamVR доступны для Windows-side экспериментов.

> **Правило проекта: OBSERVE ONLY, exact_time=false, live_lighthouse_correction_allowed=false.** Не менять vendor QuickCamera/SLAM, прошивку, работающий SteamVR-драйвер, F timestamps или calibration gates без независимого доказательства. Не загружать в Git приватные ELF, CSV, заводские коэффициенты. **Backend P1 экспериментальный и не является usable live tracking-correction release.**

## 1. Цель новой фазы

Цель проекта — качественный Lighthouse Sync для Pico 4 Pro через настоящие K0 camera observations, без вмешательства в штатный SLAM, с корректной физической геометрией и доказанной временной привязкой.

**P2 изучил native timestamp computation и конфигурационные пары. Этот подэтап закрыт на уровне доступных статических данных.** В P3 требуется:

1. **P3-A / Producer:** отследить истинный создатель первого `QuickCamera FrameMetaDate` timestamp, аппаратный clock и физический момент камеры.
2. **P3-B / Host:** спроектировать пассивный Windows **QPC + OpenVR/SteamVR pose diagnostic**. Это можно делать с Pimax при выключенной Pico; такая проба сама по себе НЕ калибрует часы Pico.
3. **P3-C / Integrate later:** независимо измерить Pico↔PC clock offset/rate/uncertainty, физический exposure event, factory camera mapping, optics and HeadFromBody; протестировать в offline shadow replay; только после всех gates обсуждать live correction.

**Первое действие нового диалога:** проверить HEAD и код репозитория, затем начать **read-only host OpenVR/QPC probe** (тесты до реальной пробы на Pimax). Не возобновлять серийные тесты подбора A/B на 2.376 мкс.

## 2. P1: уже работающий backend (не ломать)

```text
pvr.ITrackingService (Binder transaction 19; kind=0)
  -> K0 ashmem rings C0,C3,C4,C5
  -> pico/src/PicoFrameReader.java (app_process, read-only)
  -> PFR1 binary, 40-B big-endian header + 307200 RAW8 pixels
  -> pico/src/lhsight_pico.c
       reused magisk/src/lhsight.c::smean(), blobs()
  -> upstream network F/T
  -> src/headset/lhsyncd.c original discovery UDP 47281,
     TCP 47280 and P/Q clock sync
  -> QuestLHSync/SteamVR driver (correction currently BLOCKED)
```

Pico-specific `pico.c` implements headset API, starts reader on TCP demand; reader terminates after disconnect. Кадры 640×480 RAW8, пять слотов по 308026 байт; ring header 20 байт; пиксели `slot+186`, sequence `slot+146`; odd означает complete; newest possibly in-flight slot reader пропускает. **Camera IDs 0/3/4/5, около 25 FPS**, никогда не запрашивать ID >=7 (некорректная проверка границ прошивки), только `kind=0`.

14 октября P1 **физически получил 1969 F кадров за 20 секунд** и 20 T heartbeat. Споты видны, но не подтверждены как станции Lighthouse. **F по-прежнему использует `copied_ns/1000`, НЕ vendor timestamp.** `hs_calibration` намеренно возвращает error, solver не применяет F в трекинг. `Optics::LoadPico` fail-closed при `mapping_verified=false`, `pose_verified=false`, `HeadFromBody=null`.

Factory calibration: приватный архив из 13 файлов, четыре tracking-сенсора имеют модель **Omni+Radtan 640×480**; `T_BS` есть body←camera, НЕ автоматически SteamVR HMD←camera. Предварительное соответствие C0→factory cam0, C3→cam1, C4→cam2, C5→cam3 **всё ещё кандидат**, не vendor-validated. Не устанавливать флаги готовности.

## 3. Приватные доказательства, которые уже есть локально

```text
C:\Dev\PicoLHSync\pico\build\qtimer-p2-private-20261016-204644\
  k0.csv; slot130-audit.json; slot130-variation.json; paired PVR clock evidence...

C:\Dev\PicoLHSync\pico\build\p2-static-clock-private-20261016-205431\
  libpvrtrackingcamera.so; libpvrtrackingservice.so;
  p2-q1-timing-coefficients.json; p2-alternate-timing-literals.json;
  p2-k0-timestamp-literal-references.json;
  01-ConfigManager-getInstance-q2.txt; 02-ConfigManager-ctor-q2.txt;
  03-CameraManager-ctor-load.txt; 04-CameraManager-ctor-store.txt; etc.
```

**Pinned binary hashes:**

```text
libpvrtrackingcamera.so  cf9e507f412ec33d62c2f720669fcdd093f1822c9cbf3adefd0a26a6b4d072ee
libpvrtrackingservice.so 45194b15539875ea1ce01fb702d34773b708d248a3409d369877ac199849b8de
```

**Эти бинарники приватны.** Репозиторий содержит только код/скрипты и текстовые отчёты. Не выдумывать пути отсутствующих producer/HIDL .so; будущую инвентаризацию выполнять read-only, когда пользователь снова включит Pico.

## 4. P2 — доказанные native metadata/clock факты

Запись **1204 completed K0 frames** (301 для каждой C0/C3/C4/C5). `slot+114 == slot+122` на всех; `slot+130` ненулевой и в той же QTIMER-like эпохе, а не в epoch BOOTTIME.

```text
QuickCameraClient::DeQueueFrame(FrameMetaDate*)
    -> first 64-bit metadata word
    -> PvrCameraFrame::processCameraFrame @0x664e8
       duplicates word at @0x666a8 into frame_item+0x18,+0x20
    -> virtual listener call at @0x666e0 (device+0x30, vtable+0x10)
    -> CameraImageListener::onFrameAvailable @0xabbfc
       callback switch VA 0x73a10 bytes 00 07 0A 0D
       descriptor 0→manager camera C0, 1→C3, 2→C4, 3→C5
    -> CameraManager::onFrameAvailable @0xaa8f4
    -> frame_item+0x28 computed @0xaaeac
    -> CameraManager::writeToSm @0xaaef4
       main kind-0 ring slot+114/+122/+130
```

Listener ABI: `PvrCameraDevice::setPvrImageListener@0x65004` stores shared listener `device+0x30`; `PvrQuickCamera::setPvrImageListener@0x6397c` invokes device setter `@0x63a1c`. ELF relocation at `CameraImageListener` vtable slot `0x15e6b0` resolves to `onFrameAvailable@0xabbfc`. **Runtime association of this exact listener object with captured active cameras remains unverified**. Отдельный Android `AImageReader` timestamp path существует; не объявлять его источником K0 без доказательства.

**Точная формула native PVR:**

```text
T130 = T122 - 52000 - A - ((B * E) ASR 1)
A = int64[CameraManager_this + cameraID*0x320 + 0x338]
B = int64[CameraManager_this + cameraID*0x320 + 0x330]
E = int32[frame_item+0x14] = K0 slot+110 = 4 в записанных кадрах
```

**Реальные 1204/1204:** `T122 - T130 == 225997 ns`, unique delta 1, adjacent transitions 0 на каждой камере. `A_runtime+2*B_runtime=173997 ns` — условное следствие source formula для данной записи. E=4 — frame code/setting, **не подтверждённая длительность экспозиции**. T130 не сертифицирован midpoint.

Из ELF static source:

| Источник и назначение | B | A | Предсказание при E=4 |
|---|---:|---:|---:|
| `0x73170`: CameraManager constructor default → 7 camera blocks stride 0x320 | 19069 | 133483 | 223621 ns |
| `0x73160`: ConfigManager::getInstance/constructor → ConfigManager +0xA0 | 19333 | 135331 | **225997 ns** |

Реально есть два 16-byte literal pair. ConfigManager грузит альтернативный q2 в двух путях `@0xa24b0` и `@0xa25e4`, сохраняет `stp q1,q2` `@0xa24e8` и `@0xa2628` в `ConfigManager+0xA0`. **Не найдено доказанной передачи в CameraManager A/B.** Разница 2376 нс реальна, но активный профиль не доказан. Нет оснований продолжать именно этот поиск без новой информации.

QTIMER из PVR сравнивался с `CNTVCT_EL0` (~19.2 MHz) и были in-session shadow checks; получена QTIMER-like гипотеза для raw K0 и sample-dependent offset около +4.7465 секунд к BOOTTIME. **Не переносить offset через sleep/reboot и не выдавать PVR producer lag ~10 ms за physical exposure lag**. Физический origin `FrameMetaDate.first_u64` остаётся unknown.

## 5. Проверки и уровень уверенности

На пользовательском Windows все последние suite выполнились успешно: 19/19 shadow/slot130, 5/5 variation, 6/6 затем 7/7 listener, 13/13 dispatch, 12/12 constructor, 15/15 q1, 15/15 alternate constants, 14/14 reference xref, 14/14 final ConfigManager assembly. **Synthetic PASS ≠ native hardware calibration.**

Ключевые файлы:
- [Подробный P2 source report](P2-K0-SourceAndSlot130-20261016.md)
- [P2 closeout / P3 gating](P2-Closeout-P3-Clock-Provenance-20261017.md)
- [Pico README](../README.md)
- `pico/tools/trace_k0_timestamp_producers.ps1`, `audit_k0_callback_dependencies.ps1`
- `pico/tools/audit_k0_slot130_variation.py`, `trace_k0_slot130_parameters.ps1`
- `pico/tools/audit_k0_q1_coefficients.py`, `audit_k0_alternate_constants.py`
- `pico/tools/audit_k0_literal_references.py`, `trace_k0_configmanager_q2.ps1`
- `pico/tools/audit_qtimer_bridge.py` и shadow QTIMER model.

**Не просить пользователя снова выполнять идентичные P2 capture/disassembly test cycles.**

## 6. Жёсткие gates P3

| Gate | Чего не хватает | Как проверять |
|---|---|---|
| P3-A1 | Hardware producer `FrameMetaDate.first_u64` | Real PICO QuickCamera HIDL/vendor producer implementation same OS version; source tracing или независимое timing measurement |
| P3-A2 | Событие SOF/exposure/readout/rolling shutter | Hardware/source event proof и контролируемый optical marker |
| P3-A3 | Активный listener и реальный коэффициентный профиль | Source-level ctor/registration/dataflow либо безопасные controlled observations |
| P3-B1 | Host clock и семантика SteamVR pose API | Passive QPC-bracketed OpenVR sampling, mocks, local private reports |
| P3-B2 | Pico QTIMER ↔ Windows QPC rate/epoch | Simultaneous paired timing with transport asymmetry/uncertainty, repeated restart/sleep/session tests |
| P3-C | Factory camera mapping, axes, HMD HeadFromBody и independent optic fit | Factory metadata, controlled optical station tests, holdout/replay |
| LIVE | Полная корректная геометрия, физическое время, отказоустойчивость | Все gates PASS, отдельные сессии, replay first, не по умолчанию |

**Запрещённые сокращения:** не считать `slot130` midpoint; не считать `E=4` милли/микросекундами; не считать `GetDeviceToAbsoluteTrackingPose(prediction=0)` hardware sampling timestamp; не назначать заводской T_BS за HeadFromBody; не применять простой ping midpoint без uncertainty.

## 7. Конкретная следующая работа: Windows + Pimax (Pico OFF)

**Первый engineering deliverable:** минимальный **read-only OpenVR + QPC probe** внутри репозитория. Сперва проверить актуальную официальную OpenVR документацию и существующий код; не выбирать неизвестные версии API из памяти.

**Sampling design:**
1. QPC tick **before** `IVRSystem::GetDeviceToAbsoluteTrackingPose(origin,0,...)`, QPC tick **after** и QPC frequency (целые ticks, без float rounding).
2. Сохранять device index, connected, valid, tracking origin/result, prediction request, pose matrix 3×4, velocities, QPC bracket, schema/version, error states.
3. Точно объяснять семантику: prediction=0 — query pose на caller time, не sensor acquisition timestamp. Bracket midpoint — лишь оценка времени *вызова API*, с неполной uncertainty; не использовать за физическую временную метку.
4. Разработать mock tests для monotonic/brackets, invalid/disconnected, corrupt sample, clean shutdown, no-live-write, и только затем **опциональный** реальный Windows/Pimax run.
5. Отчёт — QPC API latency distribution + корректные ограничения, а не выдуманный Pico camera offset.
6. Ни SDK, ни probe не должны inject/update SteamVR poses, регистрировать виртуальный HMD/driver, писать в `src/driver` или включать tracking calibration.

После host-only стадии пользователь может включить Pico. Тогда минимум read-only `adb shell` inventory фактически установленных QuickCamera/HIDL producer .so (без угадывания paths), приватное копирование подходящих vendor files и offline static tracing. Только потом cross-machine time model.

## 8. Рекомендованный workflow следующего диалога

- Работать на русском, технически точно, без повторных вводных опросов и без переписывания уже известных фактов.
- Сначала прочитать **этот** документ, два source-reports и код; определить текущий **HEAD** (не считать commit `6ca39fd` последним после публикации handover).
- Если в следующем чате есть подключённый GitHub — делать соответствующие точечные коммиты сразу в `feature/pico-support`, затем read-back. Не ждать от пользователя ручной копипасты больших скриптов.
- Минимальный план → mock/testable code → отчёт → одна короткая команда PowerShell 7 для клиента. Отдельно отмечать: исходник создан / source reviewed / tests synthetic PASS / Windows user PASS / physical gate PASS.
- **Pico выключена**, пока пользователь не скажет обратного; Pimax доступен. Не требовать девайс ради чисто offline анализа.
- Приватные доказательства не коммитить. Не путать производственную совместимость с read-only стендом. Не трогать P1 транспорт без подтверждённой необходимости.

**Финальный инвариант:** `OBSERVE ONLY`, `exact_time=false`, `live_lighthouse_correction_allowed=false`, `mapping_verified=false`, `pose_verified=false` пока не выполнены физические и временные gates.
