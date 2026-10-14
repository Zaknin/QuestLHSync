DEV=$(getprop ro.product.model)
ui_print "- Experimental QuestLHSync Pico 4 Pro P1 ($DEV)"
ui_print "- Read-only SLAM cameras via pvr.ITrackingService / K0"
ui_print "- P1 streams spots over Wi-Fi, but PC calibration is NOT implemented yet"
ui_print "- Do not use this version to apply SteamVR tracking corrections"
set_perm "$MODPATH/lhsyncd" 0 0 0755
set_perm "$MODPATH/pico_lhsight" 0 0 0755
set_perm "$MODPATH/PicoFrameReader.jar" 0 0 0644
