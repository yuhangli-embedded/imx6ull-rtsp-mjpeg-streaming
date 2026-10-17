#!/bin/bash
# Offline only: no SSH, camera access, install, service, network or SDK calls.
set -euo pipefail
root=$(cd -- "$(dirname -- "$0")/.." && pwd -P)
[[ $(uname -s) == Linux ]] || { echo 'NOT RUN: native Linux required' >&2; exit 2; }
[[ -z ${OECORE_TARGET_SYSROOT:-} ]] || { echo 'Use a fresh native shell without the Poky SDK environment' >&2; exit 2; }
for command in python3 cmake g++ ffmpeg; do
  command -v "$command" >/dev/null || { echo "Missing dependency: $command" >&2; exit 2; }
done
# A separate local POSIX filesystem copy, not the frozen parent or an HGFS cache.
work=$(mktemp -d /tmp/lp2-public-gate.XXXXXX)
echo "Offline evidence/clean copy: $work (retained; no automatic recursive deletion)"
python3 -B "$root/tools/check_candidate.py" --copy-to "$work/repository"
cd "$work/repository"
python3 -B tools/check_candidate.py
cmake -S . -B build/native -DCMAKE_CXX_COMPILER="$(command -v g++)" \
  -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTING=ON -DLP2_BUILD_TOOLS=ON
cmake --build build/native -- -j2
ctest --test-dir build/native --output-on-failure
ffmpeg -nostdin -v error -xerror -i tests/fixtures/synthetic_720p.jpg \
  -frames:v 1 -f null -
for script in scripts/release/build_release.sh tools/validate_ubuntu.sh; do bash -n "$script"; done
for script in scripts/release/board_release.sh scripts/service/lp2-media \
  scripts/service/lp2-watchdog scripts/service/manage_sysv.sh scripts/service/manage_watchdog.sh \
  scripts/stability/board_resource_probe.sh scripts/stability/monitor_rtsp_resources.sh \
  scripts/stability/mark_phase.sh; do sh -n "$script"; done
python3 -B tools/run_offline_regressions.py
echo 'Ubuntu offline/clean-copy Gate PASS (NOT a hardware or Poky Gate)'
