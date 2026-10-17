"""Offline locate ARM64 PC-relative references to two K0 timing literals.

Given the already SHA-pinned PVR service ELF, decode 16-byte tuples at
VA 0x73160 and 0x73170 and locate candidate ADRP+LDR/LDP/ADD sites.
Matches are static instruction cross-references, not evidence that a
given branch was executed or that values were active at capture time.
"""
import argparse
import hashlib
import json
import re
import subprocess
import struct
from pathlib import Path

from pico.tools.audit_k0_listener_table import SERVICE_HASH, read_elf_va
from pico.tools.audit_k0_q1_coefficients import correction_ns

PAGES = {0x73160: (0x73000, 0x160), 0x73170: (0x73000, 0x170)}
FUNC = re.compile(r"^\s*([0-9a-f]+) <(.+)>:\s*$")
INSTR = re.compile(r"^\s*([0-9a-f]+):\s+([a-z0-9.]+)\s*(.*?)\s*$")
ADRP = re.compile(r"^(x\d+),\s*0x([0-9a-f]+)\b", re.I)
BASE_MEM = re.compile(r"\[\s*(x\d+),\s*#0x([0-9a-f]+)\s*\]", re.I)
FIRST = re.compile(r"^\s*([wx]\d+)\b", re.I)
ADD_IMM = re.compile(r"^(x\d+),\s*(x\d+),\s*#0x([0-9a-f]+)\b", re.I)


def find_pc_relative_refs(text):
    """Conservative within-function ADRP/register-memory pairing.

    Reset on function boundaries and on writes to a previously tracked
    register. Classify all results as candidates because control flow
    across branch blocks and unseen aliases are not resolved.
    """
    refs = []
    owner = "UNNAMED"
    pages = {}
    instructions = []
    for line in text.splitlines():
        func = FUNC.match(line)
        if func:
            owner = func.group(2)
            pages.clear()
            instructions.clear()
            continue
        inst = INSTR.match(line)
        if not inst:
            continue
        addr, op, args = inst.groups()
        before = instructions[-6:]
        reg_write = FIRST.match(args)
        dest = reg_write.group(1) if reg_write else ""
        if dest.startswith("w"):
            dest = "x" + dest[1:]
        m = ADRP.match(args) if op == "adrp" else None
        if m:
            pages[m.group(1).lower()] = int(m.group(2), 16)
        else:
            # AArch64 x0..x18 are caller-saved. Do not carry a presumed
            # ADRP page through an arbitrary call and invent a dataflow.
            if op in ("bl", "blr"):
                for r in range(19):
                    pages.pop(f"x{r}", None)
            memory = BASE_MEM.search(args)
            if memory and op in ("ldr", "ldur", "ldp", "ldnp", "add"):
                base, offset = memory.group(1).lower(), int(memory.group(2), 16)
                page = pages.get(base)
                for va, (wanted_page, wanted_offset) in PAGES.items():
                    if page == wanted_page and offset == wanted_offset:
                        refs.append({
                            "at": "0x" + addr,
                            "owner": owner,
                            "literal_va": hex(va),
                            "instruction": line.strip(),
                            "context": [*before, line.strip()],
                            "classification": "PC_RELATIVE_ADRP_LOAD_CANDIDATE",
                        })
            add = ADD_IMM.match(args) if op == "add" else None
            if add:
                destination, base, immediate = add.groups()
                page = pages.get(base.lower())
                for va, (wanted_page, wanted_offset) in PAGES.items():
                    if page == wanted_page and int(immediate, 16) == wanted_offset:
                        refs.append({
                            "at": "0x" + addr, "owner": owner,
                            "literal_va": hex(va), "instruction": line.strip(),
                            "context": [*before, line.strip()],
                            "classification": "PC_RELATIVE_ADRP_ADD_ADDRESS_CANDIDATE",
                        })
            # Most instructions with a first register operand write it;
            # exclude stores/branches/comparisons/CBZ/TBZ.
            if dest and op not in (
                "str", "stur", "stp", "stnp", "stlr", "strb", "strh",
                "cmp", "cmn", "tst", "b", "bl", "blr", "br",
                "cbz", "cbnz", "tbz", "tbnz", "ret",
            ):
                pages.pop(dest, None)
        instructions.append(line.strip())
        if len(instructions) > 12:
            instructions.pop(0)
    return refs


def audit(elf, objdump):
    blob = Path(elf).read_bytes()
    if hashlib.sha256(blob).hexdigest() != SERVICE_HASH:
        raise ValueError("Refusing unverified PVR service ELF")
    literals = {}
    for va in PAGES:
        raw = read_elf_va(elf, va, 16)
        b, a = struct.unpack("<qq", raw)
        literals[hex(va)] = {
            "bytes_le": raw.hex(), "B": b, "A": a,
            "predicted_correction_ns_for_E4": correction_ns(a, b, 4),
        }
    cmd = [str(objdump), "-d", "--demangle", "--no-show-raw-insn", str(elf)]
    proc = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
    if proc.returncode:
        raise ValueError("LLVM objdump failed: " + proc.stderr[:600])
    hits = find_pc_relative_refs(proc.stdout)
    return {
        "status": "SOURCE_LITERAL_REFERENCES_CANDIDATES_ONLY",
        "literals": literals,
        "expected_observed_K0_delta_ns": 225997,
        "references": hits,
        "reference_count": len(hits),
        "notes": [
            "A literal with the same numeric delta is not proof it was loaded.",
            "ADRP register pairing is static and does not prove branch execution.",
            "Other PC-relative forms or aliases may be missed.",
            "Camera event semantics and LH pose clock alignment remain unverified.",
        ],
        "gates": {
            "active_profile_verified": False,
            "hardware_exposure_verified": False,
            "lighthouse_correction_allowed": False,
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--service", type=Path, required=True)
    parser.add_argument("--objdump", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.service, args.objdump)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    for va, vals in result["literals"].items():
        print(f"{va}: B={vals['B']} A={vals['A']} "
              f"predicted(E=4)={vals['predicted_correction_ns_for_E4']} ns")
    print("PC-relative candidate references:", result["reference_count"])
    for entry in result["references"][:30]:
        print(f"{entry['at']} {entry['owner'][:115]}  "
              f"literal={entry['literal_va']}")
        for context in entry["context"][-4:]:
            print("  " + context[:180])
    print("SOURCE CANDIDATES ONLY; active profile UNVERIFIED")
    print("Private report:", args.output)


if __name__ == "__main__":
    main()
