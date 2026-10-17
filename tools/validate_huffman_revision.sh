#!/usr/bin/env bash
# Offline source/host/SDK gates only; no board, service or deployment access.
set -euo pipefail
[[ $OSTYPE == linux* ]] || { echo 'NOT RUN: Ubuntu/Linux required' >&2; exit 2; }
root=$(cd -- "$(dirname -- "$0")/.." && pwd)
cd "$root"
bash tools/validate_ubuntu.sh
python3 -B tools/test_poky_abi.py
bash tools/validate_poky.sh
echo 'Huffman revision host/SDK Gate PASS; license review is separate; no board Gate run.'
