#!/system/bin/sh
# Check the fixed logcat options with a one-row request. Android 10 rejects
# -t 0; both channels are discarded on-device and only this status crosses ADB.
set -f
LC_ALL=C
export LC_ALL

if logcat -b main -d -v threadtime -t 1 >/dev/null 2>&1; then
    printf 'P3A28D\tCAPABILITY\tLOGCAT\tOPTIONS_OK\n'
else
    printf 'P3A28D\tCAPABILITY\tLOGCAT\tOPTIONS_UNSUPPORTED\n'
fi
exit 0
