"""Static safety/contract regression for the P3-A4 owner Windows-only extractor."""
import pathlib
import re
import unittest

SCRIPT = pathlib.Path(__file__).resolve().parents[1] / 'tools' / 'trace_p3a4_quickcamera_bridge.ps1'


class BridgeContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = SCRIPT.read_text(encoding='utf-8')

    def test_read_only_no_device_commands(self):
        self.assertNotRegex(self.src, r'(?mi)^\s*(?:&\s*)?(?:adb|fastboot|magisk)(?:\.exe)?\s')
        self.assertIn('NO ADB', self.src)

    def test_immutable_p2_and_p3_source_hashes(self):
        for digest in (
            'cf9e507f412ec33d62c2f720669fcdd093f1822c9cbf3adefd0a26a6b4d072ee',
            'fb22355acd35b9772a5538a7d1c49175641165ad0368e7c47e5831f5f1727017',
            'c3157e66d842dcdca148f1b98328bd5e7ce80c4ab9bbbacba895465556314f47',
        ):
            self.assertIn(digest, self.src)

    def test_gate_flags_fail_closed(self):
        for flag in ('exact_time', 'live_lighthouse_correction_allowed',
                     'mapping_verified', 'pose_verified', 'frame_meta_bridge_verified',
                     'physical_event_verified', 'binaries_copied_into_evidence'):
            self.assertRegex(self.src, re.escape(flag) + r'=\$false')

    def test_bounded_native_disassembly(self):
        self.assertIn('--start-address=', self.src)
        self.assertIn('--stop-address=', self.src)
        self.assertIn('0x1200', self.src)
        self.assertIn('llvm-objdump.exe', self.src)

    def test_evidence_is_private_and_last_marker(self):
        self.assertIn(r'\\192.168.23.63\Torrents\Codex\PicoLHSync\P3-A', self.src)
        self.assertIn('.sha256.part', self.src)
        self.assertIn('Move-Item -LiteralPath $markerPart', self.src)
        self.assertIn('SMB final integrity failed', self.src)

    def test_precise_pvr_symbol_provenance(self):
        # Old trace inadvertently selected the first four *unrelated*
        # QuickCameraClient dynamic symbols. Require exact ABI overloads.
        for piece in (
            'DeQueueFrame\\(native_handle\\*\\*, void\\*\\*,',
            'DeQueueFrame\\(native_handle\\*\\*, pico::',
            'DeQueueFrame\\(void\\*\\*, pico::',
            'QuickCameraClient::ConfigAndAllocBuffers',
            'QuickCameraClient::PrepareStreamOn',
            'QuickCameraClient::QuickCameraClient',
            'PvrCameraDeviceCallback::OnBufferReady',
        ):
            self.assertIn(piece, self.src)
        self.assertIn('Select-Object -Unique', self.src)
        self.assertIn('PVR exact symbol resolution failed', self.src)
        self.assertIn('PVR symbol size/address unsafe', self.src)
        self.assertIn('pvr_exact_targets', self.src)
        self.assertIn('p3a4.offline.bridge.v3', self.src)
        self.assertNotIn("Name=('09-pvr-symbol-' + $n)", self.src)

    def test_symbol_capture_is_in_exact_function_bounds(self):
        self.assertIn('From=$start; To=($start+$size)', self.src)
        self.assertIn("($w.To-$w.From) -gt 0x1200", self.src)

    def test_v3_hidl_callback_relocation_probe(self):
        self.assertIn("schema='p3a4.offline.bridge.v3'", self.src)
        self.assertIn('llvm-readelf.exe', self.src)
        self.assertIn("0x752b0", self.src)
        self.assertIn("0x75330", self.src)
        self.assertIn("R_AARCH64_RELATIVE", self.src)
        self.assertIn("callback_candidates", self.src)
        self.assertIn("callback_vtable_identity_verified'] = $false", self.src)
        self.assertIn("shared_buffer_identity_verified'] = $false", self.src)
        self.assertIn("Select-Object -First 8", self.src)
        self.assertRegex(self.src, r'To\s*=\s*\(\$target\s*\+\s*0x600\)')

    def test_native_powershell_parser(self):
        """Actually parse the .ps1: source-string checks cannot catch syntax bugs."""
        import os
        import shutil
        import subprocess
        import sys

        pwsh = shutil.which('pwsh') or shutil.which('pwsh.exe')
        if not pwsh:
            if sys.platform == 'win32':
                self.fail('PowerShell 7 executable missing on Windows host')
            self.skipTest('PowerShell 7 not installed on this non-Windows test host')
        env = os.environ.copy()
        env['PICO_A4_SCRIPT'] = str(SCRIPT.resolve())
        parse_only = (
            '$tokens = $null; $errors = $null; '
            '[void][System.Management.Automation.Language.Parser]::ParseFile('
            '$env:PICO_A4_SCRIPT, [ref]$tokens, [ref]$errors); '
            'if ($errors.Count) { '
            '$errors | ForEach-Object { [Console]::Error.WriteLine($_.ToString()) }; '
            'exit 3 }; exit 0'
        )
        run = subprocess.run(
            [pwsh, '-NoProfile', '-NonInteractive', '-Command', parse_only],
            env=env, capture_output=True, text=True, timeout=20,
        )
        self.assertEqual(0, run.returncode, run.stdout + '\n' + run.stderr)

    def test_v3_callback_loop_is_complete(self):
        self.assertIn('foreach ($line in $relocs) {', self.src)
        self.assertIn('foreach ($w in $windows) {', self.src)
        self.assertIn('callback_vtable_relocation_seen', self.src)
        self.assertIn('callback_vtable_identity_verified', self.src)
        self.assertIn('shared_buffer_identity_verified', self.src)
        self.assertIn("R_AARCH64_RELATIVE", self.src)
        self.assertNotIn("(R_AARCH64_\\S+)\\s+(.*)\n", self.src)

    def test_single_publish_tail_no_duplicate_blocks(self):
        # Protect against duplicate pasted suffix after the final JSON response.
        self.assertEqual(self.src.count("foreach ($line in $relocs) {"), 1)
        self.assertEqual(self.src.count("foreach ($w in $windows) {"), 1)
        self.assertEqual(self.src.count("Compress-Archive -LiteralPath"), 1)
        self.assertEqual(self.src.count("Move-Item -LiteralPath $markerPart"), 1)
        self.assertEqual(self.src.count("status='TRACE_CAPTURED_NOT_PROVEN'; zip="), 1)
        self.assertTrue(self.src.rstrip().endswith("| ConvertTo-Json -Compress"))

    def test_essential_regions_are_present(self):
        for address in ('0x664d0', '0x375d0', '0x38670', '0x38bc0',
                        '0x36860', '0x9494', '0x98e4', '0xa59c'):
            self.assertIn(address, self.src)


if __name__ == '__main__':
    unittest.main()
