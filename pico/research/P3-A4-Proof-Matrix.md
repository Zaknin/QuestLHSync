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
| `CSLHwInternalDefaultIoctl2` оборачивает QBUF/DQBUF коды во внешний ioctl | STATIC PASS | wrapper `0x6c2f8..0x6c3d8`; вызовы QBUF `0x6ba10`, DQBUF `0x6b418` | Wrapper строит 24-byte envelope `{op:u32,size:u32,reserved:u64,payload_ptr:u64}` и вызывает `ioctl(fd,0xc01856c0,&envelope)`; payload bytes userspace wrapper не переписывает. `0xc058560f/0xc0585611` — вложенные op codes, helper size `0x60` |
| PVR `fd` у wrapper соответствует конкретному `/dev/videoN` | UNKNOWN | `PrepareStreamOn` `0x6a788..0x6a7e0`; wrapper fd load `0x6c318`; исторический процессный inventory | Путь для `open(path,0x802)` приходит динамически; в ELF нет literal `/dev/videoN`. Исторический inventory показывает QuickCamera service на `/dev/video1` и `/dev/video3`, но не связывает этот `fd` с одним из них |
| PVR QBUF ID → DQBUF output → tree lookup на `buf_info[i]` | PARTIAL: userspace fields STATIC PASS; kernel contract BLOCKED | `PrepareStreamOn` `0x6a92c..0x6a940`; EnQ `0x6b9a4..0x6baa0`; DQ `0x6b378..0x6b4a4`; wrapper `0x6c2f8..0x6c3d8`; `DeQueueFrame` `0x6b720..0x6b7f8` | PVR кладёт ID в payload `m.userptr+0x40`, передаёт внутренний QBUF код `0xc058560f`; DQ внутренний код `0xc0585611` и затем читает payload `+0x40` в `int*` как tree key. Внешний kernel ioctl — `0xc01856c0`. Kernel handler не найден; сохранение/возврат исходного ID не гарантировано доступными статическими данными. Generic V4L2 `USERPTR` docs этого не закрывают |
| Producer `CSLBufferCacheOp` call site | STATIC PASS для вызова/аргументов; kernel effect UNKNOWN | `quickcamera.core.so` `0x383e4..0x383f4` | Импорт вызывается с `w0=handle`, `w1=1`, `w2=0` перед успешной веткой StreamOn. Эффект invalidate-only соответствует сигнатуре в публичном CamX mirror, но matching implementation и driver cache-op handler для Pico отсутствуют |
| Producer metadata pointer и PVR mapping относятся к тому же физическому backing store | UNKNOWN / BLOCKED | CSLAlloc use-sites; публичный CamX mirror; PVR `mmap` | Не найдено matching ELF/source для PICO build. Неофициальный CamX mirror показывает аналогичный fd→mmap путь, но не доказывает PICO ABI, kernel object/backing pages или физическую identity; gate не включать |
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

`Producer → HIDL → PVR offsets/IDs and queue calls → FrameMetaDate` доказан на уровне userspace полей, порядка и pointer arithmetic. Но QBUF/DQBUF проходят через vendor ioctl2 envelope; kernel dispatch/copy-back handler не найден, поэтому возвращённый queue key **PARTIAL** и соответствие тому же `buf_info[i]` не гарантируется. Для CSLAlloc найден только публичный неофициальный CamX analogue без PICO build match, поэтому backing-store identity остаётся **UNKNOWN/BLOCKED**. Timestamp physical event, clock sync и pose остаются неизвестными.

Все действующие gates остаются: `observe_only=true`; `exact_time=false`; `live_lighthouse_correction_allowed=false`; `mapping_verified=false`; `pose_verified=false`; `frame_meta_bridge_verified=false`; `physical_event_verified=false`; `shared_buffer_identity_verified=false`.

## P3-A6-M0 note — статусы не повышались

P3-A6-M0 подготовила offline-only synthetic analyzer и тесты; device observations не выполнялись. Поэтому строки matrix для точного `/dev/videoN`, kernel QBUF/DQBUF roundtrip, producer/PVR backing identity, runtime fallback frequency, QTIMER clock conversion и physical SOF/exposure сохраняют статусы, указанные выше. `SYNTHETIC PASS` из [`P3-A6-Acceptance-Matrix.md`](P3-A6-Acceptance-Matrix.md) — только результат обработки искусственных данных и не является дополнительной статической или аппаратной доказательной строкой.
