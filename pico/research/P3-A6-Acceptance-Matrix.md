# P3-A6 — Acceptance Matrix

Обновлено: 2026-10-19. M0/M1/M2 offline preparation отделена от runtime acceptance. Pico 4 Pro на international Pico OS — установленный факт владельца; Android property tuple описывает только программную идентичность и не пересматривает этот факт. M1.5 hardware outcome остаётся `PARTIAL_PERMISSION_DENIED`. M2 collector прошёл только synthetic/offline проверки; ADB/device actions в M2 задаче не выполнялись.

## Offline preparation M0/M1

| ID | Проверка | Статус | Доказательство / граница |
|---|---|---|---|
| M0-01 | Analyzer принимает только synthetic schema и отклоняет experimental/unknown input | `SYNTHETIC PASS` | Unit tests; реальный runtime JSON намеренно не поддержан |
| M0-02 | QBUF/DQBUF low-u32 correlation и raw-u64 сравнение | `SYNTHETIC PASS` | Fixture содержит sign-extended ID, raw match и несовпадающий low-u32 key |
| M0-03 | Frame-sequence gaps, repeated timestamp, fallback markers, request ID divergence | `SYNTHETIC PASS` | Synthetic fixture; gaps/fallback candidates не выдаются за доказанный drop/fallback |
| M0-04 | Clock affine fit, bracket width, calibrated ppm, wrap/reset rejection | `SYNTHETIC PASS` | Синтетический +100 ppm; без scale drift заблокирован. Никакого Pico clock result нет |
| M0-05 | Hardware execution gate defaults closed, exact scope + time/count bounds | `SYNTHETIC PASS` | Tests validate gate contract; настоящего approval record/direct confirmation нет |
| M0-06 | Device node, runtime queue contract, mapping identity, timestamp origin, frame delivery | `NOT RUN` | Pico и device interfaces не использовались |
| M1-01 | PS7 inventory gate, exact ADB vectors, Phoenix-family identity tuple, bounded/private evidence, POSIX protocol/quoting, pinned local ADB path and Android process names containing `:` | `MOCK + POSIX INTEGRATION PASS OFFLINE` | Full Python suite 199/199; PowerShell harness 29/29; direct WSL POSIX integration PASS; `git diff --check` PASS. Native allowlist runs before synthetic responses; vectors include identity/build/release/kernel/process/FD probes with and without `-t 42`. Exact tuple `A8110/PICOA8110/Phoenix_ovs/Pico` is a software identity check only; owner-confirmed Pico 4 Pro hardware fact remains accepted project context. 13 matching synthetic processes, including a colon-name at index 13, preserve the exact name and reach FD probes; malformed names/protocol records fail closed. Existing pinned-path, dry-run, WSL `/bin/sh`, tab-byte/parser, Android 10 argv-join and `ps` framing checks remain. ADB client/server and Pico were not run by offline tests; synthetic results are not experimental PASS |
| M1-02 | Confirmation UX requires an interactive exact lowercase `yes`, then delegates to unchanged Python approval gate | `OFFLINE REGRESSION PASS` | PowerShell harness verifies exact yes succeeds and rejected `no`, empty, `YES`, unexpected text, trailing whitespace and noninteractive EOF make zero executor calls. Python gate regressions confirm these inputs do not satisfy the shared full token. Gate still validates approval ID/action/device/expiry/limits and is rechecked before each allowed command. Included in the totals recorded for M1-01 |
| M1-HW-15 | Owner-reported real M1.5 inventory outcome | `PARTIAL_PERMISSION_DENIED` | 10 ADB commands/10 records; Phoenix identity/build/release/kernel observed; 13 matching QuickCamera/PVR processes; first foreign `/proc/<pid>/fd` returned `PROC_ACCESS_DENIED`; collector stopped with 0 video-FD records. Accessibility of the other 12 processes remains unknown. This is not a PASS and is not upgraded by synthetic tests |
| M2-01 | Read-only node-metadata design and source ranking | `OFFLINE DESIGN COMPLETE` | Sysfs `name/index/dev` and `/dev/videoN` metadata ranked first. No device open/ioctl; process-FD, CameraService/Binder, image/frame access and timing are outside M2. Details in `P3-A6-M2-Read-Only-Camera-Metadata-Proposal.md` |
| M2-02 | Separate M2 PowerShell runner, native allowlist, fixed POSIX probes, approval gate, private evidence | `SYNTHETIC + POSIX INTEGRATION PASS OFFLINE` | Dedicated `P3A6CameraNodes.psm1` and runner. Exact default/`-t 42` vectors pass allowlist; pin to SDK ADB; exact interactive `yes`; hard caps 30 s/40 observations/16 nodes per source; archived evidence with source/probe hashes and integrity marker. M2 harness: 336 assertions; full suite and legacy M1 checks recorded in `P3-A6-M2-Handover.md`. No approval file or hardware result |
| M2-03 | Empty/inaccessible/malformed sources and private evidence behavior | `SYNTHETIC PASS` | Empty roots stay `NOT_OBSERVED`; inaccessible/partial sources can never yield overall `COMPLETE`. Independent valid fields remain in evidence with `PARTIAL_LIMITATIONS`. Permission denial, missing attributes, malformed/multiline values, symlink/non-character nodes, missing/incompatible/multiline `ls`, 16-node overflow, record-budget stop, timeout, identity mismatch, archive SHA and false safety flags are exercised against real local `/bin/sh` output and PowerShell parser |
| M2-HW-01 | Pico node metadata inventory | `NOT AUTHORIZED / NOT RUN` | Future run requires fresh `read-only-camera-node-metadata` approval (<=30 s, <=40 observations), one explicit/default transport and interactive exact lowercase `yes`. Installed Pico Toybox compatibility remains unknown until separately approved session. No M1 approval carries forward |

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

`MOCK + POSIX INTEGRATION PASS OFFLINE` подтверждает поведение collector на injected fixtures и POSIX shell parsing/quoting в WSL. Exact Android property tuple подтверждает только Phoenix-family software identity; Pico 4 Pro international Pico OS уже является owner-confirmed project fact, но Android tuple не выступает независимой hardware attestation. Offline results не являются ADB-to-device results и не повышают R1–R9. Открытый `/dev/videoN` fd без наблюдённого `ioctl(fd,0xc01856c0,...)` остаётся недостаточным для R1.
