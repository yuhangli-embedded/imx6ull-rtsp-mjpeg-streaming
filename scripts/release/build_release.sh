#!/bin/bash
# Ubuntu only. New directory for each attempt; no cache reuse or deletion.
set -euo pipefail
root=$(cd -- "$(dirname -- "$0")/../.." && pwd -P)
version=${1:?Usage: bash scripts/release/build_release.sh VERSION}
[[ $version =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$ ]] || { echo 'Invalid version' >&2; exit 1; }
sdk=/opt/fsl-imx-x11/4.1.15-2.1.0/environment-setup-cortexa7hf-neon-poky-linux-gnueabi
[[ -r $sdk ]] || { echo "ERROR: Poky SDK missing: $sdk; no substitute compiler allowed" >&2; exit 1; }
# Old SDK environment scripts can reference unset shell variables.
set +u
source "$sdk"
set -u
[[ ${CXX:-} == *poky-linux-gnueabi-g++* && -d ${OECORE_TARGET_SYSROOT:-} ]] || { echo 'Wrong SDK environment' >&2; exit 1; }
for tool in cmake python3 file; do command -v "$tool" >/dev/null || exit 1; done
base="$root/build/releases/$version"
for path in "$root/build" "$root/build/releases" "$root/releases"; do
    [[ ! -L $path ]] || { echo "Refusing symlinked output parent: $path" >&2; exit 1; }
done
[[ ! -e $base && ! -L $base && ! -e $root/releases/$version ]] || { echo 'Refusing existing build/package; choose a new version' >&2; exit 1; }
mkdir -p "$base/build"
python3 -B "$root/scripts/release/release_package.py" snapshot > "$base/source-sha256.json"
# No eval: SDK CXX is a compiler plus its documented flags.
read -r -a cxx_parts <<< "$CXX"
compiler_path=$(command -v "${cxx_parts[0]}")
readelf_path=${compiler_path%-g++}-readelf
[[ -x $readelf_path ]] || { echo 'Poky readelf missing' >&2; exit 1; }
{
    echo 'origin=fresh-poky-release-build'
    printf 'sdk=%s\nsysroot=%s\nCXX=%s\nCXXFLAGS=%s\nLDFLAGS=%s\n' "$sdk" "$OECORE_TARGET_SYSROOT" "$CXX" "${CXXFLAGS:-}" "${LDFLAGS:-}"
    "${cxx_parts[@]}" --version
    cmake --version
    sha256sum "$sdk" "$root/cmake/toolchains/imx6ull-poky.cmake"
    printf 'configure=cmake -G "Unix Makefiles" -S m5_rtsp_server -B build/releases/%s/build -DCMAKE_BUILD_TYPE=Release -DCMAKE_TOOLCHAIN_FILE=cmake/toolchains/imx6ull-poky.cmake\n' "$version"
    echo 'build=cmake --build <fresh-build> --target lp2_m5_rtsp_server -- -j2'
} > "$base/build-info.txt"
cmake -G "Unix Makefiles" -S "$root/m5_rtsp_server" -B "$base/build" \
    -DCMAKE_BUILD_TYPE=Release -DCMAKE_TOOLCHAIN_FILE="$root/cmake/toolchains/imx6ull-poky.cmake"
cmake --build "$base/build" --target lp2_m5_rtsp_server -- -j2
cat "$base/build/CMakeCache.txt" >> "$base/build-info.txt"
cat "$base/build/CMakeFiles/lp2_m5_rtsp_server.dir/flags.make" \
    "$base/build/CMakeFiles/lp2_m5_rtsp_server.dir/link.txt" >> "$base/build-info.txt"
"$readelf_path" -W -h -l -d -V "$base/build/lp2_m5_rtsp_server" >> "$base/build-info.txt"
file "$base/build/lp2_m5_rtsp_server" | tee "$base/file.txt"
python3 -B "$root/scripts/release/release_package.py" create "$version"
# Same source, SDK, flags and paths reproduce the recipe; bit reproducibility
# must be established with an independent repeat build, not assumed here.
