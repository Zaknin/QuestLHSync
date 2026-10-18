import shutil
import subprocess
import unittest
from pathlib import Path


class TestP3A6ReadOnlyInventoryCollector(unittest.TestCase):
    def test_ps7_collector_contract_with_mock_adb_executor(self):
        pwsh = shutil.which('pwsh')
        if not pwsh:
            self.skipTest('PowerShell 7 is not installed; no device test is substituted')
        repo = Path(__file__).resolve().parents[2]
        harness = repo / 'pico' / 'tests' / 'p3a6_inventory_collector.tests.ps1'
        completed = subprocess.run(
            [pwsh, '-NoProfile', '-File', str(harness)],
            cwd=repo,
            text=True,
            capture_output=True,
            timeout=60,
            check=False,
        )
        self.assertEqual(
            completed.returncode,
            0,
            msg=f'PowerShell mock collector suite failed.\nstdout:\n{completed.stdout}\nstderr:\n{completed.stderr}',
        )
        self.assertIn('P3-A6 M1 PowerShell mock collector checks: 20/20 PASS', completed.stdout)

        tool = repo / 'pico' / 'tools' / 'collect_p3a6_inventory.ps1'
        dry_run = subprocess.run(
            [pwsh, '-NoProfile', '-File', str(tool), '--dry-run'],
            cwd=repo,
            text=True,
            capture_output=True,
            timeout=10,
            check=False,
        )
        self.assertEqual(dry_run.returncode, 3, msg=f'CLI dry-run must exit without device access.\n{dry_run.stderr}')
        self.assertIn('"status":"DRY_RUN"', dry_run.stdout)

    def test_generated_shell_probes_under_local_posix_shell(self):
        pwsh = shutil.which('pwsh')
        wsl = shutil.which('wsl.exe')
        if not pwsh or not wsl:
            self.skipTest('PowerShell 7 and WSL POSIX /bin/sh are required for this offline integration test')
        repo = Path(__file__).resolve().parents[2]
        harness = repo / 'pico' / 'tests' / 'p3a6_posix_shell_integration.tests.ps1'
        completed = subprocess.run(
            [pwsh, '-NoProfile', '-File', str(harness)],
            cwd=repo,
            text=True,
            capture_output=True,
            timeout=60,
            check=False,
        )
        self.assertEqual(
            completed.returncode,
            0,
            msg=f'Generated POSIX shell integration failed.\nstdout:\n{completed.stdout}\nstderr:\n{completed.stderr}',
        )
        self.assertIn('P3-A6 local POSIX shell integration:', completed.stdout)


if __name__ == '__main__':
    unittest.main()
