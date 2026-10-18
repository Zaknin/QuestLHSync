"""Integration regression for the private P3-A5 ioctl2 wrapper trace."""
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "pico" / "tools" / "trace_p3a4_quickcamera_bridge.ps1"
BUILD = ROOT / "pico" / "build"


class Ioctl2TraceTests(unittest.TestCase):
    def test_private_trace_captures_exact_ioctl2_wrapper_extent(self):
        pwsh = shutil.which("pwsh") or shutil.which("pwsh.exe")
        if not pwsh:
            if sys.platform == "win32":
                self.fail("PowerShell 7 executable missing on Windows host")
            self.skipTest("PowerShell 7 is not installed")

        sdk = pathlib.Path(os.environ.get("ANDROID_HOME") or os.environ.get("ANDROID_SDK_ROOT") or
                           pathlib.Path(os.environ.get("LOCALAPPDATA", "")) / "Android" / "Sdk")
        ndk_root = sdk / "ndk"
        objdump_candidates = list(ndk_root.glob(
            "*/toolchains/llvm/prebuilt/windows-x86_64/bin/llvm-objdump.exe"))
        pvr_candidates = list(BUILD.glob("p2-static-clock-private-*/libpvrtrackingcamera.so"))
        if not objdump_candidates or not pvr_candidates:
            self.skipTest("Pinned local ELF or Android NDK objdump is unavailable")

        initial_private_dirs = set(BUILD.glob("p3a4-bridge-*-private"))
        with tempfile.TemporaryDirectory(prefix="p3a5-ioctl2-output-") as output_root:
            try:
                run = subprocess.run(
                    [pwsh, "-NoProfile", "-NonInteractive", "-File", str(SCRIPT),
                     "-OutputRoot", output_root],
                    capture_output=True, text=True, timeout=120,
                )
                self.assertEqual(0, run.returncode, run.stdout + "\n" + run.stderr)
                result = json.loads(run.stdout.strip().splitlines()[-1])
                manifest_path = pathlib.Path(result["manifest"])
                manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))

                self.assertEqual("p3a4.offline.bridge.v4", manifest["schema"])
                matches = [target for target in manifest["pvr_exact_targets"]
                           if target["name"] == "19-pvr-CSLHwInternalDefaultIoctl2-envelope"]
                self.assertEqual(1, len(matches), manifest["pvr_exact_targets"])
                self.assertEqual(0x6C2F8, matches[0]["address"])
                self.assertEqual(0xE0, matches[0]["size"])
                self.assertIn("CSLHwInternalDefaultIoctl2(unsigned int, void*, unsigned int)",
                              matches[0]["symbol"])

                windows = [window for window in manifest["windows"]
                           if window["name"] == "19-pvr-CSLHwInternalDefaultIoctl2-envelope"]
                self.assertEqual([{"name": "19-pvr-CSLHwInternalDefaultIoctl2-envelope",
                                   "input": "pvr", "start": 0x6C2F8, "end": 0x6C3D8}], windows)
            finally:
                for path in set(BUILD.glob("p3a4-bridge-*-private")) - initial_private_dirs:
                    resolved = path.resolve()
                    if resolved.parent == BUILD.resolve() and path.name.startswith("p3a4-bridge-"):
                        shutil.rmtree(resolved)


if __name__ == "__main__":
    unittest.main()
