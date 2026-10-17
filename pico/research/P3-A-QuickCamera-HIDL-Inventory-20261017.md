# P3-A QuickCamera/HIDL read-only inventory

Status: SOURCE PREPARED / MOCK 8 of 8 PASS on Linux / Windows and Pico owner run PENDING.

The independent script pico/tools/p3a_quickcamera_inventory.py only reads from Android: build properties, root identity, actual library paths below present standard partition roots, and SHA-256 of verified paths. It does not guess vendor library file paths, copy ELF binaries, write to the headset, open cameras or change services.

It uses the previously SHA-pinned local P2 libpvrtrackingcamera.so and Android NDK llvm-readelf to extract actual DT_NEEDED QuickCamera names. Exact basename matching resolves device paths; multiple matches are retained as ambiguous. The live device camera ELF must hash to the P2 pinned SHA-256 before treating the libraries as the same firmware evidence.

On Windows, with Pico 4 Pro awake and ADB already connected to 192.168.23.12:5555, run:

    python -m unittest pico.tests.test_p3a_quickcamera_inventory -v
    python .\pico\tools\p3a_quickcamera_inventory.py

If ADB connection has expired, first run adb connect 192.168.23.12:5555. This is the known P2 serial, not a discovered current address; verify with adb devices.

Output is a private metadata-only JSON plus SHA-256 sidecar under canonical SMB \\192.168.23.63\Torrents\Codex\PicoLHSync\P3-A. The script verifies independent readback and renames .sha256 last, even for BLOCKED/PARTIAL results. No alternative evidence publication root is substituted.

INVENTORY_READY means only that matching library names, paths, hashes and P2 PVR ELF fingerprint were collected. It does NOT prove the hardware producer of the first FrameMetaDate timestamp or SOF/exposure/rolling shutter. No live corrections or time overrides. A later separately reviewed step may read-only copy only selected actual device libraries for private offline native analysis.
