#!/usr/bin/env python3
"""Offline suites only; never SSH, install, run media, or signal real services."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--windows-subset', action='store_true')
    args = parser.parse_args()
    if args.windows_subset != (os.name == 'nt'):
        parser.error('Use full suites on Linux; --windows-subset is Windows-only')
    output = ROOT / '_validation/offline'
    output.mkdir(parents=True, exist_ok=True)
    command = [sys.executable, '-B']
    if args.windows_subset:
        suites = [
            ('service-logic', 'scripts/service/tests', command + ['-m', 'unittest', '-v', 'test_sysv.LogicTests']),
            ('watchdog-logic', 'scripts/service/tests', command + ['-m', 'unittest', '-v', 'test_watchdog.WatchdogTests']),
            ('release-metadata-process', 'scripts/release/tests', command + ['-m', 'unittest', '-v', 'test_release.PackageTests', 'test_release.ProcessScanTests']),
        ]
    else:
        suites = [(name, '.', command + [path, '-v']) for name, path in (
            ('service-full', 'scripts/service/tests/test_sysv.py'),
            ('watchdog-full', 'scripts/service/tests/test_watchdog.py'),
            ('release-full', 'scripts/release/tests/test_release.py'))]
    suites += [(name, '.', command + [path, '-v']) for name, path in (
        ('stability', 'scripts/stability/tests/test_stability.py'),
        ('dual-client-offline', 'scripts/acceptance/tests/test_m9_dual_client_gate.py'))]
    results = []
    for name, cwd, argv in suites:
        print('Running ' + name, flush=True)
        environment = dict(os.environ, PYTHONDONTWRITEBYTECODE='1')
        result = subprocess.run(argv, cwd=str(ROOT / cwd), env=environment,
                                capture_output=True, text=True, timeout=240)
        text = result.stdout + result.stderr
        (output / (name + '.log')).write_text(text, encoding='utf-8')
        count = re.search(r'Ran (\d+) tests?', text)
        entry = dict(suite=name, count=int(count[1]) if count else None, exit_code=result.returncode)
        results.append(entry)
        (output / 'result.json').write_text(json.dumps(results, indent=2)+'\n')
        print(entry, flush=True)
        if result.returncode:
            print(text, file=sys.stderr)
            return 1
        if not count or re.search(r'\bskipped=', text):
            raise RuntimeError('Incomplete/skipped suite is not accepted: ' + name)
    if args.windows_subset:
        print('Native POSIX install/diagnostic suites: NOT RUN (not counted as passing).')
    return 0


if __name__ == '__main__':
    sys.exit(main())
