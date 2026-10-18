# P3-A4 — QuickCamera timestamp provenance and limits

Дата: 2026-10-18. Это статический анализ SHA-pinned `quickcamera.core.so` и `libpvrtrackingcamera.so`; timestamp values не захватывались с устройства.

## Краткий вывод

Producer получает `u64` из `CSLMessage+0x18`, кеширует его по request ID в 38-slot ring, а `CSLFenceCallback` записывает выбранное значение в metadata buffer. PVR копирует это значение без clock conversion в `FrameMetaDate+0`, затем переносит его в frame item.

В ELF есть строка `CSLTimestampTypeQtimer frameMessage:requestID=..., timestamp=..., monoTimestamp=...`. Handler читает request ID из message `+0x08` и timestamp из `+0x18`; в log setup `0x376a8..0x37724` загружается этот QTIMER-labeled format string (`0x37704`). Это подтверждает label/data association внутри handler и отдельное поле `monoTimestamp` в диагностическом тексте. Машинный код не доказывает, что конкретный QTIMER value означает physical sensor SOF, exposure start или иной точно определённый момент. `timestamp`, `monoTimestamp` и Windows/PVR time domains статически не сопоставлены. Fallback может записать timestamp из предыдущего ring slot, одновременно пометив metadata текущим request ID.

## 1. CSL message → timestamp ring

Veneer `0x4c470` подписан как `CamQuickAccessDevice::CSLMessageHandler(void*, CSLMessage*)` и безусловно переходит в тело `0x375d0`. (LLVM относит часть адресов к соседним символам; veneer — явная граница вызова.)

| VA | Действие |
|---:|---|
| `0x375e8` | читает 32-bit message type из `CSLMessage+0x00` |
| `0x375f4..0x37604` | type `1` уходит по отдельной ветви; type `0` проверяется дальше |
| `0x37608` | читает request ID из `CSLMessage+0x08` |
| `0x37618` | читает 64-bit значение из `CSLMessage+0x18` |
| `0x37620..0x37634` | вычисляет `requestID mod 38` |
| `0x37640` | сохраняет 64-bit значение в `device+0x14c0 + slot*8` |
| `0x37644..0x37648` | помечает slot valid в bitmap/byte area около `device+0x1688` |

Log string присутствует в producer ELF:

`CSLTimestampTypeQtimer frameMessage:requestID=%lld, linkhdl:%p, frameCount=%lld, timestamp=%lld, monoTimestamp=%lld`

Она показывает внутренний QTIMER label и наличие отдельного `monoTimestamp`, но не содержит определения enum value, единиц, clock source/epoch или гарантии физического события. В binary также встречаются сообщения с текстом `sof notify`; одного наличия строки недостаточно, чтобы доказать, что именно описанный message type/ring value является этим SOF notification. Требуемой привязки между ними не найдено.

## 2. Request ID и callback context

`CamQuickAccessDevice::ReuqestBuildThreadProcessing` начинается около `0x39648`:

- `0x39818` вызывает producer-side `VideoQueueUtil::DeQueVbQueueBuffer`; полученный buffer ordinal находится в `w23`.
- `0x39aec` записывает request sequence `x26` в context `+0x10`. Context base вычислен как `x27=x10+0x310` в `0x39af4`.
- `0x39b00` записывает dequeued buffer ordinal `w23` в context `+0x24`.
- `0x39b54..0x39b58` передаёт этот context в `CSLFenceAsyncWait`.

Veneer `0x4c478` подписан как `CamQuickAccessDevice::CSLFenceCallback(void*, int, CSLFenceResult)` и branches в тело `0x38338`. Callback по `context+0x24` ищет producer map, созданную при allocation по buffer ID; найденный mapped value используется как buffer CPU address.

## 3. Fence completion → metadata bytes и fallback

Callback берёт metadata offset из `device+0x70` (`0x386a4`) и формирует pointer `buffer_base+offset` (`0x386b8`). Дальше оба timestamp selection path записывают 64-bit value по metadata offset `+0x00`:

- cached/current slot path: `0x387f0..0x387fc`;
- timeout fallback path: `0x38be4..0x38c1c`.

Timed wait сохраняет начальный `steady_clock::now()` около `0x38778`, формирует condition-variable system-clock deadline и вызывает `__do_timed_wait` (`0x387cc..0x387d0`), затем повторно читает `steady_clock::now()` (`0x387dc`). Если elapsed time не меньше `0x4c4b40` ns = 5,000,000 ns, ветвится в fallback (`0x387e8..0x387ec`). Это timeout порог кода, а не измеренная частота fallback.

Fallback адреса:

| VA | Действие |
|---:|---|
| `0x38bf0` | начинает с `current_request_id - 1` |
| `0x38bf8..0x38c08` | вычисляет modulo 38 |
| `0x38c0c` | загружает timestamp из предыдущего ring slot `device+0x14c0` |
| `0x38c10..0x38c1c` | получает metadata pointer и записывает выбранный timestamp в `metadata+0` |
| `0x3881c` | записывает текущий request ID в `metadata+8` |

Остальные producer payload поля записываются как `u32` по `metadata+0x10`, `+0x14`, `+0x18` (`0x38970`, `0x38978`, `0x38a38`). Порядок данных совпадает с PVR чтением.

Следствие: `FrameMetaDate+8` в fallback branch описывает request, завершение которого вызвало callback; первое `u64` может происходить из предыдущего slot. Поэтому timestamp source request и metadata request могут различаться. Неизвестно, является ли этот previous-slot value фактическим временем соседнего кадра, устаревшим повтором или другим sample: runtime значения не наблюдались.

## 4. PVR frame consumer

PVR `DeQueueFrame(void**, FrameMetaDate*)` (`0x6b6e8`) вызывает dequeue helper (`0x6b720`), находит буферный record по returned key и вычисляет metadata pointer:

- record pointer: `0x6b7ec`;
- mapped base из `buf_info+0x20`: `0x6b7f0`;
- `u32` metadata offset из `buf_info+0x28`: `0x6b7f4`;
- `base+offset`: `0x6b7f8`.

Затем копирует metadata `+8` в `FrameMetaDate+8` (`0x6b7fc..0x6b800`), metadata `+0` в `FrameMetaDate+0` (`0x6b804..0x6b808`) и три `u32` поля (`0x6b80c..0x6b820`). `processCameraFrame` вызывает этот overload (`0x66634`); successful path переносит первый `u64` в PVR frame item (`0x6667c`, `0x666a8`). Преобразования или сравнения с host clock в этих местах не видно.

HIDL `sBufferReady` (`0x98e4`) передаёт client callback только 32-bit buffer index. PVR `PvrCameraDeviceCallback::OnBufferReady` (`0x663e4`, `0x10` bytes) не формирует timestamp metadata. Это отдельный notification путь; metadata кадра извлекается позже из queue/mapped record.

## Что доказано и что нет

**Доказано статически:** message содержит прочитанное 64-bit поле `+0x18`; request ID участвует в ring slot; fence context переносит request sequence и buffer ordinal; callback выбирает timestamp, пишет metadata; timeout ветка использует `requestID-1 mod 38`; PVR копирует metadata без видимого преобразования времени.

**Не доказано:** физический SOF/exposure-start смысл QTIMER; exact units и epoch; связь значения с `monoTimestamp`; clock conversion/synchronization между CSL, PVR, host и Lighthouse; fallback incidence, dropped/duplicated frame behavior при runtime; pose timestamp semantics и geometric mapping.

Безопасная граница пока — наблюдение и диагностика. `exact_time=false`, `physical_event_verified=false`, `pose_verified=false`, `mapping_verified=false`, `live_lighthouse_correction_allowed=false`.

## Будущая аппаратная проверка — не выполнялась

Для отдельного разрешённого эксперимента собрать синхронные записи: raw CSL timestamp, request ID, callback/fallback исход, buffer ID, queue dequeue index, host monotonic dequeue time и frame-delivery time. Привязку к физическому SOF/exposure проверять только независимым сенсорным сигналом или авторитетной документацией производителя; строки `sof` в log text недостаточно. Clock relationship оценивать по повторным paired samples до/после серии, показывать fit, drift и uncertainty, не смешивать wall clock с monotonic clocks. Pose и Lighthouse geometry измерять как отдельную последующую проверку. Не менять firmware/driver и не включать correction в рамках такой диагностики; любые обращения к Pico требуют отдельного разрешения пользователя.
