# P3-A4 — Full QuickCamera buffer provenance

Дата: 2026-10-18. Исследование выполнено офлайн по SHA-pinned ARM64 ELF. Адреса ниже — виртуальные адреса ELF. Это доказательство статического пути данных; оно не включает проверку живого устройства или физической памяти.

## Статус

Статическая связь allocator record → native handle/ID → HIDL handle/ID → PVR `mmap`, queue-call fields, tree lookup и metadata pointer прослежена по инструкциям и циклам, сохраняющим индекс и порядок. Kernel roundtrip поля `m.userptr` между QBUF и DQBUF не анализируется в этих userspace ELF. `client+0x60` — массив 32-битных queue IDs, не metadata offsets. Metadata offset передаётся отдельным `u32` в `client+0x74`, затем хранится в `buf_info+0x28`.

Не доказана внутренняя гарантия Qualcomm `CSLAlloc`, что его CPU pointer и экспортированный FD отображают одни и те же backing pages. Поэтому `shared_buffer_identity_verified=false` и `frame_meta_bridge_verified=false` остаются закрытыми, несмотря на статически прослеженные указатели, FD, IDs и одинаковые индексы.

## Входы и их SHA-256

| ELF | SHA-256 |
|---|---|
| `libpvrtrackingcamera.so` | `cf9e507f412ec33d62c2f720669fcdd093f1822c9cbf3adefd0a26a6b4d072ee` |
| `quickcamera.core.so` | `fb22355acd35b9772a5538a7d1c49175641165ad0368e7c47e5831f5f1727017` |
| `pico.camera.quickcamera.quickcameramodule@1.0-impl.so` | `c3157e66d842dcdca148f1b98328bd5e7ce80c4ab9bbbacba895465556314f47` |

## ABI layouts

### Native C++ `QuickCameraBufInfo`

Размер используемого native объекта — `0x368` байт: HIDL wrapper очищает именно `0x368` байт перед вызовом native `Initialize` (impl `ConfigAndAllocBuffers`, около `0xa514`). Поля восстановлены по producer stores и HIDL reads:

| Offset | Поле / тип | Основание |
|---:|---|---|
| `+0x00..+0x18` | семь `u32`; `+0x14` image byte size, `+0x18` buffer count | producer `0x36b40`, HIDL conversion `0x94ac..0x9508` |
| `+0x20..+0x21f` | до 64 native-handle pointers, 64-bit каждый | producer stores handle pointer по индексу; HIDL читает `[native+0x20+i*8]` |
| `+0x220..+0x31f` | до 64 buffer IDs, `u32` каждый | producer `0x36a7c`; HIDL `0x96b4..0x96e8` |
| `+0x320` | metadata region size, `u32` | producer `0x36b54` |
| `+0x324` | metadata byte offset, `u32` | producer `0x36b48` |
| `+0x328..+0x367` | 0x40-byte camera-ID string storage | HIDL string assignment from native `+0x328` at `0x94e8..0x94f4` |

Первые четыре scalar значения и точное внутреннее представление последних 0x40 байт не получили имён из символов; здесь указаны только наблюдаемые widths/uses.

### HIDL `QuickCameraBufInfo`

Восстановленный размер — `0x58` байт. Важно: pointer fields — 64-bit, но обе vector lengths — **32-bit**. Это видно по `ldr w24` / `str w24`, а не по ширине ARM64 адресов.

| Offset | Поле / тип |
|---:|---|
| `+0x00..+0x18` | семь scalar `u32` |
| `+0x20` | `hidl_vec<hidl_handle>`: data pointer `u64` |
| `+0x28` | число handles `u32` |
| `+0x2c` | owns-buffer byte |
| `+0x30` | `hidl_vec<u32>` IDs: data pointer `u64` |
| `+0x38` | число IDs `u32` |
| `+0x3c` | owns-buffer byte |
| `+0x40` | metadata size `u32` |
| `+0x44` | metadata offset `u32` |
| `+0x48..+0x57` | 16-byte `hidl_string` |

HIDL `hidl_handle` в массиве имеет шаг `0x10`; conversion выделяет `count*0x10` bytes и обрабатывает handle по одному в цикле.

### PVR `QuickCameraClient` и `buf_info`

| Offset | Поле / тип | Заполнение/использование |
|---:|---|---|
| `client+0x10` | vector элементов `buf_info`, stride `0x30` | `startPreview` push-back `0x652cc..0x652e8` |
| `buf_info+0x18` | cloned `native_handle*`, 64-bit | `startPreview` `0x652ac` |
| `buf_info+0x20` | mapped base pointer, 64-bit | `startPreview` `0x65298`, затем `0x652d0` |
| `buf_info+0x28` | metadata byte offset `u32` | HIDL `+0x44` со stack `+0x7c` записывается в temp record `0x652a8..0x652b0` |
| `client+0x60` | pointer на `u32` queue IDs, 64-bit | скопирован из HIDL vector data pointer |
| `client+0x68` | count `u32`; owner flag — byte `+0x6c` | `startPreview` `0x654c4..0x654d0`; `PrepareStreamOn` `0x6a908` |
| `client+0x70` | metadata size `u32` | `startPreview` `0x65648..0x65654` |
| `client+0x74` | metadata offset `u32` | `startPreview` `0x65658..0x65660` |

Неизвестные/configuration слова `buf_info+0x00..+0x17` намеренно не переименованы. Их восстановление не требуется для доказательства offset/handle пути.

## Цепочка данных по инструкциям

### 1. Producer allocation: CSL record → native handle, ID и metadata region

`CamQuickAccessDevice::AllocImageBuffers` около `0x36680` вызывает `CSLAlloc` (`0x36964`). Использование результата показывает три отдельно применяемых значения:

1. Первый `u32` CSL record (`record+0x00`) читается в `0x36a74` и пишется в native ID array по текущему индексу `i` (`0x36a7c`). Тот же ID передаётся как ключ в `unordered_map::emplace_unique_key_args` (`0x36a80`).
2. Адрес `record+0x08` формируется как `x27` в `0x36a58` и передаётся как mapped-value argument при вставке ID→CPU pointer в map (`0x36a6c..0x36a80`). Позднее fence callback по этому ID получает mapped pointer (`0x3860c`). Название «CPU base» — интерпретация use-site; отдельный контракт CSL не найден.
3. `native_handle_create(1,0)` вызывается в `0x36a50`; значение CSL record `+0x14` загружается в `0x36a68` и кладётся в единственный fd slot native handle `[handle+0x0c]` в `0x36a70`. Handle pointer сохраняется в native handles array в `0x36a64`.

В конце цикла `0x36b40` записывает image size в native `+0x14`, а buffer count — в `+0x18`. Producer также сохраняет image size в `device+0x70` (`0x36b44`), экспортирует его как metadata offset в `QuickCameraBufInfo+0x324` (`0x36b48`) и вычисляет metadata size как `device+0x58 - image_size`, записывая результат в `+0x320` (`0x36b4c..0x36b54`). Следовательно, offset равен концу image region; metadata region располагается после него.

### 2. Native → HIDL: одинаковое число и порядок handles/IDs

Вызов HIDL wrapper `ConfigAndAllocBuffers` начинается `0xa4c4`: после успешного native `Initialize` (`0xa5a8`) он вызывает `converttoHidl` (`0xa688`). Реальное тело conversion начинается `0x9494` (динамический символ `0xae60` — короткая trampoline).

- `0x94ac..0x94f0` копируют семь scalar `u32` в те же HIDL offsets и native camera ID string в HIDL `+0x48`.
- `0x94f8..0x9504` копируют native `+0x320/+0x324` в HIDL `+0x40/+0x44`.
- Количество берётся из native `+0x18` (`0x9508`, `ldr w24`). Conversion выделяет HIDL handles в размере `count*0x10`, затем для каждого `i` клонирует native handle `native+0x20+i*8` и помещает его в HIDL handles vector по тому же `i` (`0x9540..0x9600`, `0x96a0..0x9708`).
- HIDL IDs vector выделяется как `count*4` bytes (`0x961c..0x963c`). Цикл `0x9650..0x9678` читает native ID `+0x220+i*4` и пишет его в HIDL vector `+0x30+i*4`.
- Оба HIDL count поля загружаются/сохраняются как `w` registers: `+0x28` и `+0x38` — `u32`; pointer slots `+0x20/+0x30` — `x` registers, 64-bit.

Это доказывает одинаковые count и порядок handle/ID в conversion, но не доказывает физическую семантику CSL ID.

### 3. HIDL callback result → PVR temporary descriptor

PVR `QuickCameraClient::ConfigAndAllocBuffers` в `0x6a3dc` готовит callback объект со vptr `0x752d0` (`0x6a3f0..0x6a408`) и захваченным output pointer, затем вызывает HIDL method через indirect call (`0x6a420..0x6a430`). Android RELR slot `0x75300` равен vptr `0x752d0+0x30`; SHA-pinned ELF хранит в нём `0x6c864`.

RELR parser декодировал 12/12 целевых relocation entries; `0x75300 → 0x6c864` попадает в executable PT_LOAD. Тело `0x6c864` читает статус из `x1`, HIDL `QuickCameraBufInfo` из `x2`, копирует scalar fields, handles vector, IDs vector, metadata fields и string в output descriptor, захваченный callback объектом. Совпадение вызовного контекста, ABI обращений и разрешённого vtable slot независимо подтверждает callback identity. Соседняя `PvrCameraDeviceCallback::OnBufferReady` (`0x663e4`, размер `0x10`) является no-op/default return и не записывает timestamp metadata.

### 4. PVR `startPreview`: mmap и раздельная передача ID и offset

Экспортированная `PvrCameraDevice::startPreview` — `0x65090`, размер `0x6e8`, захвачен целиком.

- `0x651e8..0x651f4`: берёт `QuickCameraClient*` из `PvrCameraDevice+0x60`, передаёт stack `QuickCameraBufInfo` в `ConfigAndAllocBuffers`.
- Цикл handles начинается `0x65248`. Для каждого HIDL handle ordinal `i`, `0x65260..0x65264` получает native handle и клонирует его. `0x65270` загружает fd из clone `+0x0c`.
- `0x65268..0x6528c` подаёт в `mmap`: длину `image_size + metadata_size` (`w1`), `PROT_READ|PROT_WRITE=3` (`w2`), `MAP_SHARED=1` (`w3`), fd clone (`w4`) и offset 0 (`x5`). Возвращённый mapping base сохраняется (`0x65298`).
- Для того же `i` создаётся `buf_info` с clone handle (`+0x18`), mapping base (`+0x20`) и metadata offset из HIDL `+0x44` (`+0x28`). Push-back в client vector `+0x10` сохраняет тот же порядок (`0x652a8..0x652e8`).
- Отдельно HIDL IDs pointer/count из `sp+0x68/sp+0x70` копируются в `client+0x60/client+0x68` (`0x654c4..0x6563c`). Count копируется `u32`; цикл копирует ID words последовательно. Это массив IDs, не offsets.
- Metadata size `sp+0x78` попадает в `client+0x70` (`0x65648..0x65654`); metadata offset `sp+0x7c` — в `client+0x74` (`0x65658..0x65660`). Затем вызывается `StreamOn` (`0x65670..0x65674`).

### 5. PVR QBUF/DQBUF key fields → tree lookup → `FrameMetaDate`

`QuickCameraClient::PrepareStreamOn` (`0x6a768`, полный symbol extent):

- Count `u32` читается из `client+0x68` (`0x6a908`), IDs pointer — из `client+0x60` (`0x6a910`).
- В цикле `i` загружается `ids[i]` как `w24` (`0x6a92c`) и передаётся в `VideoQueueUtil::EnQueVbQueueBuffer(fd, i, id, true)` (`0x6a930..0x6a940`).
- В PVR lookup tree создаётся ключ `id` (`0x6a9b4`, node `+0x20`) и mapped pointer на `client->buf_info[i]` (`0x6a9c4`, node `+0x28`). Таким образом, queue key связан с тем record, который построен из handle ordinal `i`.
- `VideoQueueUtil::EnQueVbQueueBuffer(unsigned short, int, bool)` занимает точный symbol extent `0x6b9a4..0x6baa0`. Он сохраняет index из `w1`, ID из `w2` и кладёт sign-extended ID в request `m.userptr` поле `+0x40` (`0x6b9c0..0x6ba04`), затем вызывает ioctl `0xc058560f` с длиной `0x60` (`0x6ba10`).

`QuickCameraClient::DeQueueFrame(void**, FrameMetaDate*)` начинается `0x6b6e8`:

- `0x6b720` получает dequeue index/key через `DeQueVbQueueBuffer`.
- Вызванный `VideoQueueUtil::DeQueVbQueueBuffer(int*, bool)` имеет extent `0x6b378..0x6b4a4`; он отправляет ioctl `0xc0585611` длиной `0x60` (`0x6b418`) и при успехе копирует request/result `m.userptr` из `+0x40` в caller `int*` (`0x6b458..0x6b45c`). `DeQueueFrame` затем использует этот output как tree key.
- `0x6b72c..0x6b7ec` находит record по ключу в `client+0x108`.
- `0x6b7f0` загружает `buf_info+0x20` mapped base; `0x6b7f4` загружает `buf_info+0x28` offset; `0x6b7f8` вычисляет `base+offset`.
- `0x6b7fc..0x6b820` копирует metadata `+0x08` (64-bit request ID), `+0x00` (64-bit timestamp candidate), `+0x10`, `+0x14`, `+0x18` (три 32-bit поля) в `FrameMetaDate` по тем же offsets. Metadata record содержит минимум `0x1c` bytes.

`processCameraFrame` (`0x66634`) вызывает этот overload; при успехе timestamp word из `FrameMetaDate+0` повторно записывается в PVR item (`0x6667c`, `0x666a8`). В этой успешной ветке преобразования clock domain не найдено.

## Граница доказательства

Статически установлены: FD значение, записанное в native handle; HIDL и PVR handle clones; FD и mmap аргументы; per-index order; отдельно передаваемый metadata offset; PVR-side QBUF request field, DQBUF output field, tree lookup и pointer arithmetic/byte copies в `FrameMetaDate`.

Не установлены: реализация/контракт импортированного `CSLAlloc`; физическая идентичность его CPU pointer и exported FD backing pages; kernel сохранение queue `m.userptr` между QBUF и DQBUF и runtime успешность queue/dequeue; timestamp unit/domain; реальная частота fallback; физический event и пригодность для pose/Lighthouse.

Текущие закрытые gates: `observe_only=true`, `exact_time=false`, `live_lighthouse_correction_allowed=false`, `mapping_verified=false`, `pose_verified=false`, `frame_meta_bridge_verified=false`, `physical_event_verified=false`, `shared_buffer_identity_verified=false`.
