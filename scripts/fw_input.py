#!/usr/bin/env python3
"""Find the stock firmware images in a directory and write them as plain FW98529A.bin files.

Accepts the card image (FW98529A.bin), the CN OTA package from the 70迈 app cache (a 0xb4-byte
OTA header + FW98529A.bin, despite the .zip name) and the WW OTA zip. Images are recognised by
sha256 only, so any file name works.

Usage: fw_input.py INPUT_DIR OUT_DIR   -> OUT_DIR/cn.bin, OUT_DIR/ww.bin (when present)
"""
import hashlib, os, struct, sys, zipfile, zlib

KNOWN = {
    'abbfec494ad6e6dcfd2368cd8655f11902b658f1a243cea568e6e01fad2002c9': ('cn', 'A810 PRO CN 1.6.49'),
    'd19499741d458d2043132d73e0b1b4a601c9ff1039b6ecc255cbb17f42577273': ('ww', 'A810S WW 1.5.40ww'),
}

def candidates(path):
    """Yield FW98529A.bin payloads found in a file."""
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as z:
            for n in z.namelist():
                if os.path.basename(n) == 'FW98529A.bin':
                    yield z.read(n)
        return
    d = open(path, 'rb').read()
    if d[:4] == bytes.fromhex('55aaaa55'):                 # 70mai OTA header
        size, = struct.unpack_from('<I', d, 0x5c)
        crc, = struct.unpack_from('<I', d, 0x38)
        payload = d[0xb4:0xb4 + size]
        assert len(payload) == size and zlib.crc32(payload) == crc, f'{path}: OTA payload CRC mismatch'
        yield payload
    else:
        yield d

def main():
    src, out = sys.argv[1], sys.argv[2]
    os.makedirs(out, exist_ok=True)
    found = {}
    for name in sorted(os.listdir(src)):
        path = os.path.join(src, name)
        if not os.path.isfile(path) or name.startswith('.'):
            continue
        for fw in candidates(path):
            h = hashlib.sha256(fw).hexdigest()
            if h in KNOWN:
                key, label = KNOWN[h]
                open(os.path.join(out, key + '.bin'), 'wb').write(fw)
                found[key] = label
                print(f'{name}: {label}')
    for key, label in {v[0]: v[1] for v in KNOWN.values()}.items():
        if key not in found:
            print(f'not found: {label}')
    sys.exit(0 if 'cn' in found else 1)

if __name__ == '__main__':
    main()
