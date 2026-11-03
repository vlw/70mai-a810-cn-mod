#!/bin/sh
# Unpack any FW98529A.bin or 70mai OTA package for browsing.
#   ./unpack.sh FILE [OUTDIR]            in Docker (macOS, Linux); OUTDIR defaults to unpacked/<file name>
#   ./unpack.sh --native FILE [OUTDIR]   on this Linux machine (needs python3 and ubi_reader)
set -e
cd "$(dirname "$0")"
native=0
[ "${1:-}" = --native ] && { native=1; shift; }
[ -n "${1:-}" ] || { echo "usage: $0 [--native] FILE [OUTDIR]" >&2; exit 2; }
src=$1
out=${2:-unpacked/$(basename "$src")}
case "$src" in /*) ;; *) src=./$src ;; esac   # paths are relative to the repo inside Docker
if [ $native = 1 ]; then
    exec bash scripts/unpack-inner.sh "$src" "$out"
fi
docker build -q -t a810-cn-mod-builder docker >/dev/null
exec docker run --rm -e HOST_UID="$(id -u)" -e HOST_GID="$(id -g)" -v "$PWD":/src a810-cn-mod-builder \
    bash scripts/unpack-inner.sh "$src" "$out"
