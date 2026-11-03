#!/usr/bin/env python3
"""Replace CKSM-wrapped partitions in a Novatek FW98529A.bin and fix table/sizes/checksums.

Partitions follow table order; each one starts at the previous start + size rounded up to
0x40, zero-filled, no padding after the last (as in stock CN/WW images). The original
0x40-byte CKSM header of each replaced partition is reused with its size field (0x14)
updated; checksums are recomputed by ntk_cksum.

Usage: ntk_repack.py IN.bin OUT.bin ID=payload.bin [ID=payload.bin ...]
"""
import struct, sys
sys.path.insert(0, __import__('os').path.dirname(__file__))
from ntk_cksum import parts, calc

src, dst, repl = sys.argv[1], sys.argv[2], dict(a.split('=') for a in sys.argv[3:])
d = open(src, 'rb').read()
table = parts(d)
assert table and table[0][1] == 0xd4, 'unexpected layout'
out = bytearray(d[:table[0][1]])
for n, (pid, off, size) in enumerate(table):
    blob = d[off:off + size]
    if str(pid) in repl and blob[:4] != b'CKSM':
        # raw partition (e.g. DTB): only same-size in-place replacements are allowed
        raw = open(repl[str(pid)], 'rb').read()
        assert len(raw) == len(blob), f'part {pid}: raw replacement must keep size {len(blob)}'
        blob = raw
    elif str(pid) in repl:
        payload = open(repl[str(pid)], 'rb').read()
        hdr = bytearray(blob[:0x40])
        struct.pack_into('<I', hdr, 0x14, len(payload))
        blob = bytes(hdr) + payload
        struct.pack_into('<H', blob := bytearray(blob), 0x0c, calc(blob, 0x0c))
    if n:  # next start = previous start + previous size rounded up to 0x40 (relative, not absolute)
        out += bytes(prev_start + ((prev_size + 0x3f) & ~0x3f) - len(out))
    prev_start, prev_size = len(out), len(blob)
    struct.pack_into('<III', out, 0x80 + 12 * n, len(out), len(blob), pid)
    out += blob
struct.pack_into('<I', out, 0x1c, len(out))
struct.pack_into('<H', out, 0x24, calc(out, 0x24))
open(dst, 'wb').write(out)
print('written', dst, len(out))
