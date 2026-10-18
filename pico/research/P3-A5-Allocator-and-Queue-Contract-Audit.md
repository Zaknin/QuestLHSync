# P3-A5 — Final Offline Allocator and Queue Contract Audit

Дата: 2026-10-18. Репозиторий `C:\Dev\PicoLHSync`, branch `feature/pico-support`; исходный HEAD этой задачи: `e3f04c53b5fa0a71704d40303011b30042af209e`. Исследование только по локальным SHA-pinned ELF, локальным файлам и публично доступным исходникам. Устройство, ADB, драйверы, службы и прошивка не затрагивались.

## Итог

| Вопрос | Вердикт | Основание |
|---|---|---|
| Какой `CSLAlloc` реализован в Pico и совпадает ли он с найденным CamX кодом? | **BLOCKED** | В локальном наборе нет ELF, определяющего `CSLAlloc`, или matching CamX sources. Найденный публичный source mirror показывает аналогичный путь allocation → FD → `mmap`, но его происхождение/ветка не привязаны к PICO OS build. |
| Гарантированы ли producer CPU VA и экспортируемый FD как один DMA-BUF/ION backing allocation? | **UNKNOWN / BLOCKED** | P3-A4 подтверждает, что producer использует ID, pointer и FD из одного возвращённого record; PVR отдельно отображает переданный FD. Нет exact allocator implementation и kernel allocation handler, которые доказали бы backing object/pages. |
| Почему ID находится в `m.userptr` и вернётся ли он из DQBUF? | **PARTIAL / BLOCKED** | Пользовательская часть ELF доказана. Оба внутренних `0xc058...` кода передаются через custom outer `ioctl(0xc01856c0)` envelope; kernel dispatch/copy-back implementation не найден. Успешный userspace dequeue использует полученное значение как lookup key, но равенство исходному ID не проверяет. |
| Какой фактический `/dev/videoN` использует этот `VideoQueueUtil` fd? | **UNKNOWN** | PVR открывает динамический path; ELF не содержит имени node. Исторический process inventory сужает варианты, но не сопоставляет fd конкретному node. |

**Рекомендация:** закрыть ограниченную offline-фазу как документированную с двумя явно заблокированными контрактами. Возобновлять только при появлении exact-source/kernel материала, связанного с PICO build fingerprint, либо в отдельной аппаратной фазе с разрешённым протоколом. Из доступных доказательств нельзя включать buffer identity или queue roundtrip gates.

## 1. CSLAlloc: локальный поиск и публичный analogue

### Локальная PICO реализация

Поиск по сохранённым PICO ELF/source наборам не нашёл реализацию `CSLAlloc`. SHA-pinned `quickcamera.core.so` содержит неопределённый dynamic import `CSLAlloc`; среди доступных локальных ELF он единственный совпадающий symbol hit и не является provider. Локальные P3 producer/HIDL файлы также не включают соответствующий CamX source tree или version-matched kernel memory-manager code. Предыдущие bounded searches по репозиторию и локальным source/download roots не нашли matching implementation.

P3-A4 по producer ELF (`quickcamera.core.so`, SHA-256 `fb22355acd35b9772a5538a7d1c49175641165ad0368e7c47e5831f5f1727017`) статически подтверждает только use-sites одного allocator result record:

- `0x36964`: вызов внешнего `CSLAlloc`;
- `record+0x00`, прочитанный в `0x36a74` и записанный в `0x36a7c`: queue/buffer ID;
- `record+0x08`, использованный в `0x36a58..0x36a80`: CPU pointer, помещаемый в producer map;
- `record+0x14`, прочитанный в `0x36a68` и записанный в native handle fd slot в `0x36a70`: FD, который экспортируется дальше.

Это доказывает use-site relationship между полями record, но не семантику внешнего allocator или тождество физических страниц за pointer и FD.

### Публичный source mirror

Найдено публичное зеркало `MDNSSKNGHT/CAMX_SAIPAN_LA.UM.8.13.R1`, pinned commit `6d0bfb84243a5edc6f4340ce9f103dcc56862b7c`. Source files содержат copyright notice Qualcomm Technologies, 2016–2020, и пометку “Confidential and Proprietary”. Это не authenticated Qualcomm upstream snapshot и не подтверждённый source drop для PICO OS 5.11.2 / Android 10. Поэтому ниже он используется только как **аналогичный пример реализации**, не как доказательство поведения Pico.

В этой ветке:

1. Публичный `CSLAlloc` dispatch вызывает функцию из выбранной CSL jump table; сама публичная API-функция не фиксирует HW backend.
2. `CSLAllocHW` готовит `cam_mem_mgr_alloc_cmd` с length/alignment и вызывает `CAM_REQ_MGR_ALLOC_BUF`. Ответ содержит buffer handle, FD и length; затем те же значения передаются в `CSLHwAddBuffer`.
3. При `CSLMemFlagUMDAccess` и отсутствии protected flags `CSLHwAddBuffer` вызывает `MemMap(fd,length,0)` и записывает в `CSLBufferInfo` handle, результат mmap как `pVirtualAddr`, тот же FD и size.
4. Публичный Linux `MemMap` использует `mmap(NULL,len,PROT_READ|PROT_WRITE,MAP_SHARED,fd,offset)`.

Source references pinned к тому же mirror commit: [`CSLBufferInfo` и flags](https://github.com/MDNSSKNGHT/CAMX_SAIPAN_LA.UM.8.13.R1/blob/6d0bfb84243a5edc6f4340ce9f103dcc56862b7c/camx/src/csl/camxcsl.h#L303-L318), [`CSLAlloc` jump-table dispatch](https://github.com/MDNSSKNGHT/CAMX_SAIPAN_LA.UM.8.13.R1/blob/6d0bfb84243a5edc6f4340ce9f103dcc56862b7c/camx/src/csl/camxcsl.cpp#L499-L518), [`CSLAllocHW`](https://github.com/MDNSSKNGHT/CAMX_SAIPAN_LA.UM.8.13.R1/blob/6d0bfb84243a5edc6f4340ce9f103dcc56862b7c/camx/src/csl/hw/camxcslhw.cpp#L2030-L2152), [`CSLHwAddBuffer`](https://github.com/MDNSSKNGHT/CAMX_SAIPAN_LA.UM.8.13.R1/blob/6d0bfb84243a5edc6f4340ce9f103dcc56862b7c/camx/src/csl/hw/camxcslhwinternal.cpp#L3532-L3593), [`MemMap`](https://github.com/MDNSSKNGHT/CAMX_SAIPAN_LA.UM.8.13.R1/blob/6d0bfb84243a5edc6f4340ce9f103dcc56862b7c/camx/src/osutils/camxosutilslinux.cpp#L3440-L3475), [`CSLBufferCacheOpHW`](https://github.com/MDNSSKNGHT/CAMX_SAIPAN_LA.UM.8.13.R1/blob/6d0bfb84243a5edc6f4340ce9f103dcc56862b7c/camx/src/csl/hw/camxcslhw.cpp#L2352-L2403).

В этом source mirror userspace явно отображает тот FD, который вернул kernel allocation request. Этого достаточно, чтобы показать ожидаемую software-схему VA+FD в этой ветке. Этого недостаточно, чтобы доказать, что конкретный kernel handler создал один DMA-BUF/ION object, что Pico использует этот backend или что Pico `CSLBufferInfo` имеет идентичный ABI.

### Cache coherency

Найдено два ограниченных свидетельства:

- В matching PICO producer ELF присутствует import `CSLBufferCacheOp`. В `CamQuickAccessDevice::StreamOn` по адресу `0x383f0` вызывается PLT target с `w0=handle` (handle загружен перед call), `w1=1`, `w2=0`. ELF доказывает именно вызов с этими аргументами на этом пути. Имена аргументов/значение invalidate-only следуют из одноимённой публичной API сигнатуры в найденном mirror; без совпадения versioned implementation это не подтверждает результат cache operation в Pico.
- В mirror `CSLBufferCacheOpHW(handle,invalidate,clean)` переводит комбинацию флагов в `CAM_REQ_MGR_CACHE_OPS`. `mmap(MAP_SHARED)` сам по себе не является доказательством cache coherency. Ни вызов kernel op, ни его completion/барьеры/действие на аппаратные cache domains не могут быть перенесены из другой версии на PICO kernel.

Итак, более точный вывод — producer просит cache operation как минимум в одном статическом пути; общая coherency-гарантия между producer CPU mapping, камерным hardware и PVR mapping остаётся **UNKNOWN**.

### Provenance/ABI вывод

Matching PICO allocator ELF, exact `CSLBufferInfo` definition, его build ID/source mapping и подходящий request-manager memory handler не найдены. Источник mirror имеет иную публичную ветку `LA.UM.8.13.R1`; никакого доказательства, что она соответствует PICO build fingerprint, нет. Объявлять ABI/version match нельзя. Backing identity остается закрытым gate: `shared_buffer_identity_verified=false`, `frame_meta_bridge_verified=false`.

## 2. QBUF/DQBUF и kernel boundary

Исследован локальный `libpvrtrackingcamera.so`, SHA-256 `cf9e507f412ec33d62c2f720669fcdd093f1822c9cbf3adefd0a26a6b4d072ee`. Адреса — VA этого ELF.

### Пользовательские аргументы

- `VideoQueueUtil::EnQueVbQueueBuffer(unsigned short,int,bool)`, extent `0x6b9a4..0x6baa0`: приводит index к `u16`; пишет `memory=2` (`V4L2_MEMORY_USERPTR`); sign-extends 32-bit ID через `sxtw` и сохраняет его в структуру по `+0x40`, то есть в union field `m.userptr`; зовёт wrapper в `0x6ba10` с `op=0xc058560f`, pointer на структуру и `size=0x60`.
- `VideoQueueUtil::DeQueVbQueueBuffer(int*,bool)`, extent `0x6b378..0x6b4a4`: выставляет memory type 2; в `0x6b418` зовёт тот же wrapper с `op=0xc0585611`, structure pointer и `size=0x60`; после успешного wrapper return загружает `+0x40` и записывает младшие 32 бита в caller `int*` (`0x6b458..0x6b45c`).
- `PrepareStreamOn` (`0x6a92c..0x6a940`) берёт каждый `ids[i]`, вызывает enqueue и строит lookup tree с тем же userspace ID и `buf_info[i]`. `DeQueueFrame` использует dequeue output как lookup key (`0x6b720..0x6b7f8`).

Коды `0xc058560f` и `0xc0585611` совпадают с номерами/формой V4L2 QBUF/DQBUF command values; закодированный в них размер равен `0x58`, тогда как `CSLHwInternalDefaultIoctl2` получает payload length `0x60`. Это наблюдение о значениях и аргументах, а не утверждение о kernel semantics.

### Найденный wrapper

`CSLHwInternalDefaultIoctl2(unsigned int,void*,unsigned int)` — отдельный динамический symbol в том же PVR ELF, VA `0x6c2f8`, размер `0xe0`, точный extent `0x6c2f8..0x6c3d8`. Новая bounded trace regression захватывает этот symbol по dynamic-table extent.

Внутри wrapper:

| Адрес | Наблюдаемая операция |
|---:|---|
| `0x6c30c` | записывает ноль и payload pointer в envelope offsets `+8` и `+16` |
| `0x6c310` | записывает inner `op` и `size` в envelope offsets `+0` и `+4` |
| `0x6c318` | загружает fd из `this+0x84` |
| `0x6c320..0x6c328` | формирует outer request `0xc01856c0` |
| `0x6c32c` | вызывает libc `ioctl(fd,0xc01856c0,&envelope)` |
| `0x6c330..0x6c338` | при outer success возвращает 0 |

Envelope размером 24 bytes имеет поля `{inner_op:u32, payload_size:u32, zero:u64, payload_ptr:u64}`. Wrapper переупаковывает аргументы, но не меняет байты inner `v4l2_buffer` и не превращает ID в адрес. После вызова kernel получает outer request и pointer, через который может читать/изменять payload. Как outer handler dispatch-ит inner request, валидирует length и копирует ли `m.userptr` назад, без kernel source неизвестно.

### Device node

`PrepareStreamOn` по `0x6a788..0x6a7e0` берёт путь из объекта QuickCamera и вызывает `open(path,0x802)`; fd сохраняется в объекте VideoQueueUtil по `+0x84`. Этот же offset читает wrapper в `0x6c318`. Имя `/dev/videoN` не является literal в pinned ELF, путь создаётся динамически.

В архивном root process inventory от 2026-10-13 процесс QuickCamera service держал `/dev/video1` (`hub_cam-req-mgr`) и `/dev/video3` (`hub_cam_sync`). Это историческое evidence о process ownership, а не доказательство, какой из этих двух fds хранит конкретный `VideoQueueUtil`. Операция внешне похожа на request-manager ioctl и поэтому `/dev/video1` — правдоподобная гипотеза, но точный node оставлен **UNKNOWN**.

### Kernel handler и возврат ID

Локальный Android NDK `videodev2.h` определяет generic `V4L2_MEMORY_USERPTR=2` и стандартные QBUF/DQBUF command values. Это только UAPI declaration; в системе не найден PICO kernel tree, request-manager ioctl2 handler, cam-sync handler или точная vendor video queue implementation, которая обрабатывает внешний `0xc01856c0`.

Поэтому подтверждено только следующее:

1. PVR передаёт signed-extended ID в payload field `m.userptr`.
2. Userspace wrapper не преобразует этот field и передаёт kernel pointer на payload через outer ioctl envelope.
3. При successful outer ioctl DQBUF helper возвращает значение, которое оказалось в payload `+0x40`; PVR применяет его как key.
4. Код PVR не сверяет output с queued ID. Exact equality может быть гарантирована только соответствующим kernel/custom handler или runtime observation, которых нет.

Обычное значение USERPTR как адрес памяти здесь нельзя автоматически назначать proprietary outer handler. Так же нельзя утверждать, что драйвер возвращает исходный ID: handler может переписать поле, отклонить такой вызов или использовать vendor-specific mapping. Queue roundtrip остаётся **PARTIAL/BLOCKED**.

## 3. Проверка proof matrix и изменений статусов

Обновлён [P3-A4-Proof-Matrix.md](P3-A4-Proof-Matrix.md):

- userspace QBUF/DQBUF field flow остаётся **PARTIAL**, но теперь причина точно ограничена custom outer ioctl2/kernel contract, а не предполагаемым стандартным USERPTR roundtrip;
- добавлены **STATIC PASS** для wrapper envelope и producer `CSLBufferCacheOp` callsite/args;
- точный `/dev/videoN` отмечен **UNKNOWN**;
- CSL producer pointer ↔ PVR FD mapping отмечен **UNKNOWN/BLOCKED**; публичный mirror остаётся только analogue, не закрывает этот gate;
- прежние статические выводы P3-A4 по count/order, mmap arguments, metadata offset, timestamp copies и callback relocation не меняются.

Текущие gates сохранены без изменения:

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

## 4. Проверки и ограничения

Добавлен узкий integration regression `pico/tests/test_p3a5_ioctl2_trace.py`: он запускает приватный P3-A4 extractor на локальном SHA-pinned наборе в temp output root, проверяет новый schema и точный wrapper symbol/extent `0x6c2f8..0x6c3d8`, затем удаляет только созданный им private build folder. Он проверяет воспроизводимость bounded static evidence, а не закрытый kernel contract.

Новый regression сначала упал ожидаемым образом: текущий tracer выдавал schema v3 и не включал wrapper extent; после добавления bounded exact-symbol window проверка прошла. Полная команда `python -m unittest discover -s pico/tests -v`: **177 tests, OK**. Трасса использовала SHA-pinned локальные ELF/NDK и temp output root; созданный private build folder удалён тестом. `git diff --check` завершился с code 0 (Git вывел ожидаемые line-ending warnings о LF→CRLF). Все проверки offline. Не запускались ADB, camera service, device probe, драйверные изменения или runtime операции. В публичный Git не добавлены ELF или full disassembly.

## 5. Что ещё нужно для закрытия вопросов

Следующее полезное исследование должно начинаться только с материалов, точно привязанных к PICO fingerprint `Pico/Phoenix_ovs/PICOA8110:10/5.11.2/smartcm.1725996131:user/dev-keys`:

1. Qualcomm CamX/CSL source drop или ELF, реально экспортирующий `CSLAlloc` и `CSLBufferCacheOp`, включая build ID и ABI headers.
2. Version-matched kernel source для outer request `0xc01856c0`: request-manager dispatcher и `CAM_REQ_MGR_ALLOC_BUF` / `CAM_REQ_MGR_CACHE_OPS` handlers.
3. Точная kernel-side queue handler для inner QBUF/DQBUF operations и данные, однозначно связывающие открытый fd с device node.

Если такой source пакет недоступен, следующие доказательства требуют отдельной аппаратной проверки: какой node фактически открыт, сохраняется ли ID при успешном QBUF/DQBUF, совпадают ли producer CPU contents с PVR mapping и какое cache operation реально обеспечивает видимость. Это потребует отдельного протокола и не входит в offline результат.
