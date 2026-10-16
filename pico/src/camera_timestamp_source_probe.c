/*
 * Pico P2 READ-ONLY Android Camera2 timestamp-source discovery.
 *
 * This queries ONLY camera ID enumeration and static characteristics.
 * It NEVER calls ACameraManager_openCamera, creates sessions, or starts streams.
 * Public Camera2 IDs are NOT proven to correspond to pvrtracking K0 Binder IDs.
 * Zero calibration / pose / image writes. Android 10 / API 29 arm64.
 */
#include <camera/NdkCameraManager.h>
#include <camera/NdkCameraMetadata.h>
#include <camera/NdkCameraMetadataTags.h>
#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <time.h>

static int64_t clock_ns(clockid_t clock_id) {
    struct timespec t;
    if (clock_gettime(clock_id, &t) != 0) return -1;
    return (int64_t)t.tv_sec * INT64_C(1000000000) + t.tv_nsec;
}

static const char *source_name(uint8_t source) {
    switch (source) {
        case ACAMERA_SENSOR_INFO_TIMESTAMP_SOURCE_UNKNOWN: return "UNKNOWN";
        case ACAMERA_SENSOR_INFO_TIMESTAMP_SOURCE_REALTIME: return "REALTIME";
        default: return "OTHER";
    }
}

int main(void) {
    printf("PICO_CAMERA2_TS_SOURCE_PROBE_V1\n");
    printf("mode=ENUMERATE_STATIC_CHARACTERISTICS_ONLY\n");
    printf("k0_camera2_id_mapping_verified=false\n");
    printf("physical_exposure_epoch_verified=false\n");
    printf("live_lighthouse_correction_allowed=false\n");
    printf("boottime_ns=%" PRId64 "\n", clock_ns(CLOCK_BOOTTIME));
    printf("monotonic_ns=%" PRId64 "\n", clock_ns(CLOCK_MONOTONIC));

    ACameraManager *manager = ACameraManager_create();
    if (!manager) {
        fprintf(stderr, "camera_manager_create_failed\n");
        return 2;
    }

    ACameraIdList *ids = NULL;
    camera_status_t status = ACameraManager_getCameraIdList(manager, &ids);
    if (status != ACAMERA_OK || !ids) {
        fprintf(stderr, "camera_id_enumeration_failed status=%d\n", (int)status);
        ACameraManager_delete(manager);
        return 3;
    }

    const int camera_count = ids->numCameras;
    printf("camera2_exposed_count=%d\n", camera_count);
    int failures = 0;
    for (int i = 0; i < ids->numCameras; ++i) {
        const char *id = ids->cameraIds[i];
        ACameraMetadata *meta = NULL;
        status = ACameraManager_getCameraCharacteristics(manager, id, &meta);
        if (status != ACAMERA_OK || !meta) {
            printf("camera2_id=%s source=ERROR status=%d\n", id, (int)status);
            ++failures;
            continue;
        }

        ACameraMetadata_const_entry entry;
        status = ACameraMetadata_getConstEntry(
            meta, ACAMERA_SENSOR_INFO_TIMESTAMP_SOURCE, &entry);
        if (status != ACAMERA_OK || entry.count != 1 ||
            entry.type != ACAMERA_TYPE_BYTE) {
            printf("camera2_id=%s source=ABSENT_OR_INVALID status=%d\n", id, (int)status);
            ++failures;
        } else {
            uint8_t raw = entry.data.u8[0];
            printf("camera2_id=%s source=%s raw=%u\n",
                   id, source_name(raw), (unsigned)raw);
            if (raw != ACAMERA_SENSOR_INFO_TIMESTAMP_SOURCE_REALTIME &&
                raw != ACAMERA_SENSOR_INFO_TIMESTAMP_SOURCE_UNKNOWN) ++failures;
        }
        ACameraMetadata_free(meta);
    }
    ACameraManager_deleteCameraIdList(ids);
    ACameraManager_delete(manager);
    printf("result=%s\n", camera_count == 0 ? "NO_PUBLIC_CAMERAS" :
        (failures ? "PARTIAL_STATIC_METADATA" : "STATIC_METADATA_ONLY"));
    return camera_count == 0 ? 5 : (failures ? 4 : 0);
}
