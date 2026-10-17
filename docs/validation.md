# Validation results

Historical final project acceptance: **CONDITIONAL PASS**.

## Current Huffman replacement revision

For the replacement, the maintainer now reports Ubuntu native162/162 PASS,
ABI-checker9/9 PASS, Poky ARM compile/link PASS and static SDK ABI PASS.
These results were not rerun during the copyright review. Earlier current-source
Windows portable6/6 and offline subsets128/128 are supplemental, not native tests.

The maintainer supplied the replacement ARM SHA-256:

```text
8b631abafc478e21e23e755d2676f5061bde8292df16c5bc552c4e27e3e84f46
```

It differs from the historical M7.2 value below. The hash is a supplied build
result, not recomputed in this review: no corresponding ARM executable, abi.json
or raw SHA256SUMS is bundled here. No new hardware acceptance is inferred.
See [replacement](huffman-replacement.md) and [checklist](publication-checklist.md).

## Pre-replacement build and offline validation

The following Ubuntu results were supplied by the maintainer and were not
repeated during the final documentation review:

| Check | Result |
| --- | --- |
| Independent clean-copy native CMake build | PASS; no private parent dependency |
| CTest | 6/6 PASS |
| Service offline tests | 64/64 PASS |
| Watchdog offline tests | 21/21 PASS |
| Release offline tests | 27/27 PASS |
| Stability offline tests | 24/24 PASS |
| Dual-client offline tests | 20/20 PASS |
| Total native tests | 162/162 PASS: six CTests plus 156 Python tests |
| Specified Poky ARM cross-build | PASS |
| Static SDK ABI gate | PASS; not a new board runtime test |

The reported public ARM program hash exactly matches the frozen M7.2 binary:

```text
Release: m7.2-20261013-r1
SHA-256: ad657b4177ca3ad882e7427677bce915d8a26642f1086023c7fa16dfaabddb35
```

ARM checks cover ELF32 little-endian ARM EABI5 hard-float/VFP calling convention,
interpreter `/lib/ld-linux-armhf.so.3`, expected dynamic dependencies and symbol
requirements against the specified SDK, with GLIBC requirements <=2.23.
The exact hash match is a recorded build result, not a guarantee of reproducible
bytes with every compiler, directory or future build. Static ABI checks alone
do not establish every installed board library version.

## Historical hardware evidence

| Case | Observation | Boundary |
| --- | --- | --- |
| Normal camera mode | 1280x720 MJPEG, requested30fps, observed about29fps | UVC cadence gaps remain |
| Slow-client isolation | Normal sender drop0; slow sender drop1116; capture drop0, pool exhaustion0, ownership errors0; refs balanced, pool6/6 | Specific two-client run |
| M9.3 headless media | Concurrent decoding5.002s; after A exit B continued30.002s, frames146->1001 (+855) | Media independence PASS |
| M9.3 full automatic Gate | Paired final service/Watchdog evidence and numeric client exit evidence incomplete | INCONCLUSIVE |
| M9.1/M9.2 | Version check and30-minute playback passed | Full raw bundles not included |
| Earlier resource runs | 1800.010s/180 samples; separate reconnect run FD5/5/8, threads4/4/6 | Earlier temporary-path binaries |
| M7.4 operations | Reboot/autostart, diagnostic unlock, SIGKILL recovery, stop/start, three recoveries then lock, reset and playback | Hardware acceptance recorded; raw transcripts not distributed |

ffplay window-close coupling remains **OPEN**. A stable server identity and
headless media PASS do not prove the GUI symptom fixed. Missing paired identity
or client exit data are not reconstructed. No personal logs, machine Boot IDs,
deployment receipts or private images are included.

The frozen service references are:

```text
M7.4 init:
46ee08dee67e59ab3bbfbe6b8b83ef42bd7305ce7efc21e2d7d6d576f75116f2
M7.4 watchdog:
ff8092eda6865a2ba675c0bca48af600f1d8fd6a5b17dc4b67097e53b2c8e84d
```

## Final review checks and limits

The source allowlist, source mappings, relative links and syntax are checked
without board access. Nine ABI-checker offline regressions passed separately;
they are not included in the 162-test native count. Earlier Windows portable
checks are supplemental, not substitutes for Ubuntu/Poky evidence.

No new board test, deployment or full hardware Gate was performed for this
review. M8 did not demonstrate a significant end-to-end latency reduction.
See [limitations](limitations.md), [build](build.md) and
[publication checklist](publication-checklist.md). Licensing remains separate
from build and hardware validation.
