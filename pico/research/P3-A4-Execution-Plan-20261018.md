# P3-A4 QuickCamera provenance execution plan

**Goal:** Завершить максимально возможное статическое доказательство передачи QuickCamera timestamp metadata от CSL producer до PVR `FrameMetaDate`, сохранив неизвестные и safety gates.

**Approach:** Использовать только SHA-pinned локальные ELF, NDK LLVM, Python и PowerShell. Расширить существующую трассу, проверить отдельную модель данных тестами, опубликовать полные дизассемблирования только в приватный P3-A пакет и оформить производные выводы в `pico/research/`.

**Constraints:** Без Pico/ADB, runtime или сервисов, изменения бинарников, live correction, публичных ELF/full disassembly и изменения любых safety gates. Сохранить все существующие данные. Все новые выводы помечать как статические; физический SOF, clock synchronization, pose и backing-store identity не выводить из одних только похожих layouts.

## Задачи и контрольные результаты

1. [x] **Тестируемая модель:** RED→GREEN tests проверяют ABI sizes/widths, count/order handles и IDs, metadata bounds, fallback request-ID divergence и запрещённые timestamp claims.
2. [x] **Приватная трасса:** PowerShell tracer охватывает full `startPreview`, HIDL `converttoHidl`, producer request/fence и callback veneers; runtime execution завершён на SHA-pinned ELF; ZIP/manifest/marker прочитаны с SMB обратно.
3. [x] **Исследовательские отчёты:** созданы Full Buffer Provenance, Timestamp Semantics, Proof Matrix, Handover и Worklog; отдельно указаны `client+0x60` IDs и metadata offset в `+0x74`.
4. [x] **Проверка и публикация:** все 176 offline Python tests прошли; актуальные trace и RELR evidence packages/markers независимо прочитаны и хэши совпали; изменения прошли независимое review. Далее — staged diff/privacy check, local commit и обычный push в целевую ветку.

## Открытая оговорка модели

`CSLAlloc` импортирован из внешнего Qualcomm runtime. Исследованные ELF связывают allocator record, exported native-handle FD, producer CPU address, HIDL order и PVR mmap record, однако это само по себе не раскрывает внутреннюю гарантию Qualcomm о тождестве backing pages для CPU pointer и FD. Это утверждение останется ограниченным статически наблюдаемой связью, пока не найден локальный контракт CSL.

## Ход выполнения

- 2026-10-18: исходная ветка чистая и совпадает с `origin/feature/pico-support` на `def417f588e296e03268c84082248132397d55a3`; приватные ELF доступны и их SHA проверены в текущей сессии.
- Решение: работать в указанном пользователем чистом checkout `feature/pico-support`; не создавать параллельный worktree, поскольку пользователь прямо указал рабочую ветку и разрешил коммит/обычный push именно в рамках неё.
