#!/usr/bin/env bash
set -euo pipefail
cd -- "${RC2_WORK:-$(dirname -- "$0")/../..}"
if [[ $(uname -m) != x86_64 ]]; then
    echo "The generated host instructions require x86-64 Linux." >&2
    exit 1
fi
src=vendor/FBNeo/src
flags=(-std=gnu17 -O1 -fPIC -fvisibility=hidden -ffunction-sections -fdata-sections -fno-strict-aliasing -DLSB_FIRST -DEMU_M68K -DBUILD_HEADLESS -DBUILD_X64_EXE -DNO_VIZ -DHAVE_UNISTD_H -Ibuild/aot -Ibuild/generated -I"$src/cpu/m68k" -I"$src/cpu" -I"$src/burn" -I"$src/burn/devices" -I"$src/burn/snd" -I"$src/burner/headless")
mkdir -p build/aot-obj
for f in build/aot/sites.S build/aot/m68kcpu.c; do
    name=${f##*/}
    cc "${flags[@]}" -c "$f" -o "build/aot-obj/${name%.*}.o"
done
build_file() {
    local source="$1"
    shift
    local name="${source##*/}"
    cc "$@" -c "$source" -o "build/aot-obj/${name%.c}.o"
}
export -f build_file
printf '%s\n' build/aot/kernel_*.c | xargs -P "${AOT_JOBS:-6}" -I '{}' bash -c 'build_file "$@"' _ '{}' "${flags[@]}"
