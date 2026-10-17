#!/usr/bin/env python3
"""Static SDK ABI gate only; never executes the ARM binary or contacts a board."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
ALLOWED = {'libpthread.so.0', 'libstdc++.so.6', 'libgcc_s.so.1', 'libc.so.6', 'libm.so.6'}
VERSION = r'(?:GLIBC_|GLIBCXX_|CXXABI_|GCC_)[A-Za-z0-9_.]+'


def needs(text):
    result = {}
    section = text.partition('Version needs section')[2]
    current = None
    for line in section.splitlines():
        match = re.search(r'File:\s+(\S+)', line)
        if match:
            current = match[1]
            result.setdefault(current, set())
        match = re.search(r'Name:\s+(' + VERSION + r')', line)
        if match:
            if current is None:
                raise ValueError('Version requirement without provider')
            result[current].add(match[1])
    return result


def definitions(text):
    section = text.partition('Version definition section')[2].split('Version needs section')[0]
    return set(re.findall(r'Name:\s+(' + VERSION + r')', section))


def check_versions(required, provided):
    for library, versions in required.items():
        missing = versions - provided.get(library, set())
        if missing:
            raise ValueError('Missing SDK versions in {}: {}'.format(library, sorted(missing)))
        for value in versions:
            if value.startswith('GLIBC_'):
                number = value[6:]
                if not re.fullmatch(r'\d+\.\d+(?:\.\d+)?', number):
                    raise ValueError('Unsupported GLIBC requirement: ' + value)
                parts = tuple(map(int, number.split('.')))
                if (parts + (0,) * (3 - len(parts))) > (2, 23, 0):
                    raise ValueError('Requires newer than glibc 2.23: ' + value)


def sysroot_file(root, relative):
    """Resolve target-absolute SDK symlinks inside sysroot, never host /lib."""
    root = root.resolve()
    todo = list(Path(relative).parts)
    current = root
    links = 0
    while todo:
        part = todo.pop(0)
        if part in ('', '.', '/'):
            continue
        if part == '..':
            if current == root:
                raise ValueError('SDK link escapes sysroot')
            current = current.parent
            continue
        current = current / part
        if current.is_symlink():
            links += 1
            if links > 32:
                raise ValueError('SDK symlink loop')
            target = Path(os.readlink(current))
            current = root if target.is_absolute() else current.parent
            todo = list(target.parts) + todo
    if not current.is_file():
        raise ValueError('Missing SDK file: ' + str(current))
    return current


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', type=Path, required=True)
    parser.add_argument('--sysroot', type=Path, required=True)
    parser.add_argument('--readelf', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location('release_package', ROOT / 'scripts/release/release_package.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    details = module.elf(args.binary)
    if not details['needed'] or set(details['needed']) - ALLOWED:
        raise ValueError('Unexpected/empty dynamic dependencies')

    def readelf(option, path):
        result = subprocess.run([str(args.readelf), option, str(path)], capture_output=True,
                                text=True, check=True, timeout=30, env=dict(os.environ, LC_ALL='C'))
        return result.stdout

    for option, suffix in [('-h', 'header'), ('-l', 'segments'), ('-d', 'dynamic'),
                           ('-V', 'versions'), ('-A', 'attributes')]:
        (args.output.parent / ('readelf-' + suffix + '.txt')).write_text(readelf(option, args.binary))
    attributes = readelf('-A', args.binary)
    if not re.search(r'Tag_ABI_VFP_args:\s+VFP registers', attributes):
        raise ValueError('Missing hard-float VFP calling convention attribute')
    required = needs(readelf('-V', args.binary))
    if (not any(v.startswith('GLIBC_') for v in required.get('libc.so.6', set()))
            or set(required) - set(details['needed'])):
        raise ValueError('Missing/inconsistent version requirements')
    if re.search(r'\((?:RPATH|RUNPATH)\)', readelf('-d', args.binary)):
        raise ValueError('Unexpected runtime search path; review before approval')
    provided, libraries = {}, {}
    for name in details['needed'] + [details['interpreter'].lstrip('/')]:
        if '/' in name:
            path = sysroot_file(args.sysroot, name)
        else:
            candidates = []
            for directory in ('lib', 'usr/lib'):
                try:
                    candidates.append(sysroot_file(args.sysroot, directory + '/' + name))
                except ValueError:
                    pass
            if not candidates:
                raise ValueError('Dependency missing in SDK: ' + name)
            path = candidates[0]
        header = path.read_bytes()[:20]
        if header[:7] != b'\x7fELF\x01\x01\x01' or header[18:20] != b'\x28\x00':
            raise ValueError('SDK dependency is not ARM ELF32 LE: ' + name)
        provided[name] = definitions(readelf('-V', path))
        libraries[name] = str(path.relative_to(args.sysroot.resolve()))
    check_versions(required, provided)
    report = dict(gate='PASS: STATIC_SDK_ABI_ONLY', binary=details,
                  required_versions={k: sorted(v) for k, v in required.items()},
                  sdk_libraries=libraries, board_runtime_gate='NOT RUN',
                  boundary='SDK symbol definitions checked; installed board libraries not inspected')
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
