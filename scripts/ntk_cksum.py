#!/usr/bin/env python3
"""Novatek 16-bit checksum (MemCheck_CalcCheckSum16Bit style) used by FW98529A.bin.

sum over LE uint16 words w[i] of (w[i] + i), result = (-sum) & 0xFFFF, with the checksum
field zeroed during calculation. Verify mode checks the whole-file header (field at 0x24)
and every CKSM-wrapped partition (field at +0x0c), using ntk table at 0x80.

Usage: ntk_cksum.py FW.bin            -> verify and print
       ntk_cksum.py FW.bin --fix      -> recompute all fields in place
"""
import struct, sys
from array import array

def cks16(buf):
    if len(buf) % 2:
        buf = buf + b'\0'
    a = array('H')
    a.frombytes(buf)
    n = len(a)
    s = sum(a) + n * (n - 1) // 2
    return (-s) & 0xFFFF

def calc(blob, field):
    b = bytearray(blob)
    b[field:field + 2] = b'\0\0'
    return cks16(bytes(b))

def parts(d):
    out, pos = [], 0x80
    while pos + 12 <= len(d):
        off, size, pid = struct.unpack_from('<III', d, pos)
        if off == 0 or off + size > len(d) or off < pos:
            break
        out.append((pid, off, size))
        pos += 12
    return out

def main():
    path, fix = sys.argv[1], '--fix' in sys.argv
    d = bytearray(open(path, 'rb').read())
    ok = True
    for pid, off, size in parts(d):
        if d[off:off + 4] == b'CKSM':
            have = struct.unpack_from('<H', d, off + 0x0c)[0]
            want = calc(d[off:off + size], 0x0c)
            print(f'part {pid:2}: CKSM have {have:04x} calc {want:04x} {"OK" if have == want else "BAD"}')
            if fix:
                struct.pack_into('<H', d, off + 0x0c, want)
            ok &= have == want
    if fix:
        struct.pack_into('<I', d, 0x1c, len(d))
    have = struct.unpack_from('<H', d, 0x24)[0]
    want = calc(d, 0x24)
    print(f'file header: have {have:04x} calc {want:04x} {"OK" if have == want else "BAD"}')
    ok &= have == want
    if fix:
        struct.pack_into('<H', d, 0x24, want)
        open(path, 'wb').write(d)
        print('fixed')
    return 0 if ok or fix else 1

if __name__ == '__main__':
    sys.exit(main())
