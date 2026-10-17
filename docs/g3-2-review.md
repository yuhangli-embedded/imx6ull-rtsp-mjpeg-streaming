# ARM and publication review

This record describes the pre-replacement candidate. The public Huffman component
has since been redesigned; its native/Poky checks have now passed per the
maintainer, with the replacement hash recorded in [validation](validation.md). See
[replacement](huffman-replacement.md). No frozen media/service source changed.

## Build status

Native clean-copy build and162 tests passed. The specified Poky ARM build and
static SDK ABI gate passed; the reported binary SHA-256 matches M7.2.
See [validation](validation.md) for the hash, counts and evidence boundaries.

The [Poky gate](build.md) uses the specified SDK, a fresh source copy and build
cache, and the existing toolchain. It reuses the release ELF parser and compares
symbol requirements per SDK library. It never executes or deploys an ARM binary.

## Upload and security boundary

`PUBLIC_FILES.json` is the upload allowlist. `SOURCE_MAP.json` retains63 source
mappings. Service sources are unchanged; the Huffman replacement is documented
as a public-only media-component change. Export only the
allowlist with `tools/check_candidate.py --copy-to`; never upload the entire
local validation directory. Build outputs, private logs, images, receipts and
SDK contents are not source-delivery files.

SDK/product absolute paths and the example laboratory IP are intentional.
Deployment scripts require privilege and RTSP has no authentication; use a
trusted laboratory network. Pattern checks cannot guarantee absence of all
secrets. See [deployment](deployment.md).

## Remaining publication decision

Project publication rights are confirmed. The unknown implementation has been
replaced with new code and documented specification parameters. Project material
is MIT; the historical RFC notice and terms are retained separately.
See [notices](../THIRD_PARTY_NOTICES.md) and the
[final checklist](publication-checklist.md).

M9 remains CONDITIONAL PASS; M9.3 full automatic Gate remains INCONCLUSIVE;
ffplay window-close coupling remains OPEN. No significant M8 end-to-end latency
improvement is claimed. This document is not authorization to publish.
