# P3-A6 — Risk and Permissions

Дата: 2026-10-19. Это оценка будущего эксперимента, не разрешение на его выполнение. Pico 4 Pro на international Pico OS — установленный факт владельца. Последний owner-run M1.5 завершился `PARTIAL_PERMISSION_DENIED`; текущая M1.6/M2 работа была offline-only. Все новые M2 действия остаются **NOT AUTHORIZED / NOT RUN**.

## Классы наблюдения

| Класс / метод | Что можно узнать | Root / PICO OS 5.11.2 | Риск тайминга и потока | Доверие и границы |
|---|---|---|---|---|
| **Read-only inventory:** build props, kernel release, process list | Build identity, найти QuickCamera/PVR процессы | ADB shell нужен после отдельного разрешения; root не обязателен для части props/process list, но SELinux может скрыть процессы | Низкий, краткий системный overhead; читать без запуска камеры | Хорошая системная inventory, но не связывает VideoQueueUtil fd и node |
| **M2, при отдельном разрешении:** `/sys/class/video4linux/videoN/{name,index,dev}` read-only | Имена зарегистрированных V4L class entries, class index и major:minor | Обычный shell; traversal/read разрешения зависят от DAC/SELinux конкретного build. Denial фиксируется, обхода нет | Очень низкий ожидаемый overhead от ограниченного чтения; vendor sysfs handlers и scheduling не проверены. Ограничить до 16 nodes и 40 records | Подтверждает sysfs node metadata на время чтения; не связывает node с QuickCamera/PVR fd, ioctl, очередью или кадром |
| **M2, при отдельном разрешении:** `/dev/videoN` node metadata | Наличие character node, numeric mode/owner/group и major:minor | Обычный shell; только `ls -ln` по строго ограниченному пути, без open. DAC/SELinux могут запретить | Очень низкий; не открывать node и не вызывать ioctl; ограничить до 16 nodes | Подтверждает только node metadata; номер не является стабильной камерой и не доказывает владельца/использование |
| **M1.5 result / возможный M2 follow-up:** per-process `/proc/<pid>/fd` symlink listing | Может определить, виден ли `/dev/videoN` у каждого QuickCamera/PVR PID | Последний M1.5 запрос на первом PID получил `PROC_ACCESS_DENIED`; доступ к другим 12 процессам неизвестен. Только обычный shell, без root/su/SELinux bypass; process scope требует нового approval | Низкий–средний при максимум 13 PID; каждый PID перепроверить перед чтением, denial записать отдельно и продолжать только если это явно входит в новую approval | Видимый symlink показывает process→open-node association в момент снимка, не связь с конкретным `VideoQueueUtil` ioctl. Не читать fdinfo/maps/contents |
| **Не включать в первый M2 scope:** `dumpsys media.camera` | Потенциально Android logical camera IDs и active CameraService client/provider state | Нужны доступность команды и подходящие DUMP/SELinux permissions; PICO policy неизвестна | Средний/неопределённый: может проходить через service locks и выдавать большой output с package/PID/event/vendor data; не считать безвоздействующим | AOSP reference не доказывает PICO поведение; не устанавливает PVR queue fd или physical timing. Отложено до отдельного обоснования |
| **Passive observation:** snapshot уже существующих целевых log records | CSL request ID, QTIMER-labeled value, диагностические metadata values, если их уже логируют | Обычно shell/logcat доступ, но tags/records могут быть скрыты. Не включать logging flags | Низкий–средний; log reader и передача добавляют нагрузку, но не меняют camera stream | Подтверждает только записанные значения/label. Не доказывает timestamp event semantics или fallback без явного marker |
| **Passive observation:** уже существующий trace/log artifact | Предыдущие process/ioctl/event observations, если были включены штатно | Нужен доступ к приватному артефакту; наличие неизвестно | Съём файла может потреблять I/O, но live camera path не меняет | Может не соответствовать текущему build/session; проверять дату/build и происхождение |
| **Instrumentation, отдельное разрешение:** read-only ptrace/syscall observer для внешнего `ioctl` envelope и nested `m.userptr` | Outer ioctl fd/node attribution; QBUF/DQBUF raw ID roundtrip | Обычно ptrace permission/root или same-UID; Android 10 SELinux/vendor policy могут запретить даже с root. Debug symbols не обязательны для известных статических envelope offsets | **Высокий** относительно passive: ptrace останавливает/планирует процесс; риск queue jitter, timeout и dropped frames | Может показать observed userspace bytes до/после syscall, но не объясняет kernel semantic guarantee и не исключает observer-induced timing changes |
| **Instrumentation, отдельное разрешение:** read-only ftrace/eBPF/perfetto/atrace, если kernel/build поддерживает нужные events | Kernel outer ioctl call timing, PID/TID/fd/request; возможно vendor tracepoints | Root/debugfs/tracefs policy и конкретные events неизвестны; Perfetto/atrace availability не предполагать | Средний–высокий; event volume и tracing buffer могут менять latency/CPU | Без vendor handler tracepoint payload не доказывает DQBUF userptr copy-back. Не запускать до отдельного разрешения |
| **Instrumentation, отдельное разрешение:** read-only process-memory snapshot только по allowlisted metadata/structure fields | `FrameMetaDate` и ioctl payload при наличии адрес/offset mapping | Обычно ptrace/root и разрешение SELinux; не считать доступным | Высокий: attach/read races, stop-the-world, cache/TLB effects; metadata может изменяться параллельно | Не читать image region; snapshot — момент наблюдения, не согласованный frame boundary |
| **Не разрешать в первоначальной диагностике:** менять callbacks, hooks/patches, запись в process memory, debug logging toggles, Camera2 session, frame dump, cache op, service/camera reconfigure, APK/agent install, vendor/kernel/firmware edits, SteamVR/Lighthouse correction | Могут изменить поведение камеры, буферизацию или tracking | Не применимо | Потенциально высокий и трудно обратимый | В initial phase запрещены; не нужны для M1/M2. Любое последующее рассмотрение требует отдельной задачи/разрешения и нового risk review |

## Точные permission gates

Перед первым подключением владелец должен отдельно разрешить **конкретную** сессию. Разрешение на исследование не означает разрешение на hardware execution.

Одобрение должно определить:

1. Целевое устройство `Pico 4 Pro`, ожидаемый режим и время проведения.
2. Ровно одно разрешённое действие на approval record: например, сначала `read-only-inventory`, затем отдельная запись для `passive-log-snapshot`. Не использовать wildcard или общий `hardware-test` scope.
3. Допустимый доступ: обычный ADB shell либо отдельно root/ptrace/tracefs. Не повышать права и не обходить SELinux автоматически.
4. Максимальную длительность (до 600 s на одну запись) и максимум наблюдений (до 10 000). Назначить меньший практический предел в approval.
5. Источник остановки: лимит достигнут, camera/PVR error, рост queue failures/drops, неожиданное изменение службы/потока, появление персональных данных или требование неподтверждённой привилегии.
6. Разрешённый набор данных: allowlisted технические IDs/timestamps/metadata fields и fd identity. Не изображения, видео, пользовательские данные, аккаунты, serial или полные несвязанные логи.
7. Отдельное подтверждение для каждой instrumentation action, если passive наблюдения оказалось недостаточно.

В репозитории есть валидатор approval и M1 read-only inventory runner. Owner-confirmed Pico 4 Pro hardware identity не пересматривается; Android tuple — software identity check и не является криптографической attestation. M1.5 уже был выполнен владельцем: `PARTIAL_PERMISSION_DENIED`, 10 commands/10 records, 13 process matches и denial на первом foreign `/proc/<pid>/fd`; доступность остальных PID неизвестна. Для любого следующего run нужен свежий approval ровно на одно действие с UTC issue/expiry (окно до 24 часов), scope и лимитами; M1 hard-caps 60 seconds/200 records и повторно вызывает gate перед каждой ADB-командой. M1.6 exact `yes` prompt предотвращает случайное продолжение, но не является authentication/security boundary. На текущий M2 approval не создан; proposal-only действия ниже не запускались.

## M2 proposed permissions and exact scope

Приоритетный следующий эксперимент — новый action `read-only-camera-node-metadata`, только обычный ADB shell, 30 seconds и 40 records. Он разрешает `get-state`, четыре фиксированных owner-target getprop identity queries, fingerprint/release/kernel queries и два literal fixed-script `shell sh -c` probes: один читает только `/sys/class/video4linux/video[0-9]*` поля `name/index/dev`, второй делает bounded `ls -ln` metadata inspection только для `/dev/video[0-9]*` character nodes. Каждый probe ограничен 16 entries; transport option допустим только явно выбранным numeric `-t <id>`. Native allowlist должен сравнивать точные argument vectors и script templates; произвольный shell text не допускается. Подробный design и output contract см. [`P3-A6-M2-Read-Only-Camera-Metadata-Proposal.md`](P3-A6-M2-Read-Only-Camera-Metadata-Proposal.md).

Если node metadata оставит обоснованный вопрос, process-FD follow-up может получить только отдельный свежий action `read-only-camera-process-fd-followup` (предлагаемые пределы 60 seconds/200 records/13 process matches). Перед каждым PID probe process identity перепроверяется; каждый PID получает собственный outcome. При `PROC_ACCESS_DENIED` его статус сохраняется и запрещённая запись не переобходится. Это не даёт permission на `fdinfo`, `/proc/<pid>/maps`, process memory, ptrace, root или SELinux changes. Даже видимый `/dev/videoN` symlink не доказывает `ioctl(fd,0xc01856c0,...)` attribution.

`dumpsys media.camera`, `cmd media.camera`, camera/Binder client creation, camera open, `v4l2-ctl`, ioctl, tracing, logging changes, SteamVR и Lighthouse остаются вне первого scope. M2 sysfs/node probes не могут установить active queue ownership, frame delivery, physical SOF или exposure start. No M2 run is authorized by the M1 approval or by this proposal.

M1 inventory runner не вызывает `adb devices` и не запрашивает serial: без выбранного transport он вызывает только `adb get-state`, а при заданном `-TransportId` — `adb -t <id> get-state`. Ошибка ADB используется только transiently для определения типа отказа; raw stderr отбрасывается. Если ADB сообщает `more than one device`, runner завершает работу до shell-команд как `BLOCKED_MULTIPLE_DEVICES`. При заранее выбранном transport ID он остаётся только в памяти текущего процесса и не записывается в evidence. Эта проверка, как и остальной M1 runner, ещё не выполнялась на устройстве.

## Риск приватности и хранения

Сохранять только технику, нужную для контракта: run/approval IDs, build/kernel identity без serial, PID/TID только на время run, `/dev/videoN`, fd number, ioctl command, queue IDs, raw timestamp fields, allowlisted metadata numbers, fdinfo object identity и clock samples. Удалить из отчётов пользователей, аккаунты, Wi-Fi/Bluetooth IDs, полные system logs и непрофильные paths. Не собирать frame payload.

Сырые runtime записи — приватное evidence; публично в Git попадают только схема, методика и агрегированные результаты без чувствительных идентификаторов. Хэши сохранять для локальной целостности, но не публиковать приватные сырые dump-ы. Любое неожиданное персональное/изображающее содержимое — немедленный stop, не копировать и не публиковать.

### Private evidence schema (template only)

Следующий JSON shape предназначен для локального приватного evidence после будущей отдельно одобренной сессии. Здесь он дан как схема с `null` placeholders; фактических runtime observations нет. Это **не** входная схема текущего analyzer (`p3a6.synthetic_observations.v1` намеренно принимает только synthetic records).

```json
{
  "schema": "p3a6.private_runtime_evidence.v1",
  "record_kind": "template_only",
  "approval": {
    "approval_id": null,
    "approved_actions": [],
    "issued_at_utc": null,
    "expires_at_utc": null,
    "max_duration_seconds": null,
    "max_observations": null
  },
  "target": {
    "product": "Pico 4 Pro",
    "build_fingerprint": null,
    "android_release": null,
    "kernel_release": null
  },
  "capture": {
    "started_at_utc": null,
    "ended_at_utc": null,
    "method": null,
    "tool_and_version": null,
    "root_used": null,
    "observation_count": 0,
    "stop_reason": null
  },
  "processes": [
    {
      "role": "quickcamera_or_pvr",
      "process_name": null,
      "pid": null,
      "fd_observations": [
        {
          "fd": null,
          "node": null,
          "outer_ioctl": "0xc01856c0",
          "association_method": null
        }
      ]
    }
  ],
  "allocations": [
    {
      "role": "producer_cpu_mapping",
      "pid": null,
      "mapping_start_va": null,
      "mapping_length": null,
      "allocation_fd": null,
      "kernel_object_identity": {
        "identity_type": null,
        "exporter": null,
        "object_id": null,
        "source": null
      }
    },
    {
      "role": "pvr_fd_mapping",
      "pid": null,
      "fd": null,
      "node": null,
      "mapping_start_va": null,
      "mapping_length": null,
      "offset": null,
      "kernel_object_identity": {
        "identity_type": null,
        "exporter": null,
        "object_id": null,
        "source": null
      }
    }
  ],
  "observations": [
    {
      "ordinal": null,
      "frame_sequence": null,
      "request_id": null,
      "timestamp_source_request_id": null,
      "fallback_marker": null,
      "qbuf_id_u32": null,
      "qbuf_userptr_raw_u64": null,
      "dqbuf_userptr_raw_u64": null,
      "dqbuf_lookup_key_u32": null,
      "ioctl_status": null,
      "qtimer_value_raw": null,
      "qtimer_units": "UNKNOWN",
      "metadata_fields_allowlisted": {},
      "android_clock_api": null,
      "android_mono_before_ns": null,
      "android_mono_after_ns": null,
      "observer_delivery_mono_ns": null,
      "host_receive_clock_and_value": null
    }
  ],
  "clock_calibration": {
    "qtimer_ns_per_unit": null,
    "calibration_source": null,
    "calibration_matches_target_build": false,
    "physical_event_semantics": "UNPROVEN"
  },
  "privacy": {
    "image_pixels_collected": false,
    "video_collected": false,
    "user_data_collected": false,
    "serial_collected": false
  },
  "gates": {
    "exact_time": false,
    "mapping_verified": false,
    "pose_verified": false,
    "shared_buffer_identity_verified": false,
    "frame_meta_bridge_verified": false,
    "live_lighthouse_correction_allowed": false,
    "physical_event_verified": false
  },
  "artifact_sha256": null
}
```

Поля `mapping_start_va`, PID, fd и object identity остаются только в приватной записи; в публикуемых отчётах их агрегировать/редактировать. `metadata_fields_allowlisted` содержит только заранее перечисленные numeric offsets/values. Unknown values остаются `null`/`UNKNOWN`; не заполнять их через inference. `observer_delivery_mono_ns` разрешён только для Android-side delivery timestamp в том же clock domain; host receive time хранится отдельно и не подставляется вместо него.

## Ограничения причинности и измерений

- Process inventory показывает открытый node, но не всегда объект VideoQueueUtil. Для точной атрибуции нужен fd из внешнего ioctl observation или уже существующий однозначный log.
- `strace`/ptrace вокруг ioctl способен менять планирование; успешный круг ID при trace — наблюдение в traced run, а не доказательство невозмущённого режима или kernel guarantee.
- Доступный `/proc`/fdinfo может не публиковать dma-buf inode/exporter identity. Одинаковые size, mapping length, FD number или похожие bytes не заменяют allocation identity. Нельзя fallback-ить к чтению всей памяти.
- Сопоставление QTIMER и Android monotonic требует clock API/domain и QTIMER scale. Без independently validated scale drift ppm не рассчитывается. Перенос timestamp через logcat/ADB adds transport and logger delay.
- Системная delivery latency не означает physical sensor SOF/exposure start. Ни callback arrival, ни log prefix, ни PVR output timestamp сами по себе не определяют физическое событие.
- Android 10/PICO vendor kernel может ограничивать `procfs`, ptrace, debugfs/tracefs и shell tools. Совместимость проверяется только в одобренной сессии; неподдерживаемый метод фиксируется `BLOCKED`, не обходится.

## Stop conditions

Остановить сессию, если нужный факт требует root/ptrace без явного approval, доступа к image bytes, установки APK/agent, изменения logging/camera mode, patch/hook, запуска SteamVR/correction, или если observer вызывает ошибки/рост dropped frame кандидатов. Не продолжать «ради полного набора» после исчерпания разрешённого scope.
