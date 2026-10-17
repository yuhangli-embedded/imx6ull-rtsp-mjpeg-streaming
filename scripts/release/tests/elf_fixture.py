"""Generated ARM ELF metadata fixture, NEVER runnable and never a Release.

Pure stdlib construction keeps release-tool tests independent of SDK/private
executables. All PT_LOAD flags are read-only, entry=0, with NO machine code.
The independent parser assertions still check SHA, interpreter and dependencies.
"""
import hashlib
import struct

NEEDED = ('libpthread.so.0', 'libstdc++.so.6', 'libgcc_s.so.1', 'libc.so.6')
INTERPRETER = b'/lib/ld-linux-armhf.so.3\0'


def arm_metadata_fixture():
    data = bytearray(1024)
    ident = b'\x7fELF\x01\x01\x01' + b'\0' * 9
    # ELF32 ET_DYN, EM_ARM, EABI5 + hard-float; three program headers.
    struct.pack_into('<16sHHIIIIIHHHHHH', data, 0, ident, 3, 40, 1,
                     0, 52, 0, 0x05000400, 52, 32, 3, 0, 0, 0)
    base = 0x10000
    struct.pack_into('<8I', data, 52, 1, 0, base, base, len(data), len(data), 4, 4096)
    struct.pack_into('<8I', data, 84, 3, 160, base+160, base+160,
                     len(INTERPRETER), len(INTERPRETER), 4, 1)
    data[160:160+len(INTERPRETER)] = INTERPRETER
    strings = bytearray(b'\0')
    offsets = []
    for name in NEEDED:
        offsets.append(len(strings)); strings.extend(name.encode('ascii') + b'\0')
    data[512:512+len(strings)] = strings
    dynamic = [(5, base+512), (10, len(strings))] + [(1, i) for i in offsets] + [(0, 0)]
    struct.pack_into('<8I', data, 116, 2, 256, base+256, base+256,
                     len(dynamic)*8, len(dynamic)*8, 4, 4)
    for index, entry in enumerate(dynamic):
        struct.pack_into('<II', data, 256+index*8, *entry)
    return bytes(data)


# Fixed expected digest is filled from a reviewed deterministic generation.
FIXTURE_SHA256 = 'b650e334bdba728cc4fa375241429b1840d8ae771abfe2e8b598c1a5b100ac50'
