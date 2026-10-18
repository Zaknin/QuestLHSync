# P3-A4 — Proof matrix and corrected interpretations

Дата: 2026-10-18. Термин `STATIC PASS` означает только то, что указанные bytes/indices/branches связаны машинным кодом на SHA-pinned ELF. Он не означает runtime acceptance, физическую синхронизацию или возможность коррекции.

## Матрица утверждений

| Утверждение | Статус | Основные точки | Что именно подтверждено / граница |
|---|---|---|---|
| Входные ELF совпадают с ожидаемыми SHA | STATIC PASS | trace manifest `input_sha256` | Три зафиксированных источника; полный ELF не опубликован |
| Callback vtable slot выбирает `0x6c864` | STATIC PASS | callback object `0x6a3f0..0x6a408`; RELR `0x75300`; тело `0x6c864` | Slot разрешён из Android RELR, target executable и копирует ABI `QuickCameraBufInfo` в захваченный output |
| Allocator result задаёт producer ID, CPU pointer-use и handle FD-use | STATIC PASS, внешний контракт открыт | `0x36964`, `0x36a50..0x36a80`, `0x3860c` | Эти три значения одного allocator record связываются use-sites; внутреннее определение CSLAlloc отсутствует |
| Producer native handles и IDs экспортируются в HIDL в одном count/order | STATIC PASS | producer `0x36a64..0x36a7c`; converter `0x9508..0x9708` | Handles клонируются и IDs копируются по одному `i`; оба lengths — `u32` |
| PVR клонирует каждый HIDL handle и mmap-ит его FD | STATIC PASS | startPreview `0x65248..0x65298` | FD из handle `+0x0c`; `mmap` length=image+metadata, `PROT=3`, `MAP_SHARED=1`, offset=0 |
| PVR record сохраняет соответствие handle ordinal → mapping base → metadata offset | STATIC PASS | startPreview `0x652a8..0x652e8` | `buf_info+0x18/+0x20/+0x28`, запись шага `0x30` в том же цикле |
| `client+0x60` является массивом metadata offsets | ОПРОВЕРГНУТО | startPreview `0x654c4..0x65660` | Это pointer на `u32` IDs; metadata offset отдельно пишется в `client+0x74` |
| HIDL vector lengths и client count — 64-bit | ОПРОВЕРГНУТО | HIDL `0x9508`, `0x956c`, `0x9604`, `0x9640`; PVR `0x654c4`, `0x654cc`, `0x6a908` | Длины/count загружаются/сохраняются `w` registers, то есть `u32`; pointers остаются 64-bit |
| PVR QBUF ID → DQBUF output → tree lookup на `buf_info[i]` | PARTIAL: userspace field path STATIC PASS; kernel roundtrip unverified | `PrepareStreamOn` `0x6a92c..0x6a940`; EnQ helper `0x6b9a4..0x6baa0`; DQ helper `0x6b378..0x6b4a4`; `DeQueueFrame` `0x6b720..0x6b7f8` | PVR puts ID in request `m.userptr` at `+0x40` (`QBUF 0xc058560f`); DQ helper copies returned `+0x40` into caller `int*` (`DQBUF 0xc0585611`), then PVR uses that value as tree key. Kernel implementation/runtime does not prove the returned word equals the queued ID |
| Producer metadata pointer и PVR mapping относятся к тому же физическому backing store | НЕ ДОКАЗАНО | CSLAlloc result use-sites + PVR `mmap` | Нет исходников/контракта Qualcomm allocator и runtime page identity proof; не включать gate |
| `metadata_ptr` попадает в `FrameMetaDate` без field conversion | STATIC PASS | PVR `0x6b7f0..0x6b820` | base + отдельный `u32` offset; копируются raw `u64/u32` поля по offsets |
| PVR преобразует timestamp в host clock | Не найдено в traced success path | `0x6b7fc..0x6b820`, `0x66634..0x666a8` | В этих местах только memory loads/stores; это не доказывает clock equality |
| Producer handler логирует QTIMER-labeled message timestamp и request ID | STATIC PASS для diagnostic label/data association | producer `0x375d0..0x37724`; формат string table | Handler читает message `+0x18` и request ID `+0x08`; log setup загружает формат `CSLTimestampTypeQtimer ... timestamp=..., monoTimestamp=...`; enum units/source не раскрыты |
| QTIMER значение — physical SOF/exposure-start time | НЕ ДОКАЗАНО | label string; message ring/fence code | В ELF не установлена требуемая семантика события или физическая точка экспозиции |
| Timeout fallback способен использовать предыдущий ring slot | STATIC PASS | fence callback `0x38778..0x387ec`, `0x38bf0..0x38c1c` | После 5 ms elapsed ветка берёт `(requestID-1) mod 38`, пишет старый slot value при current request ID metadata |
| Fallback происходит с известной частотой в реальной камере | НЕИЗВЕСТНО | Только статический branch | Нет runtime telemetry; реальную частоту не экстраполировать |
| Clock domains, frame pose и Lighthouse geometry verified | НЕТ | В исследованных ELF нет достаточной связи | Требуются отдельные физические/системные измерения; не менять gates |

## Поправки к предыдущим интерпретациям

1. **`QuickCameraClient+0x60` — не offset array.** Его элементы — 32-bit IDs, пришедшие из native `+0x220` через HIDL `+0x30`. PVR передаёт ID в QBUF `m.userptr`, а DQBUF helper копирует возвращённый `m.userptr` в `int*`, который `DeQueueFrame` использует как tree key. Сохранение того же ID через kernel queue boundary статически не доказано. Metadata offset равен image size и идёт отдельно: native `+0x324` → HIDL `+0x44` → client `+0x74` → `buf_info+0x28`.
2. **Счётчики — 32-bit.** В HIDL `+0x28/+0x38` и PVR client `+0x68` увидены `ldr/str w`. 64-bit здесь — vector data pointers, handle pointers и mapped addresses. Предшествующая сводка с 64-bit vector length/client count ошибочна.
3. **HIDL `sBufferReady` — notification index, не metadata payload.** PVR `OnBufferReady` не пишет `FrameMetaDate`; metadata извлекается позже по queue/dequeue record.
4. **Callback slot `0x6c864` больше не только кандидат.** Android RELR slot `0x75300` разрешается в executable `0x6c864`; `QuickCameraClient::ConfigAndAllocBuffers` передаёт callback с vptr `0x752d0`, а тело callback имеет соответствующие status/QuickCameraBufInfo обращения и пишет в captured output.
5. **QTIMER label не означает physical SOF.** В той же ELF есть строки с `sof notify`, но связи, которая бы доказывала семантику этого ring timestamp как SOF или начала экспозиции, не установлено.
6. **Статическая последовательность mmap не подтверждает backing pages.** Похожесть размеров и сохранение handle/ID порядка не закрывают внешний CSL allocator contract.

## Итоговый уровень завершённости

`Producer → HIDL → PVR offsets/IDs and queue calls → FrameMetaDate` доказан на уровне статических полей, order и pointer arithmetic; сопоставление returned queue key с тем же `buf_info[i]` остаётся условным на стандартный kernel USERPTR QBUF/DQBUF roundtrip. Утверждение «PVR получает те же физические CSL metadata bytes» также **PARTIAL**, потому что экспортированный CSL FD и producer CPU pointer не подтверждены независимым контрактом или runtime backing-store proof. Timestamp physical event, clock sync и pose остаются неизвестными.

Все действующие gates остаются: `observe_only=true`; `exact_time=false`; `live_lighthouse_correction_allowed=false`; `mapping_verified=false`; `pose_verified=false`; `frame_meta_bridge_verified=false`; `physical_event_verified=false`; `shared_buffer_identity_verified=false`.
