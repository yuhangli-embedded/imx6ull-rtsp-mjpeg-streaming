#!/usr/bin/env python3
"""Read-only source candidate audit; optional allowlisted clean-copy export."""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import re
import shutil

ROOT = Path(__file__).resolve().parents[1]
IGNORED = {'_validation', 'build', 'results', 'test-results', 'releases', '__pycache__', '.git'}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit():
    manifest = json.loads((ROOT / 'PUBLIC_FILES.json').read_text())
    entries = manifest['files']
    listed = {entry['path'] for entry in entries}
    if len(listed) != len(entries):
        raise ValueError('Duplicate manifest entries')
    for entry in entries:
        path = ROOT / entry['path']
        if ROOT not in path.resolve().parents or path.is_symlink() or not path.is_file():
            raise ValueError('Missing/unsafe candidate path: ' + entry['path'])
        if digest(path) != entry['sha256']:
            raise ValueError('Candidate changed since inventory: ' + entry['path'])
    actual = set()
    for path in ROOT.rglob('*'):
        relative = path.relative_to(ROOT)
        if any(part in IGNORED for part in relative.parts):
            continue
        if path.is_symlink():
            raise ValueError('Unreviewed symlink: ' + str(relative))
        if path.is_file():
            actual.add(relative.as_posix())
    if actual != listed | {'PUBLIC_FILES.json'}:
        raise ValueError('Unexpected/missing upload files: ' + str(actual ^ (listed | {'PUBLIC_FILES.json'})))
    copied = json.loads((ROOT / 'SOURCE_MAP.json').read_text())['files']
    for entry in copied:
        if entry['public_path'] not in listed:
            raise ValueError('Source map escapes the upload allowlist')
        if digest(ROOT / entry['public_path']) != entry['public_sha256']:
            raise ValueError('Source mapping mismatch: ' + entry['public_path'])
    added = json.loads((ROOT / 'SOURCE_MAP.json').read_text()).get('new_public_sources', [])
    for entry in added:
        if entry['public_path'] not in listed or digest(ROOT / entry['public_path']) != entry['public_sha256']:
            raise ValueError('New public-source mapping mismatch: ' + entry['public_path'])
    includes = {name.split('/include/', 1)[1] for name in listed if '/include/' in name}
    links = 0
    for name in listed:
        path = ROOT / name
        if path.suffix == '.py':
            ast.parse(path.read_text(encoding='utf-8'))
        if path.suffix not in {'.md', '.cpp', '.hpp', '.py', '.sh', '.txt', '.cmake', '.json', '.ps1'} and path.name not in {'CMakeLists.txt', 'lp2-media', 'lp2-watchdog'}:
            continue
        text = path.read_text(encoding='utf-8')
        if path.suffix in {'.cpp', '.hpp'}:
            for header in re.findall(r'^#include "(lp2/[^"]+)"', text, re.M):
                if header not in includes:
                    raise ValueError('Missing project header: ' + header)
        if path.suffix == '.md':
            for target in re.findall(r'\[[^\]]*\]\(([^)]+)\)', text):
                if re.match(r'https?://|#', target):
                    continue
                target = target.split('#')[0]
                resolved = (path.parent / target).resolve()
                if ROOT not in (resolved, *resolved.parents) or not resolved.exists():
                    raise ValueError('Broken/external local link: ' + name + ': ' + target)
                links += 1
        secret = re.search(r'-----BEGIN [A-Z ]*PRIVATE KEY-----|github_pat_[A-Za-z0-9_]{24,}|gh[pousr]_[A-Za-z0-9]{30,}|AKIA[0-9A-Z]{16}', text)
        if secret:
            raise ValueError('Credential-like material; manual review required: ' + name)
    for name in listed:
        magic = (ROOT / name).read_bytes()[:4]
        if magic == b'\x7fELF' or magic[:2] == b'MZ':
            raise ValueError('Compiled executable in source allowlist: ' + name)
        if Path(name).suffix.lower() in {'.exe', '.o', '.a', '.dll', '.so', '.bin', '.zip', '.tar', '.gz', '.pdf', '.docx', '.pem', '.key'}:
            raise ValueError('Forbidden upload type: ' + name)
        if Path(name).suffix.lower() == '.jpg' and name != 'tests/fixtures/synthetic_720p.jpg':
            raise ValueError('Unreviewed photo: ' + name)
    print('Candidate audit PASS: {} files, {} mapped sources, {} local links; no parent-workspace reads'.format(len(listed), len(copied), links))
    print('MIT project material and retained historical RFC 2435 terms; pattern scanning is not a legal/security guarantee.')
    return listed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--copy-to', type=Path)
    args = parser.parse_args()
    listed = audit()
    if args.copy_to:
        destination = args.copy_to.resolve()
        if destination.exists():
            raise ValueError('Clean-copy destination must not exist')
        # Prevent an accidental export above/over the candidate itself.
        if destination == ROOT or destination in ROOT.parents:
            raise ValueError('Unsafe clean-copy destination')
        destination.mkdir(parents=True)
        for name in sorted(listed | {'PUBLIC_FILES.json'}):
            target = destination / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, target)
        print('Allowlisted clean copy: ' + str(destination))


if __name__ == '__main__':
    main()
