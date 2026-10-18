# P3-A4E — decode callback vtable R_AARCH64_RELATIVE addends from pinned ELF64

Date: 2026-10-18. Phase is **offline only**, no Pico/ADB/SteamVR access, no runtime injection.

## Verified private input

Canonical TrueNAS / downstream Google Drive evidence:
- `p3a4-bridge-20261018T093025Z-a991ee47.zip` SHA-256 `3221850d821d9659de0561918a7629acae6c31b41f33cace1db3bf8334746f83`
- `p3a4-bridge-20261018T093025Z-a991ee47.json` SHA-256 `d382409178aa92ff844c9c0b5a91fdd7195be89dd00dfbd1ca1e290cfa862f96`
- PVR pinned SHA-256 `cf9e507f412ec33d62c2f720669fcdd093f1822c9cbf3adefd0a26a6b4d072ee`.

The sidecar independently matches both files. The JSON has `schema=p3a4.offline.bridge.v3`, `TRACE_CAPTURED_NOT_PROVEN`, 15 disassembly windows, and **12** `R_AARCH64_RELATIVE` relocations at offsets spanning `0x752B0–0x75328`. The prior v3 script captured **zero** candidate callback function windows because `llvm-readelf --relocs` omitted relocation addends in its textual output, although the slot and relocation type were visible.

**Do not infer callback absence from an empty candidate list.** There are actual relocation entries. The follow-up needs raw ELF64 data, not repeated capture or regex changes.

## New implementation

`pico/tools/p3a4e_resolve_callback_relocations.py`: pure standard-library Python 3, independently parses ELF64/AArch64 PT_LOAD mappings and SHT_RELA/SHT_REL sections. For `R_AARCH64_RELATIVE` and exact 0x752B0..0x75330 target slot range:
- RELA: uses the signed explicit r_addend from the relocation entry;
- REL: uses the implicit addend stored at the mapped relocation slot;
- requires a candidate target to lie inside a file-backed executable PT_LOAD region before disassembly.
- SHA-checks the private P2 ELF, verifies the newest final P3-A4D JSON and ZIP against their published .sha256 marker, requires the original safety gates, and cross-matches actual relocation slots to prior observed report slots.
- Up to eight distinct candidate executable addresses get bounded +0x600 byte `llvm-objdump` text excerpts; findings, JSON, ZIP and final-last SHA-256 are **private**, published to canonical TrueNAS `P3-A`. No ELF copied into evidence or GitHub.
- New `pico/tests/test_p3a4e_resolve_callback_relocations.py`: 8 offline mock tests (synthetic little-endian AArch64 ELF64 with explicit RELA and implicit REL, executable filtering, malformed/wrong architecture, hash verification, atomic publishing). The 8 tests have passed locally in the development container. Owner Windows run is pending.

Command on owner's PowerShell 7 / Windows 11:

```powershell
Set-Location C:\Dev\PicoLHSync
git pull --ff-only
if ($LASTEXITCODE) { throw 'Git pull failed' }
python -m unittest pico.tests.test_p3a4e_resolve_callback_relocations -v
if ($LASTEXITCODE) { throw 'Tests failed' }
python .\pico\tools\p3a4e_resolve_callback_relocations.py
if ($LASTEXITCODE) { throw 'P3-A4E resolver failed' }
```

Expected output: `relocations_requested=12` if source report is unchanged. Number of decoded, executable callback candidates is not assumed before actual input. `CANDIDATES_CAPTURED_NOT_PROVEN` means only that target address excerpts are ready for review; `NO_EXECUTABLE_CANDIDATE_NOT_PROVEN` directs us to inspect relocation encoding and vtable fields, not enable PVR.

## Next interpretation step

Inspect resolved pointer targets and narrow callback bodies to find whether HIDL `QuickCameraBufInfo` metadata offsets and shared buffer handles populate PVR `QuickCameraClient +0x60/+0x10`, subsequently used by `PrepareStreamOn` and `DeQueueFrame`. Even if identical source bytes/offsets are statically shown, active physical SOF, fallback incidence, Pico↔Windows clock calibration and camera↔factory geometry remain separate gates.

Safety flags remain `observe_only=true`, `exact_time=false`, `live_lighthouse_correction_allowed=false`, `mapping_verified=false`, `pose_verified=false`, `frame_meta_bridge_verified=false`, `shared_buffer_identity_verified=false`, `physical_event_verified=false`.
