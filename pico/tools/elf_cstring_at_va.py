"""Read a single NUL-terminated ELF64 AArch64 string at a virtual address.

Pure standard library, bounded to a caller-controlled maximum. Only reads
an offline firmware file; does not execute ELF code or access the headset.
"""
import argparse
import struct
from pathlib import Path


def elf_cstring(path, va, max_bytes=256):
    if not (1 <= max_bytes <= 4096):
        raise ValueError("max_bytes must be 1..4096")
    blob = Path(path).read_bytes()
    if (len(blob) < 64 or blob[:4] != b"\x7fELF" or blob[4] != 2 or blob[5] != 1):
        raise ValueError("Expected little-endian ELF64")
    if struct.unpack_from("<H", blob, 18)[0] != 183:
        raise ValueError("Expected AArch64 ELF (EM_AARCH64=183)")
    phoff = struct.unpack_from("<Q", blob, 32)[0]
    phentsize = struct.unpack_from("<H", blob, 54)[0]
    phnum = struct.unpack_from("<H", blob, 56)[0]
    if phentsize < 56 or phnum < 1 or phnum > 4096 or phoff + phentsize * phnum > len(blob):
        raise ValueError("Invalid ELF program-header table")
    for i in range(phnum):
        off = phoff + i * phentsize
        ptype, flags, fileoff, pva, ppa, filesz, memsz, align = struct.unpack_from("<IIQQQQQQ", blob, off)
        if ptype != 1 or not (pva <= va < pva + filesz):
            continue
        offset = fileoff + (va - pva)
        available = min(max_bytes, filesz - (va - pva))
        if offset < 0 or offset + available > len(blob):
            raise ValueError("Malformed PT_LOAD file mapping")
        data = blob[offset:offset + available]
        terminator = data.find(b"\x00")
        if terminator < 0:
            raise ValueError("No NUL within bounded PT_LOAD string region")
        return data[:terminator]
    raise ValueError("Requested VA not backed by PT_LOAD file data")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--elf", type=Path, required=True)
    parser.add_argument("--va", type=lambda s: int(s, 0), required=True)
    parser.add_argument("--max-bytes", type=int, default=256)
    args = parser.parse_args()
    data = elf_cstring(args.elf, args.va, args.max_bytes)
    print(f"ELF virtual address: {hex(args.va)}")
    print(f"Literal bytes: {data!r}")
    print("Classification: format string/constant only; no timestamp-domain claim.")


if __name__ == "__main__":
    main()
