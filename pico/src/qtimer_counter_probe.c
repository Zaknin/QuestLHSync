/*
 * Pico P2: READ-ONLY native CNTVCT (Qualcomm PVR QTIMER candidate)
 * vs CLOCK_BOOTTIME / CLOCK_MONOTONIC.
 *
 * Uses the same ARM64 architectural registers present in the SHA-pinned
 * pvr::SnsLowLatBridge::qtimer_get_time_ns implementation. It does not
 * call any camera, Binder, SLAM, pose, or vendor APIs.
 *
 * Diagnostic only: matching the timer does NOT prove image timestamp
 * source or real physical exposure instant.
 */
#define _GNU_SOURCE
#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <time.h>
#include <unistd.h>

static uint64_t read_cntvct(void) {
    uint64_t ticks;
    __asm__ volatile("isb; mrs %0, cntvct_el0" : "=r"(ticks) :: "memory");
    return ticks;
}

static uint64_t read_cntfrq(void) {
    uint64_t hz;
    __asm__ volatile("mrs %0, cntfrq_el0" : "=r"(hz));
    return hz;
}

static int64_t ns_now(clockid_t which) {
    struct timespec t;
    if (clock_gettime(which, &t) != 0) return -1;
    return (int64_t)t.tv_sec * INT64_C(1000000000) + t.tv_nsec;
}

int main(void) {
    const uint64_t freq = read_cntfrq();
    if (!freq || freq > UINT64_C(1000000000)) {
        fprintf(stderr, "unexpected_CNTFRQ=%" PRIu64 "\n", freq);
        return 2;
    }

    puts("PICO_QTIMER_COUNTER_PROBE_V1");
    puts("mode=READ_ONLY_CNTVCT_AND_STANDARD_CLOCKS");
    puts("k0_timestamp_clock_verified=false");
    puts("physical_exposure_epoch_verified=false");
    puts("steamvr_pose_clock_verified=false");
    puts("live_lighthouse_correction_allowed=false");
    printf("cntfrq_hz=%" PRIu64 "\n", freq);
    puts("sample,cntvct_ticks,cntvct_ns,boot_mid_ns,mono_mid_ns,"
         "cntvct_minus_boot_ns,cntvct_minus_mono_ns,boot_minus_mono_ns,"
         "clock_read_bracket_ns");

    for (int i = 0; i < 8; ++i) {
        int64_t bb = ns_now(CLOCK_BOOTTIME);
        int64_t mb = ns_now(CLOCK_MONOTONIC);
        const uint64_t raw = read_cntvct();
        int64_t ma = ns_now(CLOCK_MONOTONIC);
        int64_t ba = ns_now(CLOCK_BOOTTIME);

        if (bb < 0 || mb < 0 || ma < mb || ba < bb || ba < 0) {
            fprintf(stderr, "clock_read_failure\n");
            return 3;
        }
        /* Keep full counter precision, no floating point or double epoch loss. */
        const uint64_t qns = (uint64_t)(((__uint128_t)raw *
                                        UINT64_C(1000000000)) / freq);
        if (qns > INT64_MAX) {
            fprintf(stderr, "cntvct_ns_overflow\n");
            return 4;
        }
        const int64_t boot = bb + (ba - bb) / 2;
        const int64_t mono = mb + (ma - mb) / 2;
        printf("%d,%" PRIu64 ",%" PRIu64 ",%" PRId64 ",%" PRId64 ","
               "%" PRId64 ",%" PRId64 ",%" PRId64 ",%" PRId64 "\n",
               i, raw, qns, boot, mono, (int64_t)qns - boot,
               (int64_t)qns - mono, boot - mono, ba - bb);
        fflush(stdout);
        if (i != 7) usleep(150000);
    }
    puts("result=HARDWARE_COUNTER_OBSERVATION_ONLY");
    return 0;
}
