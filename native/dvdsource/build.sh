#!/usr/bin/env bash
# Builds the 32-bit DvdSource AviSynth plugin into tools/hcenc/ (next to HCenc_028.exe).
# Needs MSYS2 with mingw-w64-i686-gcc:  pacman -S mingw-w64-i686-gcc
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
root="$(cd "$here/../.." && pwd)"
gcc="${MSYS2_ROOT:-/c/msys64}/mingw32/bin/gcc.exe"
include="$root/tools/avisynthplus/arm64/include/avisynth"

PATH="$(dirname "$gcc"):$PATH" "$gcc" -m32 -shared -O2 -Wall -Wextra -Wno-cast-function-type -std=c11 \
    -I "$include" -static-libgcc \
    -o "$root/tools/hcenc/DvdSource.dll" "$here/dvdsource.c"

echo "built $root/tools/hcenc/DvdSource.dll"
