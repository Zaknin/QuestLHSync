# PicoLHSync / QuestLHSync — промпт для нового диалога в проекте Pico4 Stuff

Продолжаем разработку **PicoLHSync (QuestLHSync Pico 4 Pro support)**. Это **новый диалог внутри того же проекта ChatGPT**, а не новая разработка с нуля. Ты — ведущий технический исследователь и разработчик: действуй доказательно, проактивно и не повторяй уже выполненные тесты P1/P2.

**Сначала прочитай:**

1. [Полный handover P2→P3](P2-to-P3-FULL-HANDOVER-20261017.md) — основной источник истины.
2. [P2 closeout и P3 proof gates](P2-Closeout-P3-Clock-Provenance-20261017.md).
3. [Полная native K0/slot130 реконструкция](P2-K0-SourceAndSlot130-20261016.md).
4. [pico/README.md](../README.md) и релевантные исходники.

**Репозиторий:** https://github.com/Zaknin/QuestLHSync — **ветка `feature/pico-support`**. Мой локальный checkout Windows 11 — `C:\Dev\PicoLHSync`, PowerShell 7.6.6. Используй подключённый GitHub, проверь текущий HEAD, сам читай/коммить проверенные изменения, затем подтверждай их read-back. Pico 4 Pro (PICO OS 5.11.2, root) сейчас **выключена**; зато можно работать с **Pimax Crystal + SteamVR** на этом ПК. Не требуй включения Pico, если задача может решаться offline.

> **Текущий статус P3-D (2026-10-20):** P3-C станционные записи повторно классифицированы: четыре сохранённые сессии содержат raw channel-first и transformed channel-last `S` rows; прежние 24 метрики не затронуты, но найден отдельный synthetic integer-`x` parser edge и добавлен строгий regression. Числовой `HeadFromBody` в доступных fitting/candidate материалах отсутствует (`HEAD_FROM_BODY_SOURCE_UNAVAILABLE`); identity остаётся только диагностическим контролем. Не повторять native replay и не подбирать timing offsets до независимого измерения transform. См. [P3-D HeadFromBody and Native Replay](P3-D-HeadFromBody-and-Native-Replay.md). Следующий полезный шаг — отдельно разрешённая оптическая metrology-калибровка factory body frame ↔ OpenVR HMD head frame; все safety gates остаются false.

### Что уже доказано

- P1 camera K0 read-only Binder/ashmem reader + PFR1 + upstream blob detector + QuestLHSync F/T TCP transport **работает**. Это НЕ готовая Lighthouse correction. `F` пока использует `copied_ns/1000`, `hs_calibration` fail-closed, оптическая registration не завершена.
- Запись K0: **1204 кадров**, по 301 для C0/C3/C4/C5, `slot+114 == slot+122`. Во всей записи `slot122-slot130=225997ns` точно. Native code: `T130=T122-52000-A-((B*E) ASR 1)`; `E=4` — metadata code, **не** измеренная оптическая экспозиция.
- Две реальные ROM пары: CameraManager ctor VA `0x73170` — `B=19069,A=133483` (223621ns); ConfigManager VA `0x73160` — `B=19333,A=135331` (225997ns). ConfigManager сохраняет альтернативную пару в `+0xA0`. **Прямая передача к активным camera A/B не доказана**. Хватит гоняться за 2376 ns без новых фактов.
- Native QuickCamera callback и CameraManager K0 routing статически восстановлены, internal indices `0,1,2,3` соответствуют manager IDs `0,3,4,5`. **Аппаратный источник** `FrameMetaDate.first_u64`, его физический event (SOF/exposure/readout) и active listener binding пока не подтверждены. QTIMER ↔ CNTVCT_EL0 порядка 19.2MHz plausibility — ещё **не** Pico↔PC clock calibration.
- Заводская Omni+Radtan geometry частично проверена, но factory-camera mapping и `HeadFromBody` не прошли финальную оптическую проверку.

### Неприкосновенные условия

`OBSERVE ONLY`, `exact_time=false`, `live_lighthouse_correction_allowed=false`, `mapping_verified=false`, `pose_verified=false` до независимых доказательств. Не вмешиваться в SLAM, vendor services/firmware, HMD calibration, SteamVR driver/poses или живые `F` timestamps. Никаких ручных «исправлений» QTIMER на 4.7465 сек. Не коммитить приватные ELF/CSV/factory calibration; они находятся локально в `pico/build/*-private-*`.

### Историческая задача этого handover: **P3-B, host-only OpenVR + Windows QPC probe**

Этот пункт описывает исходный scope предыдущего handover; P3-C выше — текущий актуальный этап. Не начинать заново P3-B только по этому историческому тексту.

1. Посмотри, есть ли в репозитории готовые подходящие API/helpers; проверь актуальные официальные исходники/документацию OpenVR, не выдумывай прототипы и версии.
2. Предложи минимальную read-only архитектуру и unit-test план; **реализуй** безопасный host-side probe в ветке `feature/pico-support` с mock tests, fail-closed behavior и документацией.
3. Читай OpenVR pose, например через официальную `IVRSystem::GetDeviceToAbsoluteTrackingPose(origin, prediction_seconds=0)`, ограничивай каждый вызов QPC `before/after`, сохраняй integer ticks, frequency, origin, prediction, device ID, connected/valid, tracking result, pose matrix/velocity и интервал вызова. **Не выдавай** QPC midpoint или API pose при prediction=0 за настоящий sensor acquisition timestamp.
4. Дай одну короткую команду PowerShell для opt-in проверки **на Pimax Crystal** и точную интерпретацию того, что этот тест докажет и чего не докажет. Ничего не менять в работающем драйвере.
5. Поддерживай P3-A backlog: когда я сам снова включу Pico, нужен read-only inventory и локальное копирование именно установленных QuickCamera/HIDL producer libraries для определения реального источника первого FrameMetaDate word. Пути и имена не угадывать, никакого переснятия старого K0 без новой конкретной гипотезы.

Отвечай на русском. Не задавай повторных вопросов с известными ответами. Чётко разделяй **static proof / synthetic test PASS / user Windows-run PASS / physical validation PASS**. Работай с репозиторием напрямую там, где можешь; не поручай мне вручную собирать длинные скрипты. После чтения handover приступай к первому безопасному P3-B шагу.
