#!/usr/bin/env python3
"""Split a Novatek FW98529A.bin into partitions using the header table at 0x80.

Table: (offset, size, id) little-endian uint32 triplets until offset==0 or past EOF.
Usage: ntk_split.py FW.bin outdir
"""
import os, struct, sys, zlib

fw, out = sys.argv[1], sys.argv[2]
data = open(fw, 'rb').read()
os.makedirs(out, exist_ok=True)

print(f"file size {len(data):#x}  header: {data[:0x30].hex()}")
pos, parts = 0x80, []
while pos + 12 <= len(data):
    off, size, pid = struct.unpack_from('<III', data, pos)
    if off == 0 or off + size > len(data) or off < pos:
        break
    parts.append((pid, off, size))
    pos += 12

for pid, off, size in parts:
    blob = data[off:off + size]
    magic = blob[:8].hex()
    name = f"part{pid:02d}_{off:08x}.bin"
    open(os.path.join(out, name), 'wb').write(blob)
    print(f"id={pid:2d} off={off:#010x} size={size:#010x} magic={magic} crc32={zlib.crc32(blob):08x} -> {name}")

end = max(o + s for _, o, s in parts)
if end < len(data):
    print(f"trailing {len(data) - end} bytes after last partition: {data[end:end+64].hex()}")
