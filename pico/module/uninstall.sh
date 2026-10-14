#!/system/bin/sh
[ -f /dev/.questlhsync_pico/service.pid ] && kill "$(cat /dev/.questlhsync_pico/service.pid)" 2>/dev/null
pkill -x lhsyncd 2>/dev/null
pkill -x pico_lhsight 2>/dev/null
rm -rf /dev/.questlhsync_pico
