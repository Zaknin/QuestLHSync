# P3-A QuickCamera/HIDL read-only inventory

Status: SOURCE PREPARED / mock tests available, owner Windows and Pico verification PENDING.

The independent script pico/tools/p3a_quickcamera_inventory.py only reads from Android: build properties, root identity, actual library paths below present standard partition roots, and SHA-256 of verified paths. It does not guess vendor library file paths, copy ELF binaries, write to the headset, open cameras or change services.

It uses the previously SHA-pinned local P2 libpvrtrackingcamera.so and Android NDK llvm-readelf to extract actual DT_NEEDED QuickCamera names. Exact basename matching resolves device paths; multiple matches are retained as ambiguous. The live device camera ELF must hash to the P2 pinned SHA-256 before treating the libraries as the same firmware evidence.

On Windows, with Pico 4 Pro awake and ADB already connected to 192.168.23.12:5555, run:

    python -m unittest pico.tests.test_p3a_quickcamera_inventory -v
    python .\pico\tools\p3a_quickcamera_inventory.py

If ADB connection has expired, first run adb connect 192.168.23.12:5555. This is the known P2 serial, not a discovered current address; verify with adb devices.

Output is a private metadata-only JSON plus SHA-256 sidecar under canonical SMB \\192.168.23.63\Torrents\Codex\PicoLHSync\P3-A. The script verifies independent readback and renames .sha256 last, even for BLOCKED/PARTIAL results. No alternative evidence publication root is substituted.

INVENTORY_READY means only that matching library names, paths, hashes and P2 PVR ELF fingerprint were collected. It does NOT prove the hardware producer of the first FrameMetaDate timestamp or SOF/exposure/rolling shutter. No live corrections or time overrides. A later separately reviewed step may read-only copy only selected actual device libraries for private offline native analysis.

## 2026-10-17 P3-A bugfix: adb su -c remote shell

First live USB+Wi-Fi connected run returned BLOCKED with `/system/bin/sh: syntax error: unexpected 'do'`. This is a client-side quoting defect: `adb shell su -c <multiple words>` does not supply the entire script as one argument to `su -c`. The `root_shell()` wrapper now applies `shlex.quote(command)` before adb reconstructs its remote command; the inventory scan also searches only `*.so`, avoiding unnecessary non-library path output. New mock tests cover nested quotes, a for/do script and a full read-only inventory.

The previous BLOCKED evidence is retained on TrueNAS. The source fix is verified by GitHub readback, but the correction still requires a new owner Windows/Pico run. No change to the P2 optical gates or producer event semantics.
