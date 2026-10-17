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
        self.assertNotRegex(self.src.lower(), r'\badb\b|\bfastboot\b|\bmagisk\b')
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

    def test_essential_regions_are_present(self):
        for address in ('0x664d0', '0x375d0', '0x38670', '0x38bc0',
                        '0x36860', '0x9494', '0x98e4', '0xa59c'):
            self.assertIn(address, self.src)


if __name__ == '__main__':
    unittest.main()
