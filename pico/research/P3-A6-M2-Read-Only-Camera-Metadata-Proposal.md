# P3-A6-M2 — Read-Only Camera Metadata Proposal

Дата: 2026-10-19. Репозиторий `C:\Dev\PicoLHSync`, branch `feature/pico-support`, basis `8ee2858c3e7f1054750126d369c2b2950d01855e`.

## Статус и границы

**OFFLINE PROPOSAL ONLY — NOT AUTHORIZED / NOT RUN.** В M1.5 владелец подтвердил Pico 4 Pro на international Pico OS и сообщил partial inventory outcome: 13 QuickCamera/PVR process matches; первая `/proc/<pid>/fd` проверка получила `PROC_ACCESS_DENIED`; сбор остановился с `PARTIAL_PERMISSION_DENIED`, 10 commands, 10 records и нулём video-FD records. Ничего из этого не доказывает доступность оставшихся process descriptors. M2 ниже не использует и не распространяет M1 approval.

Первый M2 эксперимент предлагается ограничить системными метаданными Video4Linux nodes. Он не открывает `/dev/videoN`, не вызывает ioctl, CameraService, Camera2/Binder client, не читает чужую память или descriptor directories, не требует root и не запускает камеру. Отдельная per-process FD follow-up рассматривается отдельно и требует собственного точного approval action. Никакой M2 collector/allowlist коду в этой задаче не добавлен.

## Ранжирование источников

| Ранг | Источник | Информационная ценность | Shell permissions / Android 10 | Риск timing / privacy | Что можно доказать |
|---|---|---|---|---|---|
| **1** | `/sys/class/video4linux/videoN/{name,index,dev}` — только чтение | Низкой стоимостью связывает зарегистрированный class entry с descriptive name, class index и major:minor | Нужны traversal/read права для соответствующих sysfs entries; DAC и SELinux policy конкретной PICO прошивки неизвестны. Без root; denial фиксируется | Очень низкий ожидаемый overhead от нескольких sysfs reads; vendor `show()` implementation и scheduling неизвестны. Имя может раскрывать драйвер/vendor, поэтому сохранять только ограниченную строку | Доказывает наличие/имя зарегистрированного V4L class device на момент чтения. Не доказывает, что его использует QuickCamera/PVR, что у него активна очередь или что кадр доставлен |
| **2** | `/dev/videoN` — `lstat`-подобная node metadata | Подтверждает наличие character node и его mode, numeric owner/group, major:minor | Обычно достаточно search permission на `/dev` и доступности `ls`; node не открывается. DAC/SELinux могут запретить metadata lookup | Очень низкий, но ADB process scheduling добавляет малую задержку. Записывать только `/dev/videoN` и numeric metadata; не сохранять посторонние пути | Подтверждает только node metadata. Номер не стабилен между builds/boots; не доказывает fd, ioctl, queue ownership, frame delivery или SOF |
| **3** | Остальные QuickCamera/PVR `/proc/<pid>/fd` — только отдельный future action | Может показать, какой обычный userspace process держит открытый `/dev/videoN` на момент чтения | Только текущий unprivileged `shell` domain. Каждый PID должен быть заново подтверждён через `ps`; access-denied означает stop для этого PID. Не использовать root/su/ptrace/SELinux bypass | Низкий–средний: чтение до 13 fd directories/readlink entries и ADB scheduling; PID/name и только video-node targets приватны. Не читать fd contents, fdinfo, maps или file payload | Может показать process→open-fd→node association, если shell законно видит ссылку. Не связывает fd с конкретным ioctl/`VideoQueueUtil`; не доказывает queue activity или timings |
| **4** | `dumpsys media.camera` | Может сообщать Android logical camera IDs, providers и active CameraService clients | Требует, чтобы команда и permission `android.permission.DUMP` были доступны shell на точном build; PICO policy не проверена. Upstream AOSP не гарантирует vendor поведения | Не выбран для первого M2: dump проходит через service locks/provider dump и может раскрыть client package/PID, event/vendor metadata; output может быть большим. Даже если он не открывает камеру в AOSP reference implementation, его обращение к service не является нулевым runtime воздействием | Только Android CameraService logical/client state. Не показывает PVR ioctl fd, queue key или VideoQueueUtil owner и не устанавливает frame timing |
| **5** | Уже известный Pico Camera/Binder metadata path из P2/P3 | Высокая ценность для исходных timestamp/request/metadata полей, но лишь если данные уже экспортируются в существующем лог-файле | Предыдущий статический путь проходит через QuickCamera CSL/HIDL/shared-buffer и PVR mapping. ADB shell не получает эти значения простым чтением `/sys` или `/dev`; новые Binder клиент, process memory read или instrumentation не входят в M2 | Существующий, уже собранный технический log snapshot мог бы быть passive, если его точный источник и bounded format заранее найдены. Новый client/memory reader может изменить service scheduling и требует отдельной оценки | Статические источники устанавливают поля/передачу, но не runtime значения. Даже увиденный QTIMER-labelled metadata value сам по себе не доказывает SOF/exposure start |

**Приоритет:** (1) sysfs metadata, затем (2) `/dev` node metadata. Они дополняют друг друга и требуют только read/list metadata. Если оба источника доступны, они могут связать V4L class entry с node number/major:minor; это всё ещё node inventory, а не процессная/ioctl атрибуция. Service dump не оправдан на первом этапе из-за объёма, privacy и lock interactions. Per-process FD probes могут быть полезны, но должны быть самостоятельным свежим scope после рассмотрения результата node inventory.

Linux Video4Linux documentation описывает `name`, `index` и `dev_debug` class attributes; `dev_debug` используется для включения file-operation/ioctl logging, поэтому он явно запрещён, включая любые write-команды. Linux device-node numbers зависят от probe order и не являются стабильным camera identity. Эти generic kernel references не устанавливают наличие, permission или поведение на конкретном PICO build. Ссылки: [kernel V4L2 device registration and sysfs attributes](https://www.kernel.org/doc/html/v5.19/driver-api/media/v4l2-dev.html), [V4L2 userspace node naming and open semantics](https://cdn.kernel.org/doc/html/latest/userspace-api/media/v4l/open.html).

Android SELinux действует как mandatory access control поверх DAC и может запретить file access даже если pathname виден. Права проверяются естественным путём; отказ отмечается как `PERMISSION_DENIED` без retry с другими credentials и без обхода. См. [AOSP SELinux model](https://source.android.com/docs/security/features/selinux).

CameraService source в AOSP требует dump permission и берёт service/state locks, перечисляя client/provider state. Это только архитектурный reference: он не подтверждает поведение vendor build или безопасность конкретного PICO dump. См. [AOSP CameraService dump implementation](https://android.googlesource.com/platform/frameworks/av/+/e397f43/services/camera/libcameraservice/CameraService.cpp) и [AOSP camera architecture](https://source.android.com/docs/core/camera).

## Предлагаемые bounded commands и exact allowlist

Это design contract для будущего отдельного runner, не команда к запуску в M1.6. Host-side executable должен остаться pinned `$env:LOCALAPPDATA\Android\Sdk\platform-tools\adb.exe`; native allowlist принимает только следующие vectors и точные fixed POSIX script bytes. POSIX quoting производится только текущим безопасным quoting helper, а не shell interpolation пользовательского текста.

### Первый scope: node metadata

Новое approval действие: **`read-only-camera-node-metadata`**. Одно approval record, только target `Pico 4 Pro`, только это действие, `max_duration_seconds=30`, `max_observations=40`, UTC validity ≤24 часов. Это не существующий M1 action; M1 runner не должен принимать его.

Разрешённые vectors:

```text
['get-state']
['shell', 'getprop', 'ro.product.model']
['shell', 'getprop', 'ro.product.device']
['shell', 'getprop', 'ro.product.name']
['shell', 'getprop', 'ro.product.manufacturer']
['shell', 'getprop', 'ro.build.fingerprint']
['shell', 'getprop', 'ro.build.version.release']
['shell', 'uname', '-r']
['shell', 'sh', '-c', Q(SYSFS_NODE_METADATA_V1)]
['shell', 'sh', '-c', Q(DEVNODE_METADATA_V1)]
```

При явно выбранном transport допускается только префикс `['-t', '<1..10 digit nonzero transport-id>']` перед одним из этих vectors. `Q(script)` — POSIX single-argument quoting текущего helper; script bytes должны совпасть с встроенным шаблоном. Никакой произвольный `sh -c`, service command или пользовательский path не допускается.

`SYSFS_NODE_METADATA_V1` — fixed POSIX script template (его точные bytes должны быть закреплены в тестируемом allowlist перед реализацией), который:

1. Обходит только glob `/sys/class/video4linux/video[0-9]*`; принимает basename только если suffix целиком decimal.
2. Рассматривает максимум 16 nodes; сверх лимита печатает `LIMIT_REACHED` и останавливается.
3. Для каждого node читает только `index`, `dev`, `name`, если файл readable. Остальные sysfs атрибуты и `/sys/.../device` link не читаются.
4. Читает только по одной строке для каждого из `index`, `dev`, `name`; проверяет `index` и `dev` как bounded decimal/`major:minor` значения; ограничивает `name` длиной 96 ASCII символов из `[A-Za-z0-9_.:+ -]`. Любая дополнительная строка или некорректное значение заменяется статусом и не попадает в protocol data.
5. Выдаёт tab-delimited records фиксированным `printf` format: разделители `\t` находятся только в format string, все значения передаются отдельными `%s` arguments. На пустом glob сообщает `NOT_OBSERVED`; permission/field failures explicit.

Bounded POSIX template for the allowlist (not part of the M1 collector; implementation must pin its exact bytes and test them before any hardware run):

```sh
LC_ALL=C
export LC_ALL
count=0
found=0
read_one_line() {
  value=
  extra=
  {
    IFS= read -r value || return 1
    if IFS= read -r extra; then return 1; fi
  } < "$1"
  return 0
}
for d in /sys/class/video4linux/video[0-9]*; do
  [ -e "$d" ] || continue
  found=1
  count=$((count + 1))
  if [ "$count" -gt 16 ]; then
    printf 'P3A6\tSYSFS_STATUS\tLIMIT_REACHED\n'
    break
  fi
  base=${d##*/}
  suffix=${base#video}
  case "$suffix" in ''|*[!0-9]*) printf 'P3A6\tSYSFS_NODE_STATUS\tINVALID_NODE_NAME\n'; continue ;; esac
  if [ "${#suffix}" -gt 10 ]; then
    printf 'P3A6\tSYSFS_NODE_STATUS\tINVALID_NODE_NAME\n'
    continue
  fi
  if ! read_one_line "$d/index"; then printf 'P3A6\tSYSFS_NODE_STATUS\t%s\tUNAVAILABLE\n' "$suffix"; continue; fi
  index=$value
  if [ "${#index}" -gt 10 ]; then printf 'P3A6\tSYSFS_NODE_STATUS\t%s\tINVALID_INDEX\n' "$suffix"; continue; fi
  case "$index" in ''|*[!0-9]*) printf 'P3A6\tSYSFS_NODE_STATUS\t%s\tINVALID_INDEX\n' "$suffix"; continue ;; esac
  if ! read_one_line "$d/dev"; then printf 'P3A6\tSYSFS_NODE_STATUS\t%s\tUNAVAILABLE\n' "$suffix"; continue; fi
  dev=$value
  case "$dev" in *:*:*|:*|*:) printf 'P3A6\tSYSFS_NODE_STATUS\t%s\tINVALID_DEV\n' "$suffix"; continue ;; *:*) ;; *) printf 'P3A6\tSYSFS_NODE_STATUS\t%s\tINVALID_DEV\n' "$suffix"; continue ;; esac
  major=${dev%%:*}
  minor=${dev#*:}
  if [ "${#major}" -gt 10 ] || [ "${#minor}" -gt 10 ]; then printf 'P3A6\tSYSFS_NODE_STATUS\t%s\tINVALID_DEV\n' "$suffix"; continue; fi
  case "$major$minor" in ''|*[!0-9]*) printf 'P3A6\tSYSFS_NODE_STATUS\t%s\tINVALID_DEV\n' "$suffix"; continue ;; esac
  if ! read_one_line "$d/name"; then printf 'P3A6\tSYSFS_NODE_STATUS\t%s\tUNAVAILABLE\n' "$suffix"; continue; fi
  name=$value
  if [ "${#name}" -lt 1 ] || [ "${#name}" -gt 96 ]; then printf 'P3A6\tSYSFS_NODE_STATUS\t%s\tINVALID_NAME\n' "$suffix"; continue; fi
  case "$name" in *[!A-Za-z0-9_.:+\ \-]*) printf 'P3A6\tSYSFS_NODE_STATUS\t%s\tINVALID_NAME\n' "$suffix"; continue ;; esac
  printf 'P3A6\tSYSFS_NODE\t%s\t%s\t%s\t%s\n' "$suffix" "$index" "$dev" "$name"
done
[ "$found" -eq 1 ] || printf 'P3A6\tSYSFS_STATUS\tNOT_OBSERVED\n'
```

Перед hardware implementation тест обязан проверять literal script hash, все поля и статусы; этот дизайн-код сейчас не входит в collector. Доступные записи считываются только из трёх фиксированных sysfs files; значения никогда не используются как format string или как pathname component.

`DEVNODE_METADATA_V1` — fixed POSIX script, который обходит только `/dev/video[0-9]*`, проверяет suffix на decimal и лимит 16. Он сначала проверяет `-L` и выдаёт `SYMLINK_EXCLUDED` для symlink, затем `-c` для обычного character device; так `ls` не получает symlink и не печатает его target. Для regular character node вызывается только `ls -ln <fixed /dev/videoN path>`; parser принимает только bounded numeric mode/uid/gid/major:minor fields и отбрасывает любые строки с неожиданным framing. Сырой `ls` output не сохраняется. Он никогда не открывает video node, не вызывает ioctl, `v4l2-ctl`, streaming API или `stat` на произвольных paths. Недоступные/ошибочные значения становятся explicit status records, не пустым успешным результатом. Совместимость `ls -ln` и точный Toybox output на target требуют проверки только после отдельного разрешения; incompatibility даст `UNAVAILABLE`/`BLOCKED`, без fallback на более широкие команды.

### Следующий отдельный scope: process FD follow-up

Только если node inventory оставит конкретный вопрос, рассмотреть новое действие **`read-only-camera-process-fd-followup`** с отдельным свежим approval: максимум 60 секунд, 200 records/observations, 13 QuickCamera/PVR PIDs. Это независимый последующий experiment, не часть node metadata approval и не продолжение M1.5 разрешения.

Allowlist — точный `ps -A -o PID,NAME` process-list script и generated per-PID FD probe, где PID принимается только как decimal 1–10 digits. Перед чтением probe должен повторно проверить, что тот же PID всё ещё принадлежит bounded QuickCamera/PVR process name. Далее он может лишь тестировать/list `/proc/<pid>/fd` и `readlink` symlinks, сохраняя только targets `/dev/video[0-9]+`. Ни один descriptor не открывается приложением-коллектором и его содержимое не читается. Для каждого PID отдельный статус `OBSERVED`, `PROCESS_DISAPPEARED`, `PERMISSION_DENIED` или `UNAVAILABLE`; denial одного PID можно зафиксировать и перейти к следующему PID в рамках явно утверждённого 13-process limit. Не читать `/proc/<pid>/fdinfo`, `maps`, `map_files`, cmdline, environment, памяти или target paths, не являющихся `/dev/videoN`. Любой unexpected output/malformed protocol останавливает конкретную команду; privilege escalation запрещена.

Даже доступный FD target показывает только open file descriptor/process association в момент наблюдения. Для R1 всё ещё нужен точный `ioctl(fd,0xc01856c0,...)` attribution. Это исследование само по себе не позволит утверждать, что queue работает или кадры доставляются.

### Явно запрещённые vectors

`adb root`, `su`, `remount`, `push`, `install`, `reboot`, arbitrary shell, `dumpsys media.camera`, `cmd media.camera`, Camera2 API call, camera provider/client launch, open `/dev/videoN`, `VIDIOC_*`, `v4l2-ctl`, fd contents, `/proc` outside approved per-PID FD link lookup, `strace`, ptrace, hooks, tracepoints, log-level changes, service restart, APK/agent, image/video capture, and all Lighthouse/SteamVR commands.

CameraService dump остаётся вне allowlist: даже если на каком-либо build shell имеет `DUMP`, output может раскрыть package/PID, историю клиентов и vendor metadata; AOSP implementation взаимодействует с CameraService/provider locks. В M2 нет оснований подвергать работающий tracking/camera service этому запросу, когда sysfs/node metadata доступнее и безопаснее.

## Evidence and privacy contract

Для будущего разрешённого node-only run сохранять приватно: approval ID/action, UTC times, exact method, build identity, requested/effective limits, только parsed node metadata/statuses, command/record counts, source digests, archive SHA-256 и final marker. Не сохранять serial, аккаунты, Wi-Fi/Bluetooth IDs, camera images/video, frame pixels, полные dumpsys/logcat, raw process table или private user data. Для M2 не создаётся evidence package до отдельного run authorization.

`NOT_OBSERVED`, `UNAVAILABLE`, `PERMISSION_DENIED`, `LIMIT_REACHED` — самостоятельные outcomes; их нельзя превращать в пустой `PASS`. Не сохранять raw denial text, SELinux contexts целиком или непрофильные paths. Process names/PIDs и FD target metadata приватны и остаются только в отдельном approved process-FD action.

## Acceptance criteria будущего offline-reviewed implementation

1. Approval gate требует новую точную action строку и ограничивает 30 s/40 records для node-only scope; процессный follow-up требует другого approval action с 60 s/200 records/13 PID hard caps.
2. Gate проходит перед каждой ADB-командой; exact native allowlist отклоняет все vectors вне приведённых шаблонов. Пинованный ADB path и M1 privacy controls остаются.
3. Synthetic fixtures проверяют отсутствие sysfs/node entries, несколько nodes, permission denial, malformed/tab/newline values, 16-node cap, symlink exclusion, character-node selection, process PID reuse/disappearance, per-PID denial и отказ unexpected protocol.
4. Ни один probe не открывает video node, не запускает CameraService/client, не читает buffer/frame/process memory, не поднимает права и не меняет camera/tracking configuration.
5. Private evidence сохраняет точные statuses/method/build/time/caps/count/hash; safety gates остаются `false`.
6. В hardware results отдельными пунктами указано, что node existence/name/FD holder не доказывают ioctl attribution, queue ownership, frame delivery, SOF или exposure start.

До реализации этих criteria и новой прямой owner authorization M2 execution status — **NOT AUTHORIZED / NOT RUN**.

Offline validation (2026-10-19): the documented sysfs POSIX template was extracted and parsed by local WSL `/bin/sh -n` — **PASS**. This checks shell syntax only; it does not execute the template against sysfs fixtures or a Pico, does not test Android/Toybox compatibility, and does not provide device evidence.

## Static Pico userspace/Binder paths from prior phases

Предыдущие локальные исследования обнаружили собственный QuickCamera CSL → HIDL `QuickCameraBufInfo` → PVR mapped-buffer/`FrameMetaDate` путь. CSL metadata содержит QTIMER-labelled value в metadata `+0`, request ID в `+0x8` и дополнительные поля `+0x10/+0x14/+0x18`; отдельная timeout ветка может подставить предшествующий request timestamp. PVR получает handles/IDs через HIDL, конфигурирует буферный mapping и позже копирует metadata в `FrameMetaDate`. Точные статические результаты и ограничения находятся в [`P3-A3-CSL-Timestamp-SharedBuffer-20261017.md`](P3-A3-CSL-Timestamp-SharedBuffer-20261017.md), [`P3-A4-HIDL-PVR-Bridge-20261017.md`](P3-A4-HIDL-PVR-Bridge-20261017.md), [`P3-A4-Full-Buffer-Provenance.md`](P3-A4-Full-Buffer-Provenance.md) и [`P3-A5-Allocator-and-Queue-Contract-Audit.md`](P3-A5-Allocator-and-Queue-Contract-Audit.md).

Это статическая proprietary userspace provenance, не generic `dumpsys` schema. Ни обычный sysfs, ни `/dev` node metadata не содержат этих per-frame fields. Если штатный существующий log уже публикует строго ограниченные records — сначала нужен локальный offline discovery exact tag/format и отдельное разрешение на passive snapshot. Новый Binder client или процессный memory reader в M2 не предлагается: он может создать camera/service activity или изменить scheduling и требует отдельной instrumentation review.

## Итоговая рекомендация

Первый следующий hardware experiment, когда владелец отдельно разрешит его, должен ограничиться **node metadata only** (rank 1+2) с action `read-only-camera-node-metadata`, 30 seconds, 40 records. Это наиболее узкая проверка наличия/имён/major:minor nodes. Отдельный fresh approval потребуется прежде чем повторить process FD lookup по оставшимся PIDs; каждому PID уделить отдельный status и остановиться при policy denial, не обходя его. `dumpsys`, Binder client и timing instrumentation не включать.

Эта последовательность может сузить список кандидатов и определить, какие proc entries читаемы в обычном shell. Она не закроет R1 without ioctl-fd attribution, не докажет shared allocation, frame delivery, timestamp semantics или физический SOF/exposure. Safety gates остаются неизменными:

```text
exact_time=false
mapping_verified=false
pose_verified=false
shared_buffer_identity_verified=false
frame_meta_bridge_verified=false
live_lighthouse_correction_allowed=false
physical_event_verified=false
```
