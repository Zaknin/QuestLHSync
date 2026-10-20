#!/system/bin/sh
# Fixed shell-protocol check. The nonzero status is intentional and contains
# no device data; the host must receive the exact marker and exit code 23.
printf 'P3A28D\tSHELL_V2\tOK\n'
exit 23
