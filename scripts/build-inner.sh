#!/bin/bash
# Build FW98529A.bin from the stock CN 1.6.49 image with the features from config.env.
# Runs as root in the builder container (or natively on Linux with mtd-utils and ubi_reader):
# unpacking keeps owners/modes/device nodes, so the work tree stays in /tmp, only out/ is shared.
set -euo pipefail
cd "$(dirname "$0")/.."
. ./config.default.env
[ -f config.env ] && . ./config.env
W=${WORK:-/tmp/a810-build}
OUT=out
on() { [ "${!1:-0}" = 1 ]; }

rm -rf "$W" && mkdir -p "$W" "$OUT"
echo "== input"
python3 scripts/fw_input.py input "$W/in"
NEED_WW=0
{ on LANGUAGE_MENU || on VOICE_RU_EN; } && NEED_WW=1
if [ $NEED_WW = 1 ] && [ ! -f "$W/in/ww.bin" ]; then
    echo "LANGUAGE_MENU / VOICE_RU_EN need the WW 1.5.40ww image in input/ (see README)" >&2
    exit 1
fi

echo "== unpack"
unpack() {  # unpack FW DIR: partitions + rootfs/app trees (owners kept)
    python3 scripts/ntk_split.py "$1" "$2/parts" >/dev/null
    tail -c +65 "$2"/parts/part09_*.bin > "$2/p09.ubi"   # CKSM header is 0x40 bytes
    tail -c +65 "$2"/parts/part10_*.bin > "$2/p10.ubi"
    ubireader_extract_files -k -o "$2/rootfs" "$2/p09.ubi" >/dev/null
    ubireader_extract_files -k -o "$2/app" "$2/p10.ubi" >/dev/null
}
unpack "$W/in/cn.bin" "$W/cn"
ROOT=$(ls -d "$W"/cn/rootfs/*/rootfs)
APP=$(ls -d "$W"/cn/app/*/app)
if [ $NEED_WW = 1 ]; then
    python3 scripts/ntk_split.py "$W/in/ww.bin" "$W/ww/parts" >/dev/null
    tail -c +65 "$W"/ww/parts/part10_*.bin > "$W/ww/p10.ubi"
    ubireader_extract_files -k -o "$W/ww/app" "$W/ww/p10.ubi" >/dev/null
    WWAPP=$(ls -d "$W"/ww/app/*/app)
fi
manifest() { (cd "$1" && find . -printf '%p\t%y\t%m\t%U\t%G\t%s\t%l\n' | LC_ALL=C sort); }
manifest "$ROOT" > "$W/rootfs_orig.manifest"
manifest "$APP" > "$W/app_orig.manifest"

echo "== patch"
FEATURES=""
for f in LANGUAGE_MENU TIMEZONE_MENU DEFAULT_ENGLISH GPS_HOME HLG RU_LABELS; do on $f && FEATURES="$FEATURES $f"; done
python3 scripts/patch_main_app.py "$ROOT/usr/bin/main_app" "$W/main_app" $FEATURES "DEFAULT_TZ=${DEFAULT_TZ:-}"
cat "$W/main_app" > "$ROOT/usr/bin/main_app"          # content only: inode metadata stays stock

copy_like() {  # copy_like SRC DST REF: copy a WW folder with owners of a stock reference folder
    cp -a "$1" "$2" && chown -R --reference="$3" "$2"
}
if on LANGUAGE_MENU; then   # non-Chinese UI switches voice control to English: ship its Cerence model
    copy_like "$WWAPP/voice/res/cerence/enu" "$APP/voice/res/cerence/enu" "$APP/voice/res/cerence/mnc"
fi
if on VOICE_RU_EN; then
    for l in russian english; do
        copy_like "$WWAPP/voice/res/audio/$l" "$APP/voice/res/audio/$l" "$APP/voice/res/audio/chinese"
    done
fi
if on HLG; then
    python3 scripts/hlg_cfg.py "$APP/isp/imx678_hdr.cfg" "$W/imx678_hdr.cfg"
    cat "$W/imx678_hdr.cfg" > "$APP/isp/imx678_hdr.cfg"
fi
for f in TELNET GPS_WARM; do
    on $f || continue
    d=files/$(echo $f | tr 'A-Z_' 'a-z-')
    (cd "$d" && find . -type f) | while read -r p; do
        install -m 0755 -o 0 -g 0 "$d/$p" "$ROOT/$p"
    done
done
REPLACE=""
if on UPDATE_SCREEN_EN; then   # U-Boot picks the update screen language from /logo/language (CN 0, WW 1)
    for p in 1 2; do
        python3 scripts/fdt_setprop.py "$W"/cn/parts/part0${p}_*.bin "$W/dtb$p.bin" /logo language 1 >/dev/null
        REPLACE="$REPLACE $p=$W/dtb$p.bin"
    done
fi

echo "== UBI"
mkfs.ubifs -m 2048 -e 126976 -c 524 -x lzo -f 8 -k r5 -p 1 -l 5 -r "$ROOT" -o "$W/rootfs.ubifs"
mkfs.ubifs -m 2048 -e 126976 -c 684 -x lzo -f 8 -k r5 -p 1 -l 5 -r "$APP" -o "$W/app.ubifs"
ubi_ini() { printf '[%s]\nmode=ubi\nimage=%s\nvol_type=dynamic\nvol_id=0\nvol_name=%s\nvol_alignment=1\nvol_size=%s\n' "$1" "$2" "$1" "$3"; }
ubi_ini rootfs "$W/rootfs.ubifs" 66535424 > "$W/rootfs.ini"
ubi_ini app "$W/app.ubifs" 86851584 > "$W/app.ini"
ubinize -p 131072 -m 2048 -O 2048 -s 2048 -x 1 -Q 1738136151 -o "$W/p09_new.ubi" "$W/rootfs.ini"
ubinize -p 131072 -m 2048 -O 2048 -s 2048 -x 1 -Q 2121631321 -o "$W/p10_new.ubi" "$W/app.ini"

echo "== verify UBI"
ubireader_extract_files -k -o "$W/chk_root" "$W/p09_new.ubi" >/dev/null
ubireader_extract_files -k -o "$W/chk_app" "$W/p10_new.ubi" >/dev/null
diff -r --no-dereference "$ROOT" "$(ls -d "$W"/chk_root/*/rootfs)" >/dev/null || { echo "rootfs image differs from tree" >&2; exit 1; }
diff -r --no-dereference "$APP" "$(ls -d "$W"/chk_app/*/app)" >/dev/null || { echo "app image differs from tree" >&2; exit 1; }
echo "rootfs, app: image == patched tree"
manifest "$(ls -d "$W"/chk_root/*/rootfs)" | diff "$W/rootfs_orig.manifest" - | grep '^[<>]' | sed 's/^/rootfs vs stock: /' || true
manifest "$(ls -d "$W"/chk_app/*/app)" | diff "$W/app_orig.manifest" - | grep '^[<>]' | grep -v '/voice/res/' \
    | sed 's/^/app vs stock: /' || true

echo "== FW98529A.bin"
python3 scripts/ntk_repack.py "$W/in/cn.bin" "$OUT/FW98529A.bin" $REPLACE 9="$W/p09_new.ubi" 10="$W/p10_new.ubi"
python3 scripts/ntk_cksum.py "$OUT/FW98529A.bin"
{
    echo "base: 70mai A810 PRO (DR2830) CN 1.6.49"
    echo "main_app:$FEATURES DEFAULT_TZ=${DEFAULT_TZ:-} md5 $(md5sum < "$W/main_app" | cut -d' ' -f1)"
    for f in TELNET GPS_WARM VOICE_RU_EN UPDATE_SCREEN_EN; do echo "$f=${!f:-0}"; done
    echo "sha256 $(sha256sum < "$OUT/FW98529A.bin" | cut -d' ' -f1)"
} | tee "$OUT/build-info.txt"
[ -n "${HOST_UID:-}" ] && chown "$HOST_UID:${HOST_GID:-$HOST_UID}" "$OUT" "$OUT"/*
rm -rf "$W"
