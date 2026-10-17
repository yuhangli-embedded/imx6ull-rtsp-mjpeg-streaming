# Synthetic JPEG fixture

`synthetic_720p.jpg` contains only deterministic16x16 pixel geometric color cells,
not a photograph, screenshot, person or room. RGB cell values are:

```text
a=x/16, b=y/16
R=(37*a+17*b)%256
G=(11*a+43*b)%256
B=(23*a+7*b)%256
```

Dimensions1280x720, JPEG quality88; produced using the Windows platform encoder
by [generate_windows.ps1](generate_windows.ps1). That script never reads an image
input, refuses overwrite, and performs a real platform JPEG decode afterwards.
No image-generation service or copied third-party photograph was used.

```text
Bytes: 25647
SHA-256: 5803a43ad1d57ad96ed1ea683a16029023e845469b67b186886614d87f3a4b0b
```

The unchanged JPEG inspector test verifies baseline1280x720, type1/4:2:0, two DQT,
four canonical DHT and one complete scan. Existing tests also require multiple
RTP packets and scan/table byte preservation. Independent Windows decode passed;
the Ubuntu gate requires a separate FFmpeg decode. No decoder success is inferred
from marker checks alone.

The checked-in bytes are authoritative test input; Windows encoder versions may
produce different bytes on regeneration. This is reproducible test consumption,
not a cross-encoder bit-reproducibility claim. Regeneration is optional and not a
Linux build dependency. Review new bytes/format/provenance before changing the hash.

The generated ELF fixture is **source code** in
[elf_fixture.py](../../scripts/release/tests/elf_fixture.py), not a checked-in
ARM executable. It is metadata-only and never executed; see [testing](../../docs/testing.md).
