#!/bin/sh
# Build out/FW98529A.bin from the stock images in input/ with the features from config.env.
#   ./build.sh            build in Docker (macOS, Linux)
#   ./build.sh --native   build on this Linux machine as root (needs mtd-utils, python3, ubi_reader)
set -e
cd "$(dirname "$0")"
if [ "${1:-}" = --native ]; then
    exec bash scripts/build-inner.sh
fi
docker build -q -t a810-cn-mod-builder docker >/dev/null
exec docker run --rm -e HOST_UID="$(id -u)" -e HOST_GID="$(id -g)" -v "$PWD":/src a810-cn-mod-builder \
    bash scripts/build-inner.sh
