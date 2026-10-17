# P3-A2 — Private QuickCamera producer extraction

Date: 2026-10-17. P3-A1 result: INVENTORY_READY. Canonical inventory: p3a-inventory-20261017T135048Z-e80db5d2.json, SHA-256 4f13897f524c189e3a4f4995ea5f615ab6c5b3fbbe2b97cfeaa2422baf0c3be7.

The installed AArch64 libpvrtrackingcamera.so matches the P2 pinned SHA at /system/lib64/libpvrtrackingcamera.so. Eight actual producer-candidate ELFs were inventoried: three QuickCamera DT_NEEDED libraries in both /system/lib64 and /vendor/lib64 (different SHA-256), plus /vendor/lib64/hw/pico.camera.quickcamera.quickcameramodule@1.0-impl.so and /vendor/lib64/quickcamera.core.so. No evidence proves which matching system/vendor copy is loaded at runtime.

## Read-only collector

From the Windows repo root with Pico awake and wireless ADB device 192.168.23.12:5555:

    git pull --ff-only
    python -m unittest pico.tests.test_p3a_collect_producers -v
    python .\pico\tools\p3a_collect_producers.py

The collector discovers the latest INVENTORY_READY inventory under the canonical SMB root and checks its .sha256 commit sidecar against its contents. It verifies P2 matching camera SHA and safety gates, then checks the live firmware fingerprint. It consumes only actual source paths from that inventory, not guessed library paths.

Device actions are strictly read-only: adb get-state, getprop, root sha256sum (before AND after extraction), and adb pull. No adb push, installation, vendor edits, camera opens, SLAM hooks, calibration changes, Magisk operations, or SteamVR driver activity. Every downloaded ELF is verified against its inventoried SHA-256 and ELF64/AArch64 headers. Verified local copies are in an ignored pico/build/p3a-producers-*-private directory.

An archive with only SHA-verified ELF files, plus a manifest containing both successes and failures, is published to the canonical TrueNAS root:

    \\192.168.23.63\Torrents\Codex\PicoLHSync\P3-A\p3a-producers-*.zip

A sibling .manifest.json and .sha256 are published by .part -> independent SHA readback -> rename, with the .sha256 sidecar last. PARTIAL and BLOCKED packages are preserved. Google Drive Cloud Sync is a downstream mirror. No proprietary ELF, private calibration, or device capture data go to GitHub.

PACKAGE_READY means the eight discovered producer candidates were acquired with verified bytes. It does NOT prove the runtime-selected HIDL module nor the provenance, epoch or SOF/exposure/rolling-shutter meaning of FrameMetaDate first word. Next is offline ELF DT_NEEDED, interface/vtable and clock source tracing. Keep observe_only=true, exact_time=false, live_lighthouse_correction_allowed=false, mapping_verified=false, pose_verified=false.

Source prepared; Linux isolated mock 8/8 PASS; owner Windows and real Pico extraction tests pending.
