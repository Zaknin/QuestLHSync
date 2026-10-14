#!/system/bin/sh
MODDIR=${0%/*}
RUN=/dev/.questlhsync_pico
until [ "$(getprop sys.boot_completed)" = 1 ]; do sleep 2; done
mkdir -p "$RUN"
chmod 0755 "$RUN"
[ -f "$RUN/service.pid" ] && kill "$(cat "$RUN/service.pid")" 2>/dev/null
# One lhsyncd per headset: the normal Quest module must not also be installed on this Pico.
(
    while [ ! -e "$MODDIR/disable" ] && [ ! -e "$MODDIR/remove" ]; do
        "$MODDIR/lhsyncd" "$MODDIR"
        sleep 5
    done
) </dev/null >/dev/null 2>&1 &
echo $! > "$RUN/service.pid"
