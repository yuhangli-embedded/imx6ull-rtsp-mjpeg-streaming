# Public-source provenance

This candidate selects43 core build/test files and19 operational/test files from
the frozen LP2 workspace, plus the normal run-arguments text. No parent checkout
is accessed by the build or public validation scripts.

[SOURCE_MAP.json](../SOURCE_MAP.json) records each selected origin as a relative
logical path, its original SHA-256, public path/SHA and the reason for differences.
It contains no private absolute workspace path. Production service/installer
scripts retain their hashes. The public Huffman implementation is now replaced
and inspector assertions extended; see [replacement](huffman-replacement.md).
Other media sources are unchanged. The pre-replacement ARM hash matched M7.2;
that equality is not claimed for this new source.

[PUBLIC_FILES.json](../PUBLIC_FILES.json) is the source upload allowlist and file
hash inventory (excluding itself). The audit can export only those entries into
a clean directory. Generated _validation/build/results/Release outputs are not
upload content. These hashes are not a digital signature or proof of legal ownership.

New files include the root CMake, documentation, validation helpers, deterministic
ELF metadata fixture source and geometric JPEG fixture/generator. The private
camera photograph, binaries, SDK, caches, deployment receipts and raw logs were
not copied. Project-authored material is covered by [MIT](../LICENSE); the
[third-party notice](../THIRD_PARTY_NOTICES.md) separately covers RFC-derived parameters.

Earlier adaptations: three CMake test paths/options; two C++ test message labels
say synthetic rather than camera (conditions unchanged); release tests use generated
metadata instead of a private ARM artifact; service tests use public run-args;
the M9 test's Boot ID, PIDs and start ticks use synthetic values. Safety assertions are retained.

The new parameter header, canonical codebook implementation and regression
assertions are specific public-copy changes, not modifications of frozen sources.
SOURCE_MAP retains original hashes and identifies the replacement explicitly.
