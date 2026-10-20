# P3-C — Native Solver Replay на Pico-записях

Дата выполнения: 2026-10-20
Ветка: `feature/pico-support`
Фактическая исходная ревизия: `6f43cf3a602c0ad8a62e314e784016d7b0cf8d31`
Итог: **DATA_OR_CALIBRATION_BLOCKED**

## Граница выполнения и исходное состояние

Выполнен только offline replay уже сохранённых оптических записей на оригинальном QuestLHSync solver. ADB, Pico, SteamVR и Lighthouse не запускались; новые записи не снимались. Исходные TXT и calibration-файлы не изменялись и не добавлялись в Git.

При первом preflight запрошенный baseline `ae415083b429205bfe3b6820f09718c2bfa3f23d` отсутствовал в локальном Git object database: чистые `HEAD` и `origin/feature/pico-support` тогда указывали на `6f43cf3a602c0ad8a62e314e784016d7b0cf8d31`. До публикации origin продвинулся на пять документационных коммитов и включил требуемый baseline; после fetch изменений были проверены как doc-only и рабочий P3-C commit перебазирован на `ae415083b429205bfe3b6820f09718c2bfa3f23d`. Source work начиналась от `6f43cf3a602c0ad8a62e314e784016d7b0cf8d31`; force push не применялся.

## Реализация replay-only режима

Изменения затрагивают `src/tools/replay.cpp`, `src/driver/sync.h`, `src/driver/sync.cpp`, `build_replay.bat` и `pico/tests/test_p3c_native_replay.py`.

- `--pico-offline` распознаёт сохранённые `QPC-ns U F ...` записи, проверяет их поля и передаёт исходные `F ...` поля в существующий `Sync::OnLine()`. Точный QPC receive timestamp сохраняется как integer ns в replay audit; в `Sync::OnLine()` он передаётся в единицах секунд, как требует существующий интерфейс. Payload F не переписывается.
- Поддерживаются только C0/C3/C4/C5; `--pico-cameras upper` ограничивает replay C0/C3 без переписывания источника.
- `--pings` использует сохранённые Q-записи для штатного clock mapping; replay не подменяет native solver Python fitter-ом.
- Mapping является явной гипотезой: candidate C0→0, C3→1, C4→2, C5→3; альтернативная placement guess C0→0, C3→1, C4→3, C5→2. Ни одна не верифицирована.
- Числовой `HeadFromBody` transform отсутствовал. Выполнен только явно названный identity diagnostic control; он не является калибровкой. Replay меняет в памяти отдельную копию draft для прохождения production loader, но не сохраняет верифицированные флаги в calibration-файл и не меняет production loader/gates.
- Replay-only compile guard добавляет точные счётчики стадий: camera frames, clock/pose rejects, валидные rays, добавления в native solver, успешные кандидаты Acquire, причины отклонения кандидатов, принятые alignments и успешные Timing::Estimate. Макрос задан только для target `qlhs_replay`.
- Найден и исправлен дефект разбора Pico S-записей: фактический порядок — `serial channel x y z qw qx qy qz`; прежний общий parser ожидал channel в конце. Pico-режим теперь разбирает channel-first, при этом сохраняет стабильный внутренний alias serial для штатной логики solver. Parser обычного non-Pico режима не менялся. Результаты до этого исправления в итоговую матрицу не включались.

Тестами проверены сохранение QPC/F, strict malformed-frame rejection без echo входных полей, upper-camera filtering, обе mapping-гипотезы, проверки rigid transform, неизменность production calibration rejection, channel-first S, non-Pico P/S/Q/B backward compatibility и synthetic known geometry, достигающая принятого native alignment.

## Использованные записи

Использованы четыре ранее сохранённые сессии из `%LOCALAPPDATA%\QuestLHSync\recordings`. Полные SHA-256 исходников находятся только в приватном manifest.

| Сессия | Длительность | U/F кадров | P poses | S station poses | Q clock samples | B markers |
|---|---:|---:|---:|---:|---:|---:|
| 2026-10-15 19:15:06 | 78 s | 7,780 | 5,395 | 336 | 287 | 1,531 |
| 2026-10-15 20:22:05 | 48 s | 4,775 | 3,315 | 212 | 172 | 950 |
| 2026-10-15 20:26:05 | 418 s | 41,763 | 29,112 | 1,816 | 1,526 | 8,325 |
| 2026-10-15 21:29:39 | 474 s | 47,404 | 32,859 | 2,064 | 1,704 | 9,088 |

На 418-секундной записи были Lighthouse OFF/ON интервалы. 474-секундная запись — focused capture. Счётчики P/S/Q/B выше — записи файла, а не кадры или уникальные физические события.

## Реальные offline native replay результаты

Все 24 сохранённых запуска завершились с exit code 0. Матрица содержит 16 запусков (4 сессии × all/upper × baseline/learn), 6 timing-sensitivity запусков на 474-секундной записи (90/96/102 ms × all/upper) и 2 отдельные placement-guess запуски на этой записи.

| Сессия | Набор камер | Submitted frames | Blobs admitted | Native Solver::Add | Acquire candidates | Support rejects | Gain rejects |
|---|---|---:|---:|---:|---:|---:|---:|
| 78 s | all | 7,780 | 11,535 | 8,367 | 21 | 21 | 5 |
| 78 s | upper | 3,890 | 8,614 | 5,973 | 21 | 21 | 4 |
| 48 s | all | 4,775 | 5,138 | 4,362 | 13 | 13 | 13 |
| 48 s | upper | 2,388 | 3,774 | 3,208 | 13 | 13 | 13 |
| 418 s | all | 41,763 | 44,906 | 41,107 | 119 | 119 | 119 |
| 418 s | upper | 20,882 | 31,541 | 28,949 | 124 | 124 | 123 |
| 474 s | all | 47,404 | 86,520 | 79,870 | 137 | 137 | 102 |
| 474 s | upper | 23,702 | 49,789 | 45,853 | 144 | 144 | 126 |

Во всех восьми основных all/upper случаях каждый Acquire candidate был отклонён на support gate; принятых alignments — 0, final condition — false, median residual — NA, lock episodes/duration — 0, успешных `Timing::Estimate` — 0. Во всех Learn-вариантах итоговые PICO метрики совпали с соответствующим baseline; exposure осталась 18 ms, `timing_learned=false`.

Для каждой камеры `FrameGrid` обучил период примерно 40 ms. По четырём сессиям диапазон составил 39.997–40.004 ms. Для focused 474 s candidate/all: C0/C3/C4/C5 соответственно дали 11,851 кадр на камеру; valid rays — 13,022 / 34,162 / 16,686 / 18,180; solver additions — 12,709 / 33,144 / 16,299 / 17,718. Clock-map failures — 7 / 7 / 6 / 6, pose failures — 642 / 1,743 / 871 / 940 blobs. Наличие rays и многочисленных `Solver::Add` не означает достаточный Lighthouse consensus.

Статус показал четыре station channels `7, 13, 10, 1`, однако во всех сохранённых status samples их accepted support был нулевым. Native Acquire proposals возникали, но не прошли support threshold; этот факт не доказывает, что камеры не видели станции.

### Чувствительность

- Candidate mapping и placement guess дали одинаковые stage counts и число Acquire candidates: 137 all / 144 upper. Ни одна mapping-гипотеза не дала accepted alignment или timing estimate. Разница gain-rejection counters не является доказательством правильности mapping.
- При forced exposure 90/96/102 ms на 474 s candidate mapping сохранялось 138 Acquire candidates all и 142 upper; все отклонены по support. Accepted alignment, condition и timing estimate оставались нулевыми.
- В Learn runs штатный timing learner не достиг успешного `Timing::Estimate`; поэтому равенство baseline/Learn не подтверждает правильность 96 ms и не исключает иной временной offset.
- Identity `HeadFromBody` использовался только как диагностический контроль. Поскольку независимого числового transform нет, все результаты зависят от неверифицированной позной гипотезы и не могут классифицировать способность native solver на корректной Pico-калибровке.

### Lighthouse OFF/ON интерпретация

На 418 s записи были проверены интервалы OFF→ON каналов 13, 10, 1 и 7 (примерно 36.089–48.433 s); на 474 s — три сохранённых интервала канала 1/10 (36.082–47.938 s). Максимальные target и other station support counters равнялись нулю до, во время и после интервалов. Поскольку ни один alignment не принят, это **не** подтверждает невидимость выключенной станции и не измеряет optical on/off response.

## Решение

Итог **DATA_OR_CALIBRATION_BLOCKED**, а не `NATIVE_SOLVER_NO_FIT`: реальные записи корректно поданы в оригинальный native pipeline, Q mapping, frame grid и optical rays наблюдались, Acquire кандидаты были, но единственная `HeadFromBody` проверенная в этом replay гипотеза — явно недостоверная identity control; корректной числовой позной калибровки нет. Поэтому по этим результатам нельзя заключить, что native solver не способен получить consensus на корректной калибровке.

**Следующий практический шаг:** получить обоснованный числовой 4×4 `HeadFromBody` в тех же координатных базисах из существующего независимого измерения/калибровки. После этого прогнать focused 474 s candidate mapping baseline на all/upper и проверить результат на held-out 418 s записи, не подбирая гипотезу по held-out сессии. Пока это условие не выполнено, дальнейший перебор timing offsets неинформативен.

## Тесты и приватное evidence

- `cmd /c build_replay.bat` — exit 0; собраны `out\qlhs_replay.exe` и `out\qlhs_nettest.exe`. Скрипт вывел существующее предупреждение `'Fastboot++\' is not recognized`, но оба компилятора завершились успешно.
- `python -m unittest discover -s pico/tests -p 'test_*.py'` — **297 tests, PASS**.
- `python -m unittest pico.tests.test_p3c_native_replay -v` — **11 tests, PASS**.
- `git diff --check` — PASS.
- Свежая повторная сборка после replay имеет SHA-256 `a5bcb732f473e9c7622396a53c2af412721b2cbdc3a8d77dc61409e7d860e240`. Сохранённые run summaries фиксируют SHA-256 executable, реально использованного в 24 запусках: `18ee31bca806462bf64c4c6b56811fe055b416b9cf7776d1cd00e5c06a4d2b71`. Сам executable в ZIP не включён, поэтому побайтовое повторное сравнение run binary с текущей пересборкой невозможно; текущая пересборка прошла целевые и полные offline regressions.
- Приватный пакет: `%LOCALAPPDATA%\QuestLHSync\private-evidence\p3c-native-replay-20261020T080048Z\P3C-Native-Replay-Evidence.zip`; SHA-256 `65e529f271958cb6aa2412a3c66f0606a14b135a65a6c350f19a848146f05ff9`. Совпадение проверено PowerShell `Get-FileHash`, Python `hashlib` и sidecar; ZIP CRC test прошёл, 80 entries. В архив не включены исходные записи и calibration ELF/файлы. Run outputs проверены на строки с raw station serials: совпадений 0 в 48 stdout/stderr файлах.
- Пакет и manifest сохраняются локально приватно; в Git включается только этот исследовательский отчёт, handover и source/tests.

## Safety gates

Не менялись и остаются `false`: `exact_time`, `mapping_verified`, `pose_verified`, `shared_buffer_identity_verified`, `frame_meta_bridge_verified`, `physical_event_verified`, `live_lighthouse_correction_allowed`.

Ни один offline native replay результат не разрешает live Lighthouse correction.
