"""Unit tests of offline K0 listener xref parser: no ELF/ADB needed."""
import tempfile
import unittest
from pathlib import Path

from pico.tools.audit_k0_listener_xrefs import (
    CONFIG_STORE, INSN, extract_range, find_matches,
    format_hits, parse_functions, sha256, vtable_target,
)


DISASM = """some header
0000000000001230 <pvr::SomeFactory::create()>:
  1230:       mov x0, x19
  1234:       ldr x1, [sp, #0x20]
  1238:       bl 0x6ec10 <pvr::PvrCameraDevice::setPvrImageListener(std::__1::shared_ptr<pvr::PvrImageListener>)@plt>
  123c:       str x11, [x9, #0x330]
  1240:       str x12, [x9, #0x338]
  1244:       ret
0000000000002000 <pvr::AnotherFunction()>:
  2000:       ldr x10, [x9, #0x330]
  2004:       bl 0xabc64 <pvr::CameraManager::CameraImageListener::onError(int)@plt>
"""


class ListenerAuditTests(unittest.TestCase):
    def test_function_ownership_and_call(self):
        lines, owners = parse_functions(DISASM)
        hits = find_matches(
            lines, owners,
            lambda s, fn: bool(INSN.match(s) and
                "setPvrImageListener" in s), max_matches=10
        )
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["at"], "1238")
        self.assertIn("SomeFactory", hits[0]["owner"])
        self.assertIn("1238", format_hits("listener", hits))

    def test_stores_separated_from_reads(self):
        lines, owners = parse_functions(DISASM)
        writes = find_matches(lines, owners, lambda s, fn: bool(CONFIG_STORE.match(s)))
        self.assertEqual({x["at"] for x in writes}, {"123c", "1240"})
        self.assertNotIn("2000", {x["at"] for x in writes})

    def test_function_range(self):
        lines, owners = parse_functions(DISASM)
        instructions = extract_range(lines, 0x1238, 0x1244)
        self.assertEqual(len(instructions), 3)
        self.assertIn("setPvrImageListener", instructions[0])

    def test_relocation_exact_vtable_slot(self):
        match = (
            "000000000015e6b0  0000054700000101 R_AARCH64_ABS64 "
            "00000000000abbfc _ZN3pvr13CameraManager19CameraImageListener"
            "16onFrameAvailableEPNS_16pvr_frame_item_tE + 0"
        )
        self.assertTrue(vtable_target(match))

    def test_relocation_wrong_slot_rejected(self):
        wrong = (
            "000000000015e6b8  0000054700000101 R_AARCH64_ABS64 "
            "00000000000abbfc _ZN3pvr13CameraManager19CameraImageListener"
            "16onFrameAvailableEPNS_16pvr_frame_item_tE + 0"
        )
        self.assertFalse(vtable_target(wrong))

    def test_relocation_wrong_target_rejected(self):
        wrong_target = (
            "000000000015e6b0  0000054700000101 R_AARCH64_ABS64 "
            "00000000000abc64 _ZN3pvr13CameraManager19CameraImageListener"
            "16onFrameAvailableEPNS_16pvr_frame_item_tE + 0"
        )
        self.assertFalse(vtable_target(wrong_target))

    def test_sha256_streaming(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "fixture.bin"
            target.write_bytes(b"abc")
            self.assertEqual(
                sha256(target),
                "ba7816bf8f01cfea414140de5dae2223b00361a"
                "396177a9cb410ff61f20015ad"
            )


if __name__ == "__main__":
    unittest.main()
