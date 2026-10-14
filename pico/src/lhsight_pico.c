// Pico 4 Pro K0 -> QuestLHSync F lines. Reuses Quest's original smean() and blobs() (not a new detector).
// PicoFrameReader (app_process) owns Binder/ashmem; no injection or camera controls.
#define _GNU_SOURCE
#include <errno.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

// Frida CModule declares its own clock_gettime signature; provide an ABI-compatible wrapper.
#define clock_gettime qlhs_cm_clock_gettime
#include "../../magisk/src/lhsight.c"
#undef clock_gettime
struct st S;
int qlhs_cm_clock_gettime(int clk, struct ts *out) {
    struct timespec t;
    if (clock_gettime(clk, &t)) return -1;
    out->s = t.tv_sec;
    out->ns = t.tv_nsec;
    return 0;
}

#define W 640
#define H 480
#define BYTES (W * H)
#define CELLS ((W / 16) * (H / 16))
#define HEADER_BYTES 40
static volatile sig_atomic_t stopping;
static pid_t java_pid;
static void terminated(int sig) { (void)sig; stopping = 1; if (java_pid > 0) kill(java_pid, SIGTERM); }

static uint32_t be32(const unsigned char *p) {
    return ((uint32_t)p[0] << 24) | ((uint32_t)p[1] << 16) | ((uint32_t)p[2] << 8) | p[3];
}
static uint64_t be64(const unsigned char *p) { return ((uint64_t)be32(p) << 32) | be32(p + 4); }
// Complete reads; stdout is reserved for valid QuestLHSync text records, never binary.
static int get_bytes(int fd, unsigned char *buf, size_t n) {
    size_t got = 0;
    while (got < n && !stopping) {
        ssize_t k = read(fd, buf + got, n - got);
        if (k == 0) return 0;
        if (k < 0) { if (errno == EINTR) continue; return -1; }
        got += (size_t)k;
    }
    return got == n ? 1 : 0;
}
static int valid_camera(uint32_t c) { return c == 0 || c == 3 || c == 4 || c == 5; }
static int spawn_java(const char *jar, int *input) {
    int fd[2];
    if (pipe(fd)) return -1;
    java_pid = fork();
    if (java_pid == 0) {
        close(fd[0]);
        if (dup2(fd[1], STDOUT_FILENO) < 0) _exit(126);
        close(fd[1]);
        setenv("CLASSPATH", jar, 1);
        execl("/system/bin/app_process", "app_process", "/system/bin", "PicoFrameReader", (char *)NULL);
        _exit(127);
    }
    close(fd[1]);
    if (java_pid < 0) { close(fd[0]); return -1; }
    *input = fd[0];
    return 0;
}

int main(int argc, char **argv) {
    if (argc != 2) { fprintf(stderr, "usage: pico_lhsight /path/to/PicoFrameReader.jar\n"); return 2; }
    signal(SIGPIPE, SIG_IGN);
    signal(SIGTERM, terminated);
    signal(SIGINT, terminated);
    int fd;
    if (spawn_java(argv[1], &fd)) { perror("Pico app_process spawn"); return 2; }

    // Reuse the exact Quest detector's blob implementation. K0 is ALREADY the short exposure;
    // do not apply the Quest Pro long/short/long exposure classifier to Pico frames.
    static u8 pixels[BYTES];
    static u16 cells[CELLS];
    static int labels[CELLS];
    static char output_ring[OUTCAP];
    set_bufs(pixels, cells, labels, output_ring, 16); // K0 dark-room threshold (experimental)
    uint64_t frames = 0, scans = 0, scan_time_ns = 0;
    uint64_t last_heartbeat_ns = 0;
    unsigned char head[HEADER_BYTES];
    int result = 0;
    while (!stopping) {
        int rc = get_bytes(fd, head, sizeof head);
        if (rc <= 0) { if (!stopping) result = rc < 0 ? 3 : 1; break; }
        uint32_t magic = be32(head), cam = be32(head + 4);
        uint64_t seq = be64(head + 8);
        uint64_t vendor_ts = be64(head + 16);
        uint64_t copied_ns = be64(head + 24);
        uint32_t exposure = be32(head + 32), length = be32(head + 36);
        (void)vendor_ts; // candidate clock domain still unverified
        if (magic != 0x50465231 || !valid_camera(cam) || length != BYTES ||
            exposure != 4 || (seq & 1u) == 0 || copied_ns == 0) {
            fprintf(stderr, "W Pico invalid frame header: magic=%08x cam=%u seq=%llu len=%u exposure=%u\n",
                    magic, cam, (unsigned long long)seq, length, exposure);
            result = 3; break;
        }
        rc = get_bytes(fd, pixels, BYTES);
        if (rc <= 0) { if (!stopping) result = 3; break; }
        const int mean = smean(pixels, BYTES); // Quest unit: pixel average multiplied by 10
        u64 sx[MAXB], sy[MAXB];
        u32 np[MAXB];
        int peak[MAXB];
        memset(S.hot, 0, CELLS);
        uint64_t before = now();
        int count = blobs(W, H, 250, 1, 0, sx, sy, np, peak);
        int threshold = mean * 4 / 10; // 4x actual per-pixel mean
        if (threshold < S.thr) threshold = S.thr;
        if (threshold < 250) count = blobs(W, H, threshold, 0, count, sx, sy, np, peak);
        scan_time_ns += now() - before;
        scans++;
        // Until vendor timestamps are validated, use the MONOTONIC snapshot time.
        // That carries capture lag; this P1 transport is NOT yet pose-calibration ready.
        printf("F %u %u %llu %d %d", cam, (unsigned)seq,
               (unsigned long long)(copied_ns / 1000), mean, count);
        for (int i = 0; i < count; i++)
            printf(" %llu %llu %u %d", (unsigned long long)(sx[i] / np[i]),
                   (unsigned long long)(sy[i] / np[i]), np[i], peak[i]);
        putchar('\n');
        fflush(stdout);
        frames++;
        if (copied_ns - last_heartbeat_ns >= 1000000000ull) {
            printf("T %llu scans %llu scan_us %llu drops 0 faults 0 polls %llu\n",
                   (unsigned long long)(copied_ns / 1000),
                   (unsigned long long)scans,
                   (unsigned long long)(scan_time_ns / (scans ? scans : 1) / 1000),
                   (unsigned long long)frames);
            fflush(stdout);
            last_heartbeat_ns = copied_ns;
        }
    }
    close(fd);
    if (java_pid > 0) {
        kill(java_pid, SIGTERM);
        waitpid(java_pid, NULL, 0);
    }
    if (result) fprintf(stderr, "W Pico camera stream stopped (%d); lhsyncd will retry\n", result);
    return result;
}
