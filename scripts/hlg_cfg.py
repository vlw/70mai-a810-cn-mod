#!/usr/bin/env python3
"""Make an HLG variant of a Novatek HDR ISP config (imx678_hdr.cfg).

In SHDR mode the final [GAMMA_0/1] LUTs are identity and the whole SDR rendering lives in
[GAMMA] tone_lut_shdr_set0..4_val (65 points, 12-bit, chosen by scene LV) plus [GAMMA_EXT]
gamma_set2..4 (extra contrast at high LV). The tone input is NOT scene-linear (the SHDR merge is
already compressed: stock maps 1/8 of the input to ~0.32), so the HLG OETF on top of it
double-gammas: shadows and noise get lifted and the picture turns too bright.
Instead, like OpenIPC's isp.hdr=hlg: keep the stock rendering for shadows/mids, put diffuse white
at the HLG reference level (0.75, BT.2408) and give the stock shoulder (highlights above it) the
top quarter of the signal. AE stays stock. [GAMMA_EXT] sets become identity.

Usage: hlg_cfg.py IN.cfg OUT.cfg
"""
import math, re, sys

KEEP = 0.5        # stock output kept as is below this: shadows/mids, same noise as stock HDR
WHITE_S = 0.88    # stock output level treated as diffuse white
WHITE_HLG = 0.75  # HLG reference white

def hlg_lut(stock):
    s = [v / 4095 for v in stock]
    xs = [i / 64 for i in range(65)]
    i = next(i for i, v in enumerate(s) if v >= WHITE_S)
    x_w = xs[i - 1] + (WHITE_S - s[i - 1]) / (s[i] - s[i - 1]) * (xs[i] - xs[i - 1])
    d, w = WHITE_S - KEEP, WHITE_HLG - KEEP
    out = []
    for x, v in zip(xs, s):
        if v <= KEEP:
            o = v
        elif x <= x_w:   # KEEP..WHITE_S -> KEEP..WHITE_HLG, slope 1 at KEEP (quadratic, monotone)
            t = (v - KEEP) / d
            o = KEEP + d * t + (w - d) * t * t
        else:            # highlights above diffuse white: log spread over the top quarter
            o = WHITE_HLG + (1 - WHITE_HLG) * math.log(x / x_w) / math.log(1 / x_w)
        out.append(round(4095 * min(max(o, 0.0), 1.0)))
    assert all(b >= a for a, b in zip(out, out[1:])), out
    return out

def main():
    src, dst = sys.argv[1], sys.argv[2]
    text = open(src).read()
    def sub(m):
        lut = hlg_lut(list(map(int, m.group(2).split(','))))
        print(m.group(1), [round(lut[k] / 4095, 2) for k in (4, 8, 16, 32, 40, 48, 56, 64)])
        return m.group(1) + ','.join(map(str, lut))
    text, n = re.subn(r'^(tone_lut_shdr_set\d_val=)(.*)$', sub, text, flags=re.M)
    assert n == 5, f'expected 5 tone sets, got {n}'
    ident = re.search(r'^gamma_set0_lut=(.*)$', text, re.M).group(1)
    assert ident.split(',')[:4] == ['0', '8', '16', '24'], 'gamma_set0 is not identity'
    text, m = re.subn(r'^(gamma_set[1-4]_lut=).*$', lambda mm: mm.group(1) + ident, text, flags=re.M)
    assert m == 4, f'expected 4 ext sets, got {m}'
    open(dst, 'w', newline='').write(text)

if __name__ == '__main__':
    main()
