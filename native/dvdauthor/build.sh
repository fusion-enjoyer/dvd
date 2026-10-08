#!/usr/bin/env bash
# Builds dvdauthor.exe and spumux.exe (64-bit, MSYS2 UCRT64) into tools/dvdauthor/ with their DLLs.
#
# There is no official Windows build. Upstream does not build on MinGW as is, so we:
#   - patch configure.ac for autoconf 2.73 (configure-ac.patch)
#   - force-include shim/win32compat.h and add shim/ to the include path at make time
#     (mkdir/fsync/bzero, netinet/in.h, langinfo.h)
#   - build only dvdauthor and spumux (mpeg2desc needs POSIX select on files)
#
# Needs MSYS2 with: base-devel autotools gettext-devel mingw-w64-ucrt-x86_64-{gcc,pkgconf,
#   libxml2,libpng,freetype,fribidi,fontconfig,libdvdread}
# Usage: native/dvdauthor/build.sh [work-dir]
set -euo pipefail

COMMIT=fe8fe3578f95f34889e7ed17591d02dceb4f42ed   # ldo/dvdauthor master, 0.7.2+
here="$(cd "$(dirname "$0")" && pwd)"
root="$(cd "$here/../.." && pwd)"
work="${1:-$root/build/dvdauthor-src}"
msys="${MSYS2_ROOT:-/c/msys64}"

if [ ! -d "$work/.git" ]; then
    git clone -q https://github.com/ldo/dvdauthor.git "$work"
fi
git -C "$work" checkout -q "$COMMIT"
git -C "$work" checkout -q -- configure.ac
git -C "$work" apply "$here/configure-ac.patch"

to_msys() { "$msys/usr/bin/cygpath.exe" -u "$(cygpath -w "$1" 2>/dev/null || echo "$1")"; }
src="$(to_msys "$work")"
shim="$(to_msys "$here/shim")"
out="$(to_msys "$root/tools/dvdauthor")"

MSYSTEM=UCRT64 CHERE_INVOKING=1 "$msys/usr/bin/bash.exe" -lc "
set -e
cd '$src'
mkdir -p autotools m4
autoreconf -fi >/dev/null
./configure --prefix=/opt/dvdauthor </dev/null >/dev/null
make -C src -j\$(nproc) CPPFLAGS='-I$shim -include $shim/win32compat.h' dvdauthor.exe spumux.exe </dev/null >/dev/null
mkdir -p '$out'
for exe in dvdauthor.exe spumux.exe; do
    f=src/\$exe; [ -f src/.libs/\$exe ] && f=src/.libs/\$exe
    cp \"\$f\" '$out/'
    ldd \"\$f\" | awk '/\\/ucrt64\\//{print \$3}' | xargs -r -I{} cp -u {} '$out/'
done
"
echo "built into $root/tools/dvdauthor"
