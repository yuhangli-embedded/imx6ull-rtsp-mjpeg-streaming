# Build

No dependency on a private parent directory, prebuilt ARM binary, private photo,
SDK archive or generated CMake cache is allowed. The selected module layout is
deliberate; there was no original top-level CMake, so this candidate supplies one.

## Ubuntu native

Use a shell **without** an active Poky SDK. Prerequisites: g++, CMake >=3.13,
Linux userspace/V4L2 headers, POSIX threads, Python >=3.8, a POSIX shell and GNU
tools. FFmpeg is required only for the independent JPEG decode gate, not the
board pipeline. GNU mv with -T is required by service/release tests.

```bash
cmake -S . -B build/native -DCMAKE_CXX_COMPILER=/usr/bin/g++ \
  -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTING=ON -DLP2_BUILD_TOOLS=ON
cmake --build build/native -- -j2
ctest --test-dir build/native --output-on-failure
```

Targets: `lp2_m5_rtsp_server`, optional `lp2_m4_rtp_receiver`, `lp2_jpeg_rtp_check`
and six offline test executables. `LP2_BUILD_TOOLS=OFF` omits checker/receiver and
their two tests; it is not the full six-test gate. Do not run the board server on
a normal Ubuntu machine merely to validate a build: it needs a real camera and
conflict-free hardware/ports. Native CTests do not open a camera or board socket.

The fixture is already included. No generation step or Windows component is
needed on Ubuntu; see [fixture provenance](../tests/fixtures/README.md).

## Poky cross-compilation

The maintainer reports PASS for the new Huffman revision's native162 tests,
ABI checker9 tests and specified SDK build/static ABI. The supplied ARM SHA-256 is
`8b631abafc478e21e23e755d2676f5061bde8292df16c5bc552c4e27e3e84f46`.
This is not the pre-replacement M7.2 hash.
Use `bash tools/validate_huffman_revision.sh` to reproduce native and ARM checks;
no rebuild is required as part of the notice review.
See [validation](validation.md).

G3.2 provides a single non-deploying verification entry point. Run on Ubuntu
from this repository (no private parent required):

```bash
bash tools/validate_poky.sh
```

It sources the exact SDK below, rejects compilers/sysroots outside it, records
the compiler version/triple, exports a new allowlisted copy under
`/tmp/lp2-public-poky.XXXXXX`, and builds only the server in a fresh CMake cache.
The directory and logs are retained, not automatically deleted or uploaded.
No ARM executable is run. Neither SSH nor service installation is performed.
It does not repeat G3.1 native tests. See [G3.2 review](g3-2-review.md).

The SDK must be separately available under its documented target-compatible path:

```bash
source /opt/fsl-imx-x11/4.1.15-2.1.0/environment-setup-cortexa7hf-neon-poky-linux-gnueabi
cmake -S . -B build/poky-review \
  -DCMAKE_TOOLCHAIN_FILE="$PWD/cmake/toolchains/imx6ull-poky.cmake" \
  -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTING=OFF -DLP2_BUILD_TOOLS=OFF
cmake --build build/poky-review --target lp2_m5_rtsp_server -- -j2
file build/poky-review/m5_rtsp_server/lp2_m5_rtsp_server
```

Expected ABI: ARM ELF32 EABI5 hard-float, target glibc 2.23, interpreter
`/lib/ld-linux-armhf.so.3`. Use SDK readelf to inspect interpreter, NEEDED and
symbol versions; an ARM architecture label alone does not prove compatibility.
Do not execute ARM CTests on the host. No generic Ubuntu ARM compiler substitution.

The automated checker reuses the public release ELF parser. It verifies ARM32
little-endian EABI5 hard-float, VFP register calling convention, interpreter,
allowed DT_NEEDED entries, absence of RPATH/RUNPATH and each requested symbol
version against its corresponding SDK library, not a pooled namespace. Numeric
GLIBC requirements above 2.23 and unrecognized GLIBC namespaces are rejected.
SDK interpreter/dependency ELF architecture is checked. Target-absolute SDK
symlinks are interpreted inside the target sysroot, not Ubuntu's `/lib`.

Evidence: `gate.log`, `sdk.json`, `file.txt`, `SHA256SUMS`, `abi.json`, five
`readelf-*.txt` files, CMake cache and the new binary. A failed step stops the gate.
The report is **STATIC_SDK_ABI_ONLY**: matching SDK symbols is not proof that
installed board libraries match the SDK or that a new binary passed runtime
validation. Do not expect its SHA to equal frozen M7.2; never replace the frozen
Release as part of this check.

The guarded package builder is a separate entry point:

```bash
bash scripts/release/build_release.sh public-review-r1
```

It sources the SDK itself, builds the module target in a fresh version directory,
audits metadata and creates a new package. Existing versions are refused. A fresh
package is NOT automatically activated and starts with hardware_gate=PENDING.
The old baseline hash is retained as historical comparison, not as an expected
hash for new public builds. This source export is not claimed bit-identical to
the frozen hardware-tested binary. All commands here are documentation, not G2 deployment.
