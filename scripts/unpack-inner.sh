#!/bin/bash
# Unpack a FW98529A.bin (or a 70mai OTA package) for browsing: partitions, rootfs and app trees.
# Usage: unpack-inner.sh FILE OUTDIR
set -euo pipefail
cd "$(dirname "$0")/.."
src=$1 out=$2
rm -rf "$out" && mkdir -p "$out"
python3 - "$src" "$out/FW98529A.bin" <<'PY'
import sys; sys.path.insert(0, 'scripts')
from fw_input import candidates
open(sys.argv[2], 'wb').write(next(candidates(sys.argv[1])))
PY
python3 scripts/ntk_split.py "$out/FW98529A.bin" "$out/parts"
python3 scripts/ntk_cksum.py "$out/FW98529A.bin"
for p in 09 10; do
    tail -c +65 "$out"/parts/part${p}_*.bin > "$out/p$p.ubi"
    ubireader_extract_files -o "$out/fs$p" "$out/p$p.ubi" >/dev/null   # no -k: owners/devices skipped
done
rm "$out/FW98529A.bin" "$out"/p*.ubi
echo "unpacked to $out: parts/ (raw partitions), fs09/*/rootfs, fs10/*/app"
[ -n "${HOST_UID:-}" ] && chown -R "$HOST_UID:${HOST_GID:-$HOST_UID}" "$out"
true
