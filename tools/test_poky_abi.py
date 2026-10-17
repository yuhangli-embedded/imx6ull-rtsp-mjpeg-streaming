#!/usr/bin/env python3
"""Offline checker regressions, NOT an ARM compile or runtime test."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

import check_poky_abi as abi

NEEDS = '''Version needs section '.gnu.version_r' contains 2 entries:
  0x00: Version: 1 File: libc.so.6 Cnt: 2
  0x10: Name: GLIBC_2.4 Flags: none Version: 3
  0x20: Name: GLIBC_2.17 Flags: none Version: 4
  0x30: Version: 1 File: libstdc++.so.6 Cnt: 1
  0x40: Name: GLIBCXX_3.4.21 Flags: none Version: 5
'''


class Checks(unittest.TestCase):
    def test_per_library_needs(self):
        self.assertEqual(abi.needs(NEEDS), {'libc.so.6': {'GLIBC_2.4', 'GLIBC_2.17'},
                                           'libstdc++.so.6': {'GLIBCXX_3.4.21'}})

    def test_no_requirement_promoted_to_definition(self):
        text = "Version definition section '.gnu.version_d':\n Name: GLIBC_2.4\n" + NEEDS
        self.assertEqual(abi.definitions(text), {'GLIBC_2.4'})
        self.assertEqual(abi.definitions(NEEDS), set())

    def test_sdk_versions(self):
        required = abi.needs(NEEDS)
        abi.check_versions(required, required)

    def test_wrong_library_cannot_supply_version(self):
        with self.assertRaises(ValueError):
            abi.check_versions({'libc.so.6': {'GLIBC_2.4'}}, {'libm.so.6': {'GLIBC_2.4'}})

    def test_newer_glibc_rejected_even_if_sdk_provides_it(self):
        for name in ('GLIBC_2.24', 'GLIBC_2.34', 'GLIBC_2.23.1', 'GLIBC_PRIVATE'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                abi.check_versions({'libc.so.6': {name}}, {'libc.so.6': {name}})

    def test_glibc_boundary(self):
        for name in ('GLIBC_2.4', 'GLIBC_2.17', 'GLIBC_2.23'):
            abi.check_versions({'libc.so.6': {name}}, {'libc.so.6': {name}})

    def test_bad_version_record(self):
        with self.assertRaises(ValueError):
            abi.needs('Version needs section\n Name: GLIBC_2.4')

    def test_sysroot_regular_and_missing(self):
        with tempfile.TemporaryDirectory(dir=abi.ROOT / '_validation') as directory:
            root = Path(directory)
            (root / 'lib').mkdir()
            (root / 'lib/libc.so.6').write_bytes(b'fixture')
            self.assertEqual(abi.sysroot_file(root, 'lib/libc.so.6'), root / 'lib/libc.so.6')
            with self.assertRaises(ValueError):
                abi.sysroot_file(root, 'lib/missing')
            with self.assertRaises(ValueError):
                abi.sysroot_file(root, '../outside')

    def test_existing_elf_checks_reject_host_architecture(self):
        spec = importlib.util.spec_from_file_location('fixture', abi.ROOT / 'scripts/release/tests/elf_fixture.py')
        fixture = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(fixture)
        spec = importlib.util.spec_from_file_location('release', abi.ROOT / 'scripts/release/release_package.py')
        release = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(release)
        with tempfile.TemporaryDirectory(dir=abi.ROOT / '_validation') as directory:
            path = Path(directory) / 'fixture'
            # Use the public metadata-only fixture, never execute it.
            data = bytearray(fixture.arm_metadata_fixture())
            path.write_bytes(data)
            self.assertEqual(release.elf(path)['interpreter'], '/lib/ld-linux-armhf.so.3')
            data[18:20] = b'\x3e\x00'
            path.write_bytes(data)
            with self.assertRaises(ValueError):
                release.elf(path)


if __name__ == '__main__':
    (abi.ROOT / '_validation').mkdir(exist_ok=True)
    unittest.main()
