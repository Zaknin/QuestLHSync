import shutil
import subprocess
import unittest
from pathlib import Path


class TestP3A6CameraNodeCollector(unittest.TestCase):
    def test_powershell_camera_node_contract(self):
        pwsh = shutil.which('pwsh')
        wsl = shutil.which('wsl.exe')
        if not pwsh or not wsl:
            self.skipTest('PowerShell 7 and WSL POSIX /bin/sh are required for offline M2 integration tests')
        repo = Path(__file__).resolve().parents[2]
        harness = repo / 'pico' / 'tests' / 'p3a6_camera_nodes.tests.ps1'
        completed = subprocess.run(
            [pwsh, '-NoProfile', '-File', str(harness)],
            cwd=repo,
            text=True,
            capture_output=True,
            timeout=90,
            check=False,
        )
        self.assertEqual(
            completed.returncode,
            0,
            msg=f'M2 PowerShell/POSIX contract suite failed.\nstdout:\n{completed.stdout}\nstderr:\n{completed.stderr}',
        )
        self.assertIn('P3-A6-M2 camera node checks:', completed.stdout)

    def test_dry_run_cli_never_calls_adb(self):
        pwsh = shutil.which('pwsh')
        if not pwsh:
            self.skipTest('PowerShell 7 is required for the M2 dry-run CLI test')
        repo = Path(__file__).resolve().parents[2]
        runner = repo / 'pico' / 'tools' / 'collect_p3a6_camera_node_inventory.ps1'
        completed = subprocess.run(
            [pwsh, '-NoProfile', '-File', str(runner), '--dry-run'],
            cwd=repo,
            text=True,
            capture_output=True,
            timeout=10,
            check=False,
        )
        self.assertEqual(completed.returncode, 3, msg=f'M2 dry-run must be device-free.\n{completed.stderr}')
        self.assertIn('"status":"DRY_RUN"', completed.stdout)


if __name__ == '__main__':
    unittest.main()
