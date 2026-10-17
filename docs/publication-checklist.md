# Publication checklist

## Source delivery

[PUBLIC_FILES.json](../PUBLIC_FILES.json) is the exact file/hash inventory,
excluding its own self-hash. [SOURCE_MAP.json](../SOURCE_MAP.json) retains63
origin mappings and the separately documented standard-parameter source.
Deliver only the allowlisted export, not an unfiltered workspace archive.

The source delivery includes selected module sources, root CMake/toolchain,
run arguments, operational/test tools, synthetic JPEG/generator, documentation,
[MIT LICENSE](../LICENSE), [third-party notices](../THIRD_PARTY_NOTICES.md) and
[historical RFC notice](../LICENSES/RFC2435-notice.txt). Preserve both license
scopes. No ARM executable, SDK/sysroot, private image, cache, raw log or receipt
is an upload deliverable.

## Validation ledger

| Revision / check | Result / evidence boundary |
| --- | --- |
| Replacement: Ubuntu native build and tests | Maintainer reports162/162 PASS |
| Replacement: ABI-checker tests | Maintainer reports9/9 PASS |
| Replacement: specified Poky ARM build and static SDK ABI | Maintainer reports PASS |
| Replacement: ARM executable SHA-256 | 8b631abafc478e21e23e755d2676f5061bde8292df16c5bc552c4e27e3e84f46; supplied by maintainer, not recomputed in this review |
| Pre-replacement ARM SHA-256 | ad657b4177ca3ad882e7427677bce915d8a26642f1086023c7fa16dfaabddb35; historical M7.2 match ONLY |
| New hardware testing | Not performed or required by this notice-only review |

Do not substitute the historical hash into the replacement row. The numeric
replacement hash is now recorded from the maintainer's result. Its ARM binary
and raw abi.json/SHA256SUMS are not bundled or independently inspected here.
No binary hash is inferred from a source hash. Build results were not rerun.

## License and publication review

- Maintainer confirms project publication rights and no institutional/employer
  prohibition; no contributor history is invented.
- Project-authored code, scripts and documents are MIT licensed. The neutral
  copyright credit identifies the LP2 project author, not a fabricated legal name.
- RFC2435-derived parameter material keeps historical1998 terms and its required
  retained notice. It is not relicensed under MIT or retroactive Revised BSD.
  See [official-source review](rfc2435-license-review.md).
- The identified RFC copyright blocker is addressed for this scoped distribution.
  This is not a legal certification or a patent/trademark clearance.
- M9 remains CONDITIONAL PASS; M9.3 full automatic Gate remains INCONCLUSIVE;
  ffplay window-close coupling remains OPEN. M8 did not prove significant
  end-to-end latency reduction. Do not change these boundaries for publicity.
- Privileged deployment and unauthenticated RTSP are explicitly lab-only.

## Git boundary and next action

The root .gitignore defaults to ignoring files, permits directory traversal,
then explicitly permits upload-listed paths and this inventory. Generated
directories stay ignored. This does not remove already tracked files or
prevent force-add; review any eventual staged file list against the inventory.

`python3 tools/check_candidate.py` checks hashes/mappings/links and rejects
unexpected upload files. Its optional export copies only listed files to a new
directory. Keep local evidence outside the upload.

The identified license and missing numeric-hash items are addressed; the candidate
can proceed to the repository-creation review with the stated evidence boundaries.
This does not convert historical CONDITIONAL PASS into unconditional PASS. No Git
initialization, commit, push, remote creation, board access or deployment was
performed by this review.
