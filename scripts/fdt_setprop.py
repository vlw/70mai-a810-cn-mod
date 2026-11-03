#!/usr/bin/env python3
"""Set a 32-bit cell property in a flattened device tree in place (no relayout).

Usage: fdt_setprop.py IN.dtb OUT.dtb /node/path prop value
Fails unless the property exists with exactly 4 bytes.
"""
import struct, sys

FDT_BEGIN_NODE, FDT_END_NODE, FDT_PROP, FDT_NOP, FDT_END = 1, 2, 3, 4, 9

src, dst, path, prop, value = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4], int(sys.argv[5], 0)
d = bytearray(open(src, 'rb').read())
magic, total, off_struct, off_strings = struct.unpack_from('>IIII', d, 0)
assert magic == 0xD00DFEED and total == len(d), 'not a DTB or size mismatch'

want = [p for p in path.split('/') if p]
stack, pos, hit = [], off_struct, None
while True:
    tok, = struct.unpack_from('>I', d, pos); pos += 4
    if tok == FDT_BEGIN_NODE:
        end = d.index(b'\0', pos)
        name = d[pos:end].decode()
        stack.append(name.split('@')[0] if name else '')
        pos = (end + 4) & ~3
    elif tok == FDT_END_NODE:
        stack.pop()
    elif tok == FDT_PROP:
        ln, nameoff = struct.unpack_from('>II', d, pos)
        pname = d[off_strings + nameoff:d.index(b'\0', off_strings + nameoff)].decode()
        if [s for s in stack if s] == want and pname == prop:
            assert ln == 4, f'{prop} has {ln} bytes, expected 4'
            hit = pos + 8
        pos = (pos + 8 + ln + 3) & ~3
    elif tok == FDT_NOP:
        continue
    elif tok == FDT_END:
        break
    else:
        raise SystemExit(f'bad token {tok:#x} at {pos - 4:#x}')

assert hit is not None, f'{path}/{prop} not found'
old, = struct.unpack_from('>I', d, hit)
struct.pack_into('>I', d, hit, value)
open(dst, 'wb').write(d)
print(f'{path}/{prop}: {old:#x} -> {value:#x} at offset {hit:#x}')
