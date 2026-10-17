#!/usr/bin/env bash
# Fresh, allowlisted ARM build only. No packaging, SSH, deployment or execution.
set -euo pipefail
export LC_ALL=C PYTHONDONTWRITEBYTECODE=1
[[ $OSTYPE == linux* ]] || { echo 'ERROR: Ubuntu/Linux required' >&2; exit 1; }
root=$(cd -- "$(dirname -- "$0")/.." && pwd)
sdk=/opt/fsl-imx-x11/4.1.15-2.1.0
setup=$sdk/environment-setup-cortexa7hf-neon-poky-linux-gnueabi
[[ -f $setup ]] || { echo "ERROR: Missing Poky SDK: $setup" >&2; exit 1; }
for tool in python3 cmake file sha256sum mktemp tee; do
    command -v "$tool" >/dev/null || { echo "ERROR: Missing $tool" >&2; exit 1; }
done
# Old Yocto environment scripts are not guaranteed nounset-safe.
set +u
source "$setup"
set -u
work=$(mktemp -d /tmp/lp2-public-poky.XXXXXX)
echo "Evidence retained: $work"
exec > >(tee "$work/gate.log") 2>&1
trap 'rc=$?; echo "Poky gate exit=$rc; evidence=$work"' EXIT
python3 "$root/tools/check_candidate.py" --copy-to "$work/repository"
cd "$work/repository"
python3 - "$sdk" "$work" <<'PY'
import json, os, pathlib, shlex, shutil, subprocess, sys
sdk = pathlib.Path(sys.argv[1]).resolve()
out = pathlib.Path(sys.argv[2])
cxx = shlex.split(os.environ.get('CXX', ''))
if not cxx:
    raise SystemExit('ERROR: SDK CXX unset')
compiler = pathlib.Path(shutil.which(cxx[0]) or cxx[0]).resolve()
sysroot = pathlib.Path(os.environ.get('OECORE_TARGET_SYSROOT', '/missing')).resolve()
if sdk not in compiler.parents or sdk not in sysroot.parents:
    raise SystemExit('ERROR: Compiler/sysroot outside the specified Poky SDK')
if compiler.name != 'arm-poky-linux-gnueabi-g++':
    raise SystemExit('ERROR: Not the expected Poky compiler')
def run(*args):
    return subprocess.check_output([str(compiler), *args], text=True, timeout=30).strip()
machine = run('-dumpmachine')
if machine != 'arm-poky-linux-gnueabi':
    raise SystemExit('ERROR: Wrong target triple: ' + machine)
if run('-dumpversion') != '5.3.0':
    raise SystemExit('ERROR: Expected the frozen SDK GCC 5.3.0; review SDK version')
readelf = compiler.parent / 'arm-poky-linux-gnueabi-readelf'
if not readelf.is_file():
    raise SystemExit('ERROR: SDK readelf missing')
record = dict(compiler=str(compiler), cxx=cxx, target=machine, version=run('--version'),
              sysroot=str(sysroot), readelf=str(readelf))
(out / 'sdk.json').write_text(json.dumps(record, indent=2) + '\n')
(out / 'readelf-path').write_text(str(readelf))
print(json.dumps(record, indent=2))
PY
cmake -S . -B "$work/build" \
  -DCMAKE_TOOLCHAIN_FILE="$PWD/cmake/toolchains/imx6ull-poky.cmake" \
  -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTING=OFF -DLP2_BUILD_TOOLS=OFF
cmake --build "$work/build" --target lp2_m5_rtsp_server -- -j2
python3 - "$work" <<'PY'
import json, pathlib, re, sys
work = pathlib.Path(sys.argv[1])
sdk = json.loads((work / 'sdk.json').read_text())
cache = (work / 'build/CMakeCache.txt').read_text()
match = re.search(r'^CMAKE_CXX_COMPILER:(?:FILEPATH|STRING)=(.+)$', cache, re.M)
if not match or pathlib.Path(match[1]).resolve() != pathlib.Path(sdk['compiler']):
    raise SystemExit('ERROR: CMake compiler does not match audited SDK')
PY
binary=$work/build/m5_rtsp_server/lp2_m5_rtsp_server
file "$binary" | tee "$work/file.txt"
sha256sum "$binary" | tee "$work/SHA256SUMS"
python3 tools/check_poky_abi.py --binary "$binary" \
  --sysroot "$OECORE_TARGET_SYSROOT" --readelf "$(cat "$work/readelf-path")" \
  --output "$work/abi.json"
echo 'PASS: fresh Poky compile/link and static SDK ABI checks only. Board Gate NOT RUN.'
