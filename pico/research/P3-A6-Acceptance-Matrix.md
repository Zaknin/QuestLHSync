# P3-A6 — Acceptance Matrix

Обновлено: 2026-10-19. M0/M1 preparation отделена от будущих runtime acceptance. Владелец предоставил Android property tuple и process-name наблюдение как target observations; этот turn не выполнял ADB/device action. Hardware acceptance rows остаются `NOT RUN`, `UNKNOWN` или `BLOCKED`.

## Offline preparation M0/M1

| ID | Проверка | Статус | Доказательство / граница |
|---|---|---|---|
| M0-01 | Analyzer принимает только synthetic schema и отклоняет experimental/unknown input | `SYNTHETIC PASS` | Unit tests; реальный runtime JSON намеренно не поддержан |
| M0-02 | QBUF/DQBUF low-u32 correlation и raw-u64 сравнение | `SYNTHETIC PASS` | Fixture содержит sign-extended ID, raw match и несовпадающий low-u32 key |
| M0-03 | Frame-sequence gaps, repeated timestamp, fallback markers, request ID divergence | `SYNTHETIC PASS` | Synthetic fixture; gaps/fallback candidates не выдаются за доказанный drop/fallback |
| M0-04 | Clock affine fit, bracket width, calibrated ppm, wrap/reset rejection | `SYNTHETIC PASS` | Синтетический +100 ppm; без scale drift заблокирован. Никакого Pico clock result нет |
| M0-05 | Hardware execution gate defaults closed, exact scope + time/count bounds | `SYNTHETIC PASS` | Tests validate gate contract; настоящего approval record/direct confirmation нет |
| M0-06 | Device node, runtime queue contract, mapping identity, timestamp origin, frame delivery | `NOT RUN` | Pico и device interfaces не использовались |
| M1-01 | PS7 inventory gate, exact ADB vectors, Phoenix-family identity tuple, bounded/private evidence, POSIX protocol/quoting, pinned local ADB path and Android process names containing `:` | `MOCK + POSIX INTEGRATION PASS OFFLINE` | Full Python suite 198/198 PASS; PowerShell harness 28/28 check groups. Native allowlist runs before synthetic responses; all identity getprop, build/release/kernel/process/FD vectors are checked with and without `-t 42`. Exact tuple `A8110/PICOA8110/Phoenix_ovs/Pico` remains owner-bound; software tuple does not verify Pico 4 Pro hardware variant. 13 matching synthetic processes, with colon-name at index 13, preserve the exact name and all 13 PID reach FD probes; slash-name and unexpected protocol records fail closed. Existing pinned-path, dry-run, WSL `/bin/sh`, tab-byte/parser, Android 10 argv-join and `ps` framing checks remain. Owner-reported hardware formatting was not rechecked. ADB client/server and Pico не запускались; synthetic result is not experimental PASS |

## Будущие runtime acceptance

Любой runtime результат применим только к точному build fingerprint, process и ограниченной approved session. Чтобы принять строку, приватная evidence schema должна содержать method, time range, raw observations, source/build IDs, limits и hashes. Тесты на synthetic fixture не засчитываются как device evidence.

| ID | Утверждение | Критерий для ограниченного observed-run PASS | Что не является достаточным / текущий статус |
|---|---|---|---|
| R1 | PVR `VideoQueueUtil` использовал фактический `/dev/videoN` | Зафиксирован внешний `ioctl(fd,0xc01856c0,...)` из нужного PID/TID; в том же интервале fd symlink указывает на ровно этот node; build/process identity сохранены. Если node один только в process inventory, но fd не связан с ioctl — `PARTIAL` | Исторические `/dev/video1` или `/dev/video3`, статический `open(path)` и process list не доказывают конкретный fd. Сейчас `UNKNOWN/BLOCKED` |
| R2 | DQBUF возвращает queue key, совпавший с QBUF ID | Для каждой successful пары записаны `qbuf_id_u32`, raw QBUF `m.userptr`, raw DQBUF `m.userptr`, return status и caller low-u32 key; все low-u32 keys равны ожидаемому ID, QBUF raw совпадает sign-extend правилу, mismatch/error = 0; coverage достигает заранее утверждённого лимита и включает все наблюдённые IDs | Трасса outer ioctl без nested payload, совпавший только count, один случай или стандартный USERPTR manpage недостаточны. Observed-run PASS не доказывает kernel guarantee за пределами выборки. Сейчас `BLOCKED` |
| R3 | Producer CPU mapping и PVR FD mapping относятся к одной allocation identity | Оба объекта независимо привязаны к одному kernel-exported dma-buf/allocation identity (например, подтверждённый exporter+object inode/ID), с mapping ranges/offsets; процесс и FD attribution сохранены; пиксельные bytes не читаются | Одинаковый размер, fd number в разных процессах, `MAP_SHARED`, pointer order, content match или один fdinfo без двух сторон недостаточны. Если kernel identity скрыта — `BLOCKED`. Coherency отдельно не следует. Сейчас `UNKNOWN/BLOCKED` |
| R4 | CSL request ID и timestamp связаны в runtime | Существующая точная log record/allowlisted observation связывает request ID с raw QTIMER value для каждой строки; указаны provenance, field units (если известны) и build | QTIMER label без event semantics не доказывает SOF. Сейчас `NOT RUN` |
| R5 | Fallback для конкретного frame/request | Явный fallback branch marker или наблюдаемая timestamp-source request ID, подтверждённая source-level relation для matching build; marker/value/metadata записаны отдельно | Повтор timestamp, request ID gap, static fallback branch или расхождение IDs без ветки не доказывают fallback. Runtime frequency — только в пределах выборки. Сейчас `NOT RUN` |
| R6 | Metadata поля PVR output наблюдаются без frame data | Allowlist точных numeric fields/offsets, request correlation и read method; доказано, что сохранены только metadata, не image region | Наличие mapping/`FrameMetaDate` copy в ELF не доказывает runtime content. Если нужен process-memory access без отдельного разрешения — `BLOCKED`. Сейчас `NOT RUN` |
| R7 | QTIMER и Android monotonic relation / drift | Один и тот же clock domain/API в пределах серии; сырые QTIMER значения, request correlation, monotonic brackets, callback/delivery sample и residuals сохранены; независимо подтверждённая QTIMER scale указана. Drift ppm принимается только относительно этой scale | Без scale возможны только observed slope/offset. Host receive time, mixed MONOTONIC/BOOTTIME, logger latency или незакоррелированные frames не дают clock synchronization. Сейчас `UNKNOWN` |
| R8 | Frame delivery latency | Delivery timestamp берётся у Android consumer/PVR delivery boundary в явно указанном clock domain; relation к raw QTIMER рассчитывается с uncertainty/residuals и ограничен observed pipeline | ADB/host arrival, logcat rendering time или dequeue timestamp — не физический exposure age и не обязательно callback boundary. Сейчас `NOT RUN` |
| R9 | QTIMER event = physical SOF / exposure start | Matching PICO source/docs однозначно задают event semantics и подтверждены применимость к build, либо отдельное optically referenced hardware measurement синхронизировано с тем же clock | System latency, CSL label, PVR callback, Camera2 timestamp другого stream и синтетические tests недостаточны. Сейчас `NOT PROVEN`; нужна отдельная аппаратная задача |

## Неизменяемые gates

На всём M0 и до получения независимых доказательств остаются `false`:

```text
exact_time=false
mapping_verified=false
pose_verified=false
shared_buffer_identity_verified=false
frame_meta_bridge_verified=false
live_lighthouse_correction_allowed=false
physical_event_verified=false
```

`SYNTHETIC PASS` не переводится в `STATIC PASS` или hardware `PASS`. Повышение runtime статуса допустимо только после review приватного evidence package по этой матрице и соответствующей отдельной approval scope.

`MOCK + POSIX INTEGRATION PASS OFFLINE` подтверждает поведение collector на injected fixtures и POSIX shell parsing/quoting в WSL. Exact Android property tuple подтверждает только owner-bound Phoenix-family software identity; он не является Pro hardware attestation и не доказывает подключение к Pico. Это не является ADB-to-device result и не повышает R1–R9. Открытый `/dev/videoN` fd без наблюдённого `ioctl(fd,0xc01856c0,...)` остаётся недостаточным для R1.
