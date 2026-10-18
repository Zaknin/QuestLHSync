# P3-A4 — QuickCamera timestamp provenance handover

Состояние на 2026-10-18. Работа выполнена в `C:\Dev\PicoLHSync`, branch `feature/pico-support`; исходная база была чистой на `def417f588e296e03268c84082248132397d55a3`.

## Вердикт

Статически доказаны ABI и порядок передачи `CSL producer → native handle/ID arrays → HIDL handles/IDs → PVR mmap/buf_info`, а также PVR userspace-путь от ID к `QBUF userptr`, затем из `DQBUF` к lookup key и metadata pointer в `FrameMetaDate`. Участок kernel roundtrip `QBUF userptr → DQBUF userptr` остаётся **PARTIAL**: поведение драйвера/ядра не исследовано, поэтому равенство возвращённого ключа переданному ID не доказано. Внутренний contract импортированного Qualcomm `CSLAlloc` отсутствует, поэтому тождество backing pages producer CPU pointer и PVR mapped FD тоже не доказано. Называть весь shared-memory bridge проверенным нельзя.

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

1. [P3-A4-Proof-Matrix.md](P3-A4-Proof-Matrix.md) — что подтверждено, опровергнуто и неизвестно.
2. [P3-A4-Full-Buffer-Provenance.md](P3-A4-Full-Buffer-Provenance.md) — ABI, инструкция-за-инструкцией buffer/ID/offset path.
3. [P3-A4-Timestamp-Semantics.md](P3-A4-Timestamp-Semantics.md) — ring, request IDs, fence wait, fallback и clock limitations.
4. [P3-A4-Worklog-20261018.md](P3-A4-Worklog-20261018.md) — ход работ, проверка артефактов и тесты.

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
- `pico/tools/p3a4e_resolve_callback_relocations.py` — требует явный приватный output root и блокирует пути внутрь репозитория.
- `pico/tools/p3a4_provenance_model.py` и `pico/tests/test_p3a4_provenance_model.py` — pure-Python ABI/dataflow contract model, без ELF/runtime доступа.
- Четыре отчёта выше, execution plan и worklog.

Полная команда `python -m unittest discover -s pico/tests`: **176 tests, OK**. Тесты выполнялись офлайн; subprocess проверяют PowerShell parser и fail-closed output-root guards, включая временный junction; ADB/device вызовов не было.

## Что делать дальше

1. Поискать доступный Qualcomm CSLAlloc API/source contract, который определяет отношение CPU pointer и exported handle FD. Без него не закрывать backing-store identity gate.
2. При необходимости дополнить статическое описание внутренних `buf_info+0x00..+0x17` полей; они не блокируют текущий pointer/offset вывод.
3. Физическая Pico-проверка timestamp semantics/fallback/clock relationship требует отдельного пользовательского разрешения и отдельного безопасного протокола из Timestamp Semantics. В этом исследовании ничего на Pico не запускалось.
4. Pose, camera-to-factory coordinates, Lighthouse synchronization и активная коррекция остаются отдельными будущими задачами с закрытыми gates.

Следующий инженер должен начать с матрицы доказательств, сверить SHA локальных приватных ELF перед новым анализом и не переиспользовать ни одно из этих значений как runtime acceptance.
