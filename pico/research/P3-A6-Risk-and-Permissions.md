# P3-A6 — Risk and Permissions

Дата: 2026-10-19. Это оценка будущего эксперимента, не разрешение на его выполнение. Pico 4 Pro на international Pico OS — установленный факт владельца. Последний owner-run M1.5 завершился `PARTIAL_PERMISSION_DENIED`; текущая M1.6/M2 работа была offline-only. Все новые M2 действия остаются **NOT AUTHORIZED / NOT RUN**.

## Классы наблюдения

| Класс / метод | Что можно узнать | Root / PICO OS 5.11.2 | Риск тайминга и потока | Доверие и границы |
|---|---|---|---|---|
| **Read-only inventory:** build props, kernel release, process list | Build identity, найти QuickCamera/PVR процессы | ADB shell нужен после отдельного разрешения; root не обязателен для части props/process list, но SELinux может скрыть процессы | Низкий, краткий системный overhead; читать без запуска камеры | Хорошая системная inventory, но не связывает VideoQueueUtil fd и node |
| **M2, при отдельном разрешении:** `/sys/class/video4linux/videoN/{name,index,dev}` read-only | Имена зарегистрированных V4L class entries, class index и major:minor | Обычный shell; traversal/read разрешения зависят от DAC/SELinux конкретного build. Denial фиксируется, обхода нет | Очень низкий ожидаемый overhead от ограниченного чтения; vendor sysfs handlers и scheduling не проверены. Ограничить до 16 nodes и 40 records | Подтверждает sysfs node metadata на время чтения; не связывает node с QuickCamera/PVR fd, ioctl, очередью или кадром |
| **M2, при отдельном разрешении:** `/dev/videoN` node metadata | Наличие character node, numeric mode/owner/group и major:minor | Обычный shell; только `ls -ldn` по строго ограниченному пути после symlink/type checks, без open. DAC/SELinux могут запретить | Очень низкий; не открывать node и не вызывать ioctl; ограничить до 16 nodes | Подтверждает только node metadata; номер не является стабильной камерой и не доказывает владельца/использование |
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

В репозитории есть общий approval validator, M1 inventory runner и отдельный M2 node-metadata runner. Owner-confirmed Pico 4 Pro hardware identity не пересматривается; Android tuple — software identity check и не является криптографической attestation. M1.5 hardware result остаётся `PARTIAL_PERMISSION_DENIED`, 10 commands/10 records, 13 process matches и denial на первом foreign `/proc/<pid>/fd`; доступность остальных PID неизвестна. Для M2 нужен новый свежий approval ровно на action `read-only-camera-node-metadata`, с UTC issue/expiry (окно до 24 часов), Pico 4 Pro target, `max_duration_seconds <=30` и `max_observations <=40`. M2 повторно проверяет gate перед каждой командой, включая native executor boundary. Exact lowercase `yes` предотвращает случайное продолжение, но не является authentication/security boundary. Approval не создан; collector, ADB и Pico в M2 подготовке не запускались.

## M2 prepared permissions and exact scope

Подготовлен отдельный action `read-only-camera-node-metadata`, только обычный ADB shell, максимум 30 seconds/40 node observations и максимум 16 candidates per source. Exact allowlist включает `get-state`, четыре фиксированных identity getprop, fingerprint/release/kernel queries и два embedded fixed-script `shell sh -c` probes: sysfs читает только `name/index/dev`, `/dev` использует `ls -ldn` metadata после symlink/character checks. Допускается default ADB transport или явно выбранный numeric `-t <id>`. Native allowlist сравнивает exact string-array vectors и embedded script bytes; произвольный shell/path/command substitution отклоняются. Device run остаётся неразрешённым. Подробный contract и ограничения см. [`P3-A6-M2-Handover.md`](P3-A6-M2-Handover.md) и [`P3-A6-M2-Read-Only-Camera-Metadata-Proposal.md`](P3-A6-M2-Read-Only-Camera-Metadata-Proposal.md).

Если node metadata оставит обоснованный вопрос, process-FD follow-up может получить только отдельный свежий action `read-only-camera-process-fd-followup` (предлагаемые пределы 60 seconds/200 records/13 process matches). Перед каждым PID probe process identity перепроверяется; каждый PID получает собственный outcome. При `PROC_ACCESS_DENIED` его статус сохраняется и запрещённая запись не переобходится. Это не даёт permission на `fdinfo`, `/proc/<pid>/maps`, process memory, ptrace, root или SELinux changes. Даже видимый `/dev/videoN` symlink не доказывает `ioctl(fd,0xc01856c0,...)` attribution.

`dumpsys media.camera`, `cmd media.camera`, camera/Binder client creation, camera open, `v4l2-ctl`, ioctl, tracing, logging changes, SteamVR и Lighthouse остаются вне первого scope. M2 sysfs/node probes не могут установить active queue ownership, frame delivery, physical SOF или exposure start. No M2 run is authorized by the M1 approval or by this proposal. POSIX probes прошли локальные synthetic fixtures; установленный Pico Toybox output не проверялся. Несовместимый output должен остановиться со статусом unavailable без fallback.

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

## M2.7A prepared provider acquisition — permissions and residual risk

The separate future action is `read-only-camx-core-provider-acquisition`; it is not covered by M1/M2 approvals. It requires a fresh exact-action approval, explicit ADB serial or numeric transport selector, exact lowercase interactive `yes`, pinned SDK ADB, and the common gate immediately before each command. The software identity tuple and `arm64-v8a` must match the owner-reported build. Hard caps are 60 seconds, 200 command observations, 160 native command invocations, 16 candidates, 64 MiB per candidate, 128 MiB total transfer, and 64 KiB returned ADB stdout. No root, device writes, camera, `/proc`, process memory, framebuffer, sensor, ioctl, or tracing access is permitted.

| Source/operation | Permission and risk | Evidence value / limitation |
|---|---|---|
| Fixed `find` over six approved library roots | Ordinary unprivileged shell read/search permission; recursive scan may consume CPU/IO until the 60-second timeout. SELinux/DAC may hide entries. | Finds existing `camx_core.so` paths without guessing a partition. No result does not prove absence when any root is unavailable. |
| `readlink -f` on a discovered candidate | Ordinary path traversal/read permissions; Android Toybox compatibility is unverified. | Resolves aliases and constrains source to approved root/lib64; does not prove which alias the runtime loader uses. |
| `wc -c`, `sha256sum` on resolved candidate | Ordinary unprivileged file read; command availability and access are unverified on this firmware. Hashing can add storage IO. | Enforces transfer byte ceilings and records before/after source hashes; no ELF semantics. |
| `adb pull` into temporary host staging | Unprivileged ADB transfer for an explicitly discovered candidate; can add device IO and has unmeasured performance impact. | Allows static ELF parsing; does not observe camera buffers or prove provider runtime loading. |
| Local NDK `llvm-readelf` | No device permission; local CPU/memory cost bounded by subprocess timeout/output limit and input byte caps. | Reports Build ID, dynamic symbols and dependencies. Symbol matches locate code for review but do not establish a whole CRM-to-CSL bridge. |
| Canonical private SMB publication | Host write permission to the existing private evidence share; transfer occurs after collection only. | Stores verified private package/manifest and commits with sidecar last. No M2.7A publication occurred. |

Do not broaden roots, add shell fallbacks, or select one of multiple candidates. A discovered/accessible candidate is not process ownership, runtime-loaded dependency, event callback, frame delivery, physical SOF, or exposure start. `readlink -f`, `find`, `wc`, `sha256sum`, remote shell quoting and `adb pull` behavior remain unverified on the exact Android 10/PICO OS image; incompatible output stops with a diagnostic status. Preserve diagnostics privately, and never publish proprietary ELF to GitHub.

Future operator command (not executed; requires fresh separate approval):

```powershell
python .\pico\tools\p3a_m27b_camx_provider.py --approval-file "$env:LOCALAPPDATA\PicoLHSync\approvals\<fresh-M2.7B-approval>.json" --serial "<explicit-target>"
```

Final offline review tightened publisher handling: unsafe names and pre-existing final/temporary paths fail closed; `.part` files are created exclusively and only temporary files created by the current call are cleaned after an error. A repeated name cannot replace previously published artifacts. This was verified with local synthetic files only; no SMB read-back occurred. The implementation does not claim protection against a hostile concurrent writer with permission to mutate the canonical share between filesystem operations, so existing share ACLs remain part of the trust boundary. M2.7A remains **offline preparation GO**; M2.7B remains **NOT AUTHORIZED / NOT RUN**.

## M2.7B initial owner-authorized execution outcome (2026-10-19)

The M2.7B request in the current task directly authorized this one bounded read-only acquisition. The runner was changed to require explicit `--owner-authorized-run`, bind only one digest-pinned serial supplied through a process-local environment variable, and use the pinned SDK ADB executable. It no longer reads approval JSON or asks for `yes`; the report records the distinct `OWNER_AUTHORIZED_DIRECT_INSTRUCTION` mode and states that it is not cryptographic attestation. The CLI mode is not a reusable authorization: any later run requires fresh direct owner authorization. This M2.7B change does not add the raw endpoint to its runner/tests/docs; pre-existing legacy ADB defaults elsewhere in the project were left untouched.

| Operation | Access / risk | Observed outcome |
|---|---|---|
| Fixed `adb connect` | Host network connection to one explicitly pinned ADB endpoint; establishes an ADB transport if available. | Three initial bounded attempts all received TCP connection refused (Windows 10061). No device command was reached. |
| Selected `get-state` and six fixed `getprop` calls | Ordinary ADB shell read; could reveal software identity. | `NOT RUN`; connect failed first. |
| Fixed library-root `find` / `readlink` / `wc` / `sha256sum` | Unprivileged shell filesystem metadata/read; recursive scan and hashing can add bounded IO. | `NOT RUN`; no paths or candidates observed. |
| `adb pull` and local `llvm-readelf` | Reads only discovered library candidates and performs bounded host-side parsing. | `NOT RUN`; no provider bytes. |
| Canonical private publication | Host write access to canonical SMB; exact readback, ZIP/manifest then sidecar last. | Three BLOCKED diagnostic packages independently read back and verified; no `.part` remnants. Details are in the M2.7B result report. |

The runner's target-binding digest is an exact allowlist guard, not owner authentication. The direct authorization is contextual and limited to the current task. No root, SELinux bypass, `/proc`, process memory, camera, image/video, tracing, installation, firmware or Lighthouse operation was used. This initial outcome was later superseded by the connectivity recovery recorded below. The prior M2.7A `NOT AUTHORIZED / NOT RUN` statement is historical.

## M2.7B connectivity recovery and partial discovery (2026-10-19)

| Operation | Access / risk | Observed outcome |
|---|---|---|
| Windows ping, TCP/5555 and ARP inspection | Host-side network metadata only. A dynamic ARP neighbor is not authenticated device identity without a trusted MAC mapping. | Ping 0/2 replies, TCP/5555 initially closed, dynamic ARP entry; ARP identity `NOT_CONFIRMED`. |
| USB-only ADB identity check | Read-only fingerprint query through pinned SDK ADB `-d`; ambiguous/no USB transport stops before mode change. | One usable USB transport; exact owner-bound build fingerprint matched. Serial remains private. |
| `adb -s <USB_SERIAL> tcpip 5555` | Restarts adbd in TCP mode on the verified USB device; ADB-over-network remains available until reverted or adbd/device restarts. | Issued only after fingerprint match; ADB reported restarting on port 5555. One fixed-endpoint connect succeeded; TCP `get-state` and fingerprint matched. The temporary TCP mode was left active for the authorized M2.7B continuation. |
| Existing fixed M2.7B runner | Exact build/product/ABI checks then bounded recursive metadata search across the six approved roots. Root traversal may encounter DAC/SELinux or Toybox `find` errors; stderr is suppressed by the existing script. | Identity tuple and ABI matched. 9 ADB commands/observations; `/system=SCANNED`, `/system_ext=ABSENT`, `/vendor`, `/odm`, `/product`, `/apex=FIND_ERROR`; 0 candidates. Returned `PARTIAL_DISCOVERY`. Exact `find` causes remain unknown. No size/hash/pull/ELF analysis. |
| Canonical private publication | Host write and read-back of ZIP/manifest/sidecar; no ELF bytes when candidate set is empty. | One `PARTIAL_DISCOVERY` package, independently verified; archive contains only the manifest and sidecar is last. SHA-256 receipts are in the M2.7B analysis report. No duplicate package was created for repeated network checks. |

At that historical stage, the dynamic ARP mapping alone did not identify the headset, `FIND_ERROR` did not distinguish permission, traversal, or shell behavior, and the provider remained unacquired. This status was superseded by the bounded final recovery below. All timing, mapping, pose, shared-buffer, frame-meta, physical-event, and Lighthouse gates remain `false`.

## M2.7B final recovery and provider acquisition risk review (2026-10-19)

The corrected probe searches only exact expected library paths and fixed library subtrees, plus eligible APEX package `lib64` directories. It keeps validated candidate stdout from a failing `find` while preserving `FIND_ERROR`/`SCAN_INCOMPLETE` for that root. A nonzero traversal never becomes proof of absence or a complete scan. No root, SELinux bypass, arbitrary command, broad partition scan, process access or camera operation was introduced.

One bounded owner-authorized run over the already restored TCP transport checked the exact owner-bound software fingerprint and `arm64-v8a`, discovered `/vendor/lib64/camx_core.so`, validated path/type/size, remote hash before and after pull, local hash, ELF64/AArch64 and Build ID. A temporary local copy was used for static parsing only and removed; no proprietary bytes entered Git. The verified artifact and manifest were published to the existing private canonical share, independently read back, and finalized with `.sha256` last.

The collection has bounded filesystem metadata/read and hashing IO cost within the existing collector caps. It may miss files outside the allowed subtrees or in inaccessible paths; such missing coverage must remain incomplete. The one-candidate result is complete only for the reported fixed scan scope, not the whole device. Static parsing confirms provider code paths but does not prove runtime loader selection, event delivery, request/frame correlation, timestamp source selection, physical SOF/exposure semantics or Lighthouse suitability.

Current M2.7B status: **PACKAGE_READY; provider acquisition and offline binary bridge review complete**. No further device collection is recommended for this static objective. Any follow-up must target a specific runtime unknown with separate authorization and a minimal passive method. Exact-time, mapping, pose, shared-buffer, frame-meta, physical-event and Lighthouse safety flags all remain `false`.

## M2.8B runtime mapping attempt — permission stop (2026-10-19)

The owner-authorized M2.8B attempt used only the pinned SDK ADB, exact target binding, expected fingerprint/ABI checks, and the fixed 15-second/40-observation probe. It made five ADB calls and retained three normalized observations. The first allowlisted process candidate (`pvrtrackingservice`) had a stable PID/name/starttime bracket, but reading its `/proc/<pid>/maps` returned `PROC_ACCESS_DENIED`; the collector stopped immediately. It did not test additional PIDs, change identity/privileges, or retry with another interface. This is a permission limitation for the first candidate only; it does not establish that all QuickCamera/HIDL/PVR mappings are inaccessible or that `camx_core.so` is absent.

The fixed `stat` calls for the two exact installed library paths succeeded and their device/inode values remain only in the private canonical package. Since no maps record was returned, no file-to-process identity comparison is possible. The result is `BLOCKED`, never PASS/PARTIAL mapping, and leaves runtime provider loading UNKNOWN. The package contains only filtered manifest data (no raw process table/maps or ELF), its ZIP SHA-256 was independently read back against the `.sha256` sidecar, and the sidecar was committed last.

An aggregate unprivileged Android memory diagnostic could at most be considered after offline compatibility/scope review; if it reports library name without device/inode and exact PID attribution, it cannot meet mapping PASS. Do not rerun maps, broaden `/proc` reads, use root/su, `map_files`, SELinux changes, hooks, tracing or logging changes under this outcome. There is no evidence that another source can meet the full criterion within the present read-only scope. All timing, mapping, pose, shared-buffer, frame-meta, physical-event and Lighthouse gates remain `false`.

## M2.8C callback log snapshot — output framing stop (2026-10-19)

Offline review found one useful static log site in the pinned QuickCamera callback path: INFO-format `CSLTimestampTypeQtimer frameMessage` with request ID, frame count, timestamp and `monoTimestamp`. HIDL lifecycle messages, generic CamX DQEVENT logs, and PVR timestamp strings do not offer the same CRM-to-callback fields. A single bounded default-level main-buffer snapshot was therefore attempted after the exact build fingerprint and ABI matched.

The probe requested `logcat -b main -d -v threadtime -t 256`; device-side code was intended to emit only lines from the bounded QuickCamera/PVR PID/name candidate set matching the exact literal marker, then normalize numeric fields. The host received 3,540 bytes and rejected the response with `OUTPUT_FRAMING`; the implementation did not preserve which guard fired (line count versus embedded control). It accepted zero records, and logcat option/filter support remains `NOT_CONFIRMED`. Do not interpret this as an empty log buffer or absent callback.

No raw output was written to disk or canonical evidence. Because the protocol failed, we cannot prove the response contained only normalized allowlisted rows before reaching the host. Treat filter-before-transfer as **unverified**. Do not retry logcat in M2.8C. Offline-only follow-up: harden the host framing diagnostic, test CRLF solely at record boundaries, add an exact 40-line and embedded-control regression, and verify shell argument framing with synthetic fixtures before considering any separately scoped collection. Do not use `/proc`, raise privilege, change log levels, or activate a camera.

The initial canonical output was committed with a receipt error after the sidecar; it is retained unchanged. The corrected canonical diagnostic package independently verified the archive, manifest, and sidecar, and contains no raw logcat or ELF. Details and hashes are in `P3-A6-M2.8C-Callback-and-Timestamp-Provenance.md`. All timing, mapping, pose, shared-buffer, frame-meta, physical-event and Lighthouse gates remain `false`.

### M2.8C-R offline recovery (2026-10-19)

The baseline contained no original M2.8C parser, collector, fixed probe, or integration fixture; a targeted local workspace/temp search did not recover them. The checked-in M2.8C-R sources are reconstructed and must not be represented as the probe whose output produced the original 3,540-byte incident. The old raw response is absent, so its exact framing cause remains `UNKNOWN`, and the historical M2.8C result remains `BLOCKED_OUTPUT_FRAMING`.

The reconstructed parser now returns distinct safe codes for line-count overflow, invalid controls, invalid line endings, malformed protocol, missing terminator, output truncation, unverified filtering, unsupported logcat option, and remote command failure. Errors contain only fixed code, byte/record counts, and optional line/offset. Synthetic WSL tests confirm the reconstructed script filters raw logcat stdout before its ADB stdout boundary, discards buffered rows when logcat exits nonzero, keeps remote stderr on the separate ADB stderr channel, and prevents parser evidence from retaining raw stderr text. This is local synthetic evidence only; the original probe's filtering behavior remains unverified.

The fixed command vector and Windows process argument serialization were checked offline. WSL `/bin/sh` with WSL `awk` accepted the reconstructed script, but this does not prove Android 10 Toybox `awk`, device `logcat` option support, or the installed SDK ADB's remote shell quoting behavior. No incompatibility was confirmed offline; target-specific compatibility remains `UNVERIFIED`. Do not solve that gap by broadening log access or changing logging settings.

Static offset review corrected a prior explanation: QuickCamera passes the `CSLMessage+0x10` word to the format's `frameCount` argument and `+0x20` to `linkhdl`. Existing provider binary analysis records CRM `frame_id` copied to `+0x10`. This establishes a static field-flow relation between the provider frame ID and the value named `frameCount` in this log site, not runtime occurrence, pipeline/PVR ID equality, or `FrameMetaDate` correlation. `monoTimestamp` is the same request-ID-indexed 38-slot ring value as the logged timestamp on the straight-line path; it is not an independent Android monotonic sample.

The minimum useful future experiment is one fresh, separately scoped, bounded read-only default-log snapshot using a reviewed fixed probe and only if Android 10 shell/awk/ADB argument behavior is resolved. A matching record could show callback-specific log occurrence and its logged identifiers/timestamps. It still cannot prove runtime provider byte identity, CRM event ID, clock units/epoch, fallback occurrence, physical SOF/exposure, PVR metadata join, or Lighthouse suitability. M2.8C-R ran no hardware experiment and changed no safety gate.

M2.8C-R verification: Python 265/265, M2.8C parser/argv 16/16, M1 PowerShell 29/29, M2 PowerShell 410 assertions, and all four current WSL POSIX integrations PASS. All checks are offline; Android shell/logcat compatibility remains unverified.
