"""Synthetic candidate tracing of ADRP+Q-load native constant references."""
import unittest

from pico.tools.audit_k0_literal_references import find_pc_relative_refs


class LiteralReferenceTests(unittest.TestCase):
    def test_known_constructor_q1_ref_is_detected(self):
        code = """
00000000000a70e0 <pvr::CameraManager::CameraManager()>:
   a717c: adrp x9, 0x73000
   a7190: mov x28, x20
   a7194: str q1, [sp, #0x40]
   a7198: ldr q1, [x9, #0x170]
"""
        hits = find_pc_relative_refs(code)
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["literal_va"], "0x73170")
        self.assertIn("CameraManager", hits[0]["owner"])

    def test_alt_pair_q1_ref_is_detected(self):
        code = """
00000000000a1000 <pvr::CameraManager::selectMode()>:
  a1000: adrp x8, 0x73000
  a1004: ldr q0, [x8, #0x160]
  a1008: stp q0, q0, [x19]
"""
        hits = find_pc_relative_refs(code)
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["literal_va"], "0x73160")

    def test_wrong_base_page_is_not_an_alt_ref(self):
        code = """
00000000000a1000 <pvr::CameraManager::other()>:
  a1000: adrp x8, 0x74000
  a1004: ldr q0, [x8, #0x160]
"""
        self.assertEqual(find_pc_relative_refs(code), [])

    def test_clobbered_base_register_is_not_proven(self):
        code = """
00000000000a1000 <pvr::CameraManager::other()>:
  a1000: adrp x8, 0x73000
  a1004: mov x8, x19
  a1008: ldr q0, [x8, #0x160]
"""
        self.assertEqual(find_pc_relative_refs(code), [])

    def test_adpr_register_tracking_resets_between_functions(self):
        code = """
00000000000a1000 <pvr::CameraManager::one()>:
  a1000: adrp x8, 0x73000
00000000000a1100 <pvr::CameraManager::two()>:
  a1100: ldr q0, [x8, #0x160]
"""
        self.assertEqual(find_pc_relative_refs(code), [])

    def test_call_invalidates_volatile_page_register(self):
        code = """
00000000000a1000 <pvr::CameraManager::other()>:
  a1000: adrp x8, 0x73000
  a1004: bl 0x155680 <__android_log_print@plt>
  a1008: ldr q0, [x8, #0x160]
"""
        self.assertEqual(find_pc_relative_refs(code), [])

    def test_adrp_add_address_formation_is_candidate_only(self):
        code = """
00000000000a1000 <pvr::CameraManager::profile()>:
  a1000: adrp x8, 0x73000
  a1004: add x0, x8, #0x160
"""
        hits = find_pc_relative_refs(code)
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["literal_va"], "0x73160")
        self.assertEqual(hits[0]["classification"],
                         "PC_RELATIVE_ADRP_ADD_ADDRESS_CANDIDATE")

    def test_unrelated_offset_not_counted(self):
        code = """
00000000000a1000 <pvr::CameraManager::other()>:
  a1000: adrp x8, 0x73000
  a1004: ldr q0, [x8, #0x150]
"""
        self.assertEqual(find_pc_relative_refs(code), [])


if __name__ == "__main__":
    unittest.main()
