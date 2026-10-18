# P3-A4E correction: Android RELR relocation decoding (2026-10-18)

## Owner's previous run
`python -m unittest pico.tests.test_p3a4e_resolve_callback_relocations -v`: **8/8 PASS**.
`python pico/tools/p3a4e_resolve_callback_relocations.py`: `NO_EXECUTABLE_CANDIDATE_NOT_PROVEN`, `relocations_parsed=0`, `relocations_requested=12`, `disassembly_candidates=0`. Private evidence: `p3a4e-reloc-20261018T100955Z-15fba8fd.{zip,json,sha256}` under canonical TrueNAS `P3-A`. The 0/12 is a **decoder coverage failure, not evidence that the callback is absent**.

## Root cause and independent format verification
The initial `Elf64Arm.relocated_slots()` supported only conventional `SHT_REL (9)` and `SHT_RELA (4)`. The actual same-firmware SHA-pinned QuickCamera producer ELF package contains **Android packed relocation formats**:
- Vendor `quickcamera.core.so`: `.rela.dyn` `SHT_ANDROID_RELA = 0x60000002`, `.relr.dyn` `SHT_ANDROID_RELR = 0x6fffff00`; independently decoded **77** RELR relocation slots.
- Vendor `pico.camera.quickcamera.quickcameramodule@1.0-impl.so`: same section formats; independently decoded **35** RELR relocation slots.
- Both real ELF64 AArch64 binaries in canonical SHA-pinned P3-A2 producer ZIP were inspected without Pico or Android runtime interaction. A synthetic Android RELR anchor plus bitmap with four slots also decoded successfully.

GNU/LLVM `readelf --relocs` often expands RELR into apparent `R_AARCH64_RELATIVE` slot rows **without addends**. This is consistent with the 12 slots reported by P3-A4D in PVR `0x752b0..0x75330`, but PVR's exact section encoding must still be verified on the owner's private ELF. The initial decoder's omission of SHT_ANDROID_RELR / SHT_RELR explains why an expanded textual relocation list can coexist with `relocations_parsed=0`.

## Code correction
`pico/tools/p3a4e_resolve_callback_relocations.py` adds `SHT_ANDROID_RELR (0x6fffff00)` and standard `SHT_RELR (19)` support. Decodes RELR direct addresses and bitmap-run pointer slots, reads the **implicit addend from file-backed pointer-sized slot content**, then bounds-checks candidates against executable `PT_LOAD`. Existing REL/RELA decoding and SHA checks are retained. Report includes the recognized relocation section types.

Four new synthetic tests exercise Android RELR bitmap expansion/implicit addends, standard RELR, bitmap before anchor rejection, and malformed entry-size rejection. The owner should run the existing and new tests on Windows before an offline trace. No raw ELF bytes, disassemblies, or private camera data committed publicly.

**Do not** claim an exact HIDL↔PVR memory identity, physical SOF/optical timestamp semantics, source fallback frequency or clock alignment from this tool. All safety gates remain false: `exact_time=false`, `live_lighthouse_correction_allowed=false`, `mapping_verified=false`, `pose_verified=false`.

PowerShell 7 (Pico OFF):

```powershell
Set-Location C:\Dev\PicoLHSync
git pull --ff-only
if ($LASTEXITCODE -ne 0) { throw 'Git pull failed' }
python -m unittest pico.tests.test_p3a4e_resolve_callback_relocations -v
if ($LASTEXITCODE -ne 0) { throw 'Tests failed' }
python .\pico\tools\p3a4e_resolve_callback_relocations.py
if ($LASTEXITCODE -ne 0) { throw 'Offline resolver failed' }
```

Expected: **12** synthetic tests. We have 12 observed relocation slots; number of successfully decoded slots / executable candidates is not asserted before owner host execution. The new canonical private report should use a new `p3a4e-reloc-...` name; SHA sidecar is written last. Review must then inspect vtable callback disassembly candidates and link shared buffers to `QuickCameraClient+0x60`, not merely infer identity from layout agreement.
