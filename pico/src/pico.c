// Pico 4 Pro implementation of src/headset/headset.h; shares the original lhsyncd TCP/UDP daemon.
#define _GNU_SOURCE
#include <android/log.h>
#include <sys/system_properties.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
#include <sys/types.h>
#include "headset.h"

const char *const hs_capture_name = "pico_lhsight";
static const char *moddir = "/data/adb/modules/questlhsync_pico";

void hs_log(const char *line) {
    __android_log_print(ANDROID_LOG_INFO, "QuestLHSync-Pico", "%s", line);
}
void hs_init(int argc, char **argv) {
    if (argc > 1) moddir = argv[1];
    hs_log("Pico camera backend: Binder read-only K0; no tracking modifications");
}
void hs_device_info(char *serial, char *model, char *fw, size_t n) {
    (void)n; // lhsyncd passes PROP_VALUE_MAX-sized buffers
    __system_property_get("ro.serialno", serial);
    __system_property_get("ro.product.model", model);
    __system_property_get("ro.build.version.incremental", fw);
    if (!model[0]) strcpy(model, "PICO 4 Pro");
}
// P2: translate the headset's factory sensor.yaml omni/radtan calibration to the
// model understood by src/driver/sync.cpp. Never invent camera extrinsics.
int hs_calibration(char **data, size_t *len, char *name, size_t n) {
    *data = NULL; *len = 0;
    snprintf(name, n, "Pico factory omni/radtan calibration adapter not implemented (P2)");
    return -1;
}
pid_t hs_capture_start(int out_fd, char *msg, size_t n) {
    char program[512], jar[512];
    snprintf(program, sizeof program, "%s/pico_lhsight", moddir);
    snprintf(jar, sizeof jar, "%s/PicoFrameReader.jar", moddir);
    if (access(program, X_OK) || access(jar, R_OK)) {
        snprintf(msg, n, "Pico reader missing from module");
        return 0;
    }
    pid_t pid = fork();
    if (pid == 0) {
        setsid();
        dup2(out_fd, STDOUT_FILENO);
        dup2(out_fd, STDERR_FILENO);
        int nil = open("/dev/null", O_RDONLY);
        if (nil >= 0) { dup2(nil, STDIN_FILENO); close(nil); }
        for (int fd = 3; fd < 1024; fd++) close(fd);
        execl(program, "pico_lhsight", jar, (char *)NULL);
        _exit(127);
    }
    if (pid < 0) return -1;
    snprintf(msg, n, "Pico 4 Pro K0 camera reader started (pid %d)", pid);
    return pid;
}
