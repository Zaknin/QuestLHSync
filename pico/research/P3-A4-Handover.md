# P3-A6-M0 — QuickCamera timestamp provenance handover

## Current update — P3-A6-M2 (2026-10-19)

M2 node-metadata implementation is prepared offline in a dedicated PowerShell 7 runner. See [`P3-A6-M2-Handover.md`](P3-A6-M2-Handover.md), the updated [acceptance matrix](P3-A6-Acceptance-Matrix.md), [risk/permissions](P3-A6-Risk-and-Permissions.md), and [proposal](P3-A6-M2-Read-Only-Camera-Metadata-Proposal.md). The separate action is `read-only-camera-node-metadata`, hard limits 30 s/40 observations/16 candidates per source, and it requires interactive exact lowercase `yes` after a fresh approval. It only lists fixed sysfs attributes and `/dev/videoN` metadata; it does not open devices or establish VideoQueueUtil ownership, ioctl attribution, frame delivery, SOF or exposure timing. The M1.5 owner-reported result remains `PARTIAL_PERMISSION_DENIED`. M2 has not run on Pico; no ADB, approval record, camera service, `/proc`, root, SteamVR or Lighthouse was used in this preparation.

Текущее состояние на 2026-10-18: подготовлена offline-фаза runtime validation в `C:\Dev\PicoLHSync`, branch `feature/pico-support`, от исходного HEAD `97977e868ac5d0a3e743d6323266db2b666a6a06`. Pico, ADB, SSH, SteamVR и Lighthouse correction не запускались. В репозитории есть только synthetic analyzer и authorization checker; device-facing collector отсутствует.

P3-A5 выводы ниже без изменений: `/dev/videoN` для конкретного `VideoQueueUtil` остаётся `UNKNOWN`; QBUF/DQBUF kernel roundtrip — `PARTIAL/BLOCKED`; CSLAlloc producer CPU VA ↔ PVR FD backing identity — `UNKNOWN/BLOCKED`; QTIMER event, units и физическое SOF/exposure не доказаны.

## Текущие P3-A6-M0 материалы

1. [P3-A6-Runtime-Validation-Plan.md](P3-A6-Runtime-Validation-Plan.md) — этапы M1–M5, минимальные измерения, clock model и условия отдельного hardware execution approval.
2. [P3-A6-Risk-and-Permissions.md](P3-A6-Risk-and-Permissions.md) — права, Android/PICO доступность, timing/privacy/resource risks и stop conditions.
3. [P3-A6-Acceptance-Matrix.md](P3-A6-Acceptance-Matrix.md) — разделение synthetic pass и будущего runtime acceptance; текущие gates false.
4. [`p3a6_observation_analyzer.py`](../tools/p3a6_observation_analyzer.py) и [`p3a6_execution_gate.py`](../tools/p3a6_execution_gate.py) — offline-only tool modules; ни один не обращается к устройству.
5. [`P3-A6-synthetic-observations.json`](../tests/fixtures/P3-A6-synthetic-observations.json) и [`test_p3a6_runtime_analyzer.py`](../tests/test_p3a6_runtime_analyzer.py) — synthetic fixture и регрессии.

Проверено offline: целевой `python -m unittest pico.tests.test_p3a6_runtime_analyzer -v` — 19 тестов; полный `python -m unittest discover -s pico/tests -v` — 196 тестов, OK. CLI обработал только synthetic fixture; report вернул `experimental_verdict=NOT_RUN`, а все gates остались false. Это не hardware result.

Для следующей hardware-фазы требуется отдельная прямая инструкция владельца с точным набором действий, лимитом времени/наблюдений и разрешённым уровнем доступа. Inventory approval не распространяется на ptrace, process-memory reads или kernel tracing. Сейчас разрешения нет; ни один device-facing шаг не запускать.

Статусы P3-A4/P3-A5 в proof matrix не повышены. Дополнение зафиксировано в конце [P3-A4-Proof-Matrix.md](P3-A4-Proof-Matrix.md).

Состояние на 2026-10-18. Работа выполнена в `C:\Dev\PicoLHSync`, branch `feature/pico-support`, начиная с чистого `e3f04c53b5fa0a71704d40303011b30042af209e`.

## P3-A5: source-audit verdict (без изменения)

P3-A5 уточнила два внешних contract gaps. Локальный ELF provider/source, соответствующий PICO `CSLAlloc`, не найден; публичный CamX source mirror показывает только аналогичную реализацию и не привязан к PICO build. Поэтому producer CPU pointer ↔ exported FD backing identity остаётся **UNKNOWN/BLOCKED**.

Для очереди найден `VideoQueueUtil::CSLHwInternalDefaultIoctl2` (`0x6c2f8..0x6c3d8`): он заворачивает внутренние `0xc058560f/0xc0585611` и payload pointer во внешний `ioctl(fd,0xc01856c0,&envelope)`. Userspace не переписывает поле `m.userptr`, но kernel dispatcher/copy-back handler недоступен. Успешный DQBUF использует полученное поле как tree key, однако равенство исходному ID не доказано. Node, открытый конкретным `VideoQueueUtil`, также **UNKNOWN**.

В matching producer ELF подтверждён вызов `CSLBufferCacheOp(handle,1,0)` на пути `StreamOn`; cache-op kernel effect и общая coherency guarantee не установлены. Shared-memory bridge целиком проверенным не считать.

Timestamp dataflow до frame item прослежен. QTIMER label и fallback branch подтверждены в коде, но физический смысл времени и runtime частота fallback неизвестны. Clock domains, pose и Lighthouse mapping не проверялись.

Текущие gates (не менялись):

```text
observe_only=true
exact_time=false
live_lighthouse_correction_allowed=false
mapping_verified=false
pose_verified=false
frame_meta_bridge_verified=false
physical_event_verified=false
shared_buffer_identity_verified=false
```

## Чтение по порядку

1. [P3-A5-Allocator-and-Queue-Contract-Audit.md](P3-A5-Allocator-and-Queue-Contract-Audit.md) — финальный offline статус allocator, ioctl2 boundary, node и cache contract.
2. [P3-A4-Proof-Matrix.md](P3-A4-Proof-Matrix.md) — сводная таблица доказательств с уточнёнными статусами и M0 note.
3. [P3-A4-Full-Buffer-Provenance.md](P3-A4-Full-Buffer-Provenance.md) — ABI и userspace buffer/ID/offset path с пояснением wrapper.
4. [P3-A4-Timestamp-Semantics.md](P3-A4-Timestamp-Semantics.md) — ring, request IDs, fence wait, fallback и clock limitations.
5. [P3-A4-Worklog-20261018.md](P3-A4-Worklog-20261018.md) — исторический ход работ и первоначальный тестовый результат A4.

Эти документы уточняют исторические статусы в `P3-A4-HIDL-PVR-Bridge-20261017.md` и `P3-A4E-PVR-Callback-Relocations-20261018.md`; прежние отчёты сохраняются как evidence, полученное на соответствующем этапе.

## Зафиксированные исходники

| Файл | SHA-256 |
|---|---|
| PVR `libpvrtrackingcamera.so` | `cf9e507f412ec33d62c2f720669fcdd093f1822c9cbf3adefd0a26a6b4d072ee` |
| producer `quickcamera.core.so` | `fb22355acd35b9772a5538a7d1c49175641165ad0368e7c47e5831f5f1727017` |
| HIDL impl `pico.camera.quickcamera.quickcameramodule@1.0-impl.so` | `c3157e66d842dcdca148f1b98328bd5e7ce80c4ab9bbbacba895465556314f47` |

Ни один ELF не добавлялся в Git или приватные trace ZIP. В trace ZIP входят manifest и ограниченные disassembly excerpts.

## Приватные evidence packages

Приватное хранилище: каталог P3-A, destination задаётся локально настроенным output root трассировщика. В публичные производные отчёты адрес хранилища и внутренние network identities не включаются.

### Основная трасса

- `p3a4-bridge-20261018T115554Z-9513a95d.zip` — SHA-256 `a01dc01470ba263ca48118e02b54ba82af27dfdd6f7a2c17438ffaed5416993f`
- `p3a4-bridge-20261018T115554Z-9513a95d.json` — SHA-256 `824e9f03c273b5dc28902e71509def2916cde86b7a40c0cf5411d9a1e3b1afb1`
- `p3a4-bridge-20261018T115554Z-9513a95d.sha256` — SHA-256 marker file digest `d10643396681dbf19f13b84eb142864961e2db767c7c4971fa35dd3882d750d0`
- Статус `TRACE_CAPTURED_NOT_PROVEN`; 20 bounded windows, 10 exact PVR targets и 38 PVR symbol hits. Manifest включает diagnostic `CSLTimestampTypeQtimer frameMessage...`; строка является только diagnostic label, не доказательством физического SOF/exposure. SMB readback hashes ZIP/JSON совпали с marker.

### Android RELR callback resolution

- `p3a4e-reloc-20261018T115559Z-6e7e74aa.zip` — SHA-256 `a6b4bb5c52b8a7954b0ae0d1a5b527b077e5da40c59bf0ff351936e506421a01`
- `p3a4e-reloc-20261018T115559Z-6e7e74aa.json` — SHA-256 `f6325d6b01eee06c88283a97726d3a02de8431931ce43dad702bf4d0bdd6775d`
- `p3a4e-reloc-20261018T115559Z-6e7e74aa.sha256` — SHA-256 marker file digest `40dd2064f3782ebb861f2e9abeea755def28d71597ad25513d8841c36a02aedf`
- Статус `CANDIDATES_CAPTURED_NOT_PROVEN`; 12/12 slots decoded, 8 executable excerpts. Slot `0x75300` содержит `0x6c864` из `SHT_ANDROID_RELR`.
- В JSON и ZIP gates остаются false. Пакет построен на manifest основной трассы выше; marker и все хэши независимо прочитаны после публикации и совпали.

## Изменённые файлы и тесты

- `pico/tools/trace_p3a4_quickcamera_bridge.ps1` — расширены безопасные pinned disassembly windows; бинарники только читаются. Приватный output root задаётся через `P3_A_OUTPUT_ROOT` или `-OutputRoot`, запись внутрь Git repository и через reparse point блокируется.
- `pico/tests/test_p3a4_bridge_contract.py` — проверяет windows, fail-closed gates, PowerShell parsing и output-root guard.
- P3-A5 добавил `CSLHwInternalDefaultIoctl2` exact-symbol window и schema v4 в private trace; `pico/tests/test_p3a5_ioctl2_trace.py` запускает tracer с временным output root и проверяет symbol extent. Тест удаляет созданный им private build folder.
- `pico/research/P3-A5-Allocator-and-Queue-Contract-Audit.md` — найденный публичный analogue, exact ioctl envelope, unresolved kernel/node/backing-store вопросы и следующие точные входы.
- `pico/research/P3-A4-Proof-Matrix.md` и `P3-A4-Full-Buffer-Provenance.md` — исправлены формулировки kernel boundary и добавлен cache-op callsite.
- `pico/tools/p3a4e_resolve_callback_relocations.py` — требует явный приватный output root и блокирует пути внутрь репозитория.
- `pico/tools/p3a4_provenance_model.py` и `pico/tests/test_p3a4_provenance_model.py` — pure-Python ABI/dataflow contract model, без ELF/runtime доступа.
- Четыре отчёта выше, execution plan и worklog.

Полная команда `python -m unittest discover -s pico/tests -v`: A4 — 176 tests, OK; P3-A5 — **177 tests, OK**. Новый regression запускает только локальный ELF extractor с temp output root и очищает созданный им private build folder. `git diff --check` завершился с code 0; были только Git LF→CRLF warnings. ADB/device вызовов нет.

## Ранее установленное и следующий шаг

1. Offline search по локальным материалам останавливается здесь: требуемый CSL provider/kernel handler не найден. Продолжать только если появится source drop/ELF с build ID и доказанной привязкой к указанному PICO fingerprint.
2. Если exact sources отсутствуют, queue-ID return, действительный node, producer/PVR backing identity и cache behavior потребуют отдельной аппаратной проверки с отдельным протоколом. P3-A6-M0 подготовил этот протокол, но устройство не использовалось.
3. Timestamp физическое событие, clock domains, pose, camera-to-factory coordinates, Lighthouse synchronization и активная коррекция остаются отдельными будущими задачами с закрытыми gates.

Следующий инженер должен начать с P3-A6 execution gate и матрицы доказательств, получить отдельное разрешение владельца до первого подключения и не переиспользовать ни одно статическое или synthetic значение как runtime acceptance.
