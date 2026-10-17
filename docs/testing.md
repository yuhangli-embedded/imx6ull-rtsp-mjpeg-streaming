# Tests and reproducibility

## Single Ubuntu offline command

From this repository root, with native g++, CMake, Python3, FFmpeg and GNU/POSIX tools:

```bash
bash tools/validate_ubuntu.sh
```

The gate exports only PUBLIC_FILES.json entries into a unique local /tmp clean
copy (not an HGFS build cache), leaves evidence there, and performs:

1. Hash/source-map, quoted-header, relative-link, Python syntax and upload-type audit.
2. Native CMake build and all six CTests, without camera or board access.
3. Actual FFmpeg JPEG decoding with errors treated as failures.
4. Shell syntax and all release/service/watchdog/stability/dual-client offline suites.

It does not silently skip unavailable POSIX features, install dependencies, SSH,
run the hardware server, change network rules or alter any host service. Do not
run it in an SDK-contaminated shell. Keep the reported temporary directory as
evidence; removal is manual and scoped to that generated directory.

## Six CTests

- RTSP request/response, SDP, transport parsing.
- PT96/PT26 regression and marker/header checks using synthetic JPEG.
- Concurrent fixed-pool reference accounting and per-client drop-oldest.
- Slow/fast client sender isolation with a socket-free sink double.
- RTP/JPEG scan/DQT preservation, fragmentation, reverse order, duplicates,
  loss timeout, malformed headers, offset/capacity/boundary checks.
- JPEG compatibility parsing, table/sampling validation and malformed marker rejection.

No GUI test or two real network clients is implied by these unit tests. Decoder
validity is checked independently, not just by the sender/receiver sharing a parser.

## Release/service fixture adaptation

Release tests generate a deterministic **metadata-only ELF** in unique temporary
fixtures. It has ARM ELF32/hard-float metadata and dependency strings but no machine
code, no executable segment and entry=0. It is never run or distributed as a
Release. SHA, interpreter/dependency assertions remain, as do live-process
blocking, wrong approval, failed rename protection, tamper and rollback assertions.
The old artifact-identity test now identifies this explicit fixture rather than
requiring a historical private ARM binary. This is not an SDK/ABI execution test.

Service metadata tests read [public run arguments](../config/run-args.txt), not
a private Release directory. Actual service/helper/installer logic remains intact.
GNU external mv -T is required for the existing ash fixture profile; that does
not prove arbitrary board BusyBox applet compatibility.

## Windows observations and limits

`tools/run_portable_checks.py` compiles six checks with a host C++ compiler.
`tools/run_offline_regressions.py --windows-subset` selects explicitly named logic
suites and reports native install/diagnostic suites NOT RUN. Windows tests emulate
delivery of a child SIGINT where POSIX signals are unavailable; they are not Linux
signal/procfs/rename Gates. No assertion is dropped to obtain these subsets.

The included fixture was also decoded with the Windows platform JPEG decoder.
Ubuntu CMake/CTest, full POSIX regressions and the Poky build have separate
PASS results, including the new Huffman revision as reported by the maintainer;
see [validation](validation.md) for the supplied ARM hash and evidence boundary.
Local _validation output is ignored and
excluded from PUBLIC_FILES.json; never force-add generated executables or logs.

## Hardware tests

The M9.3 client runner is opt-in and **does use SSH**. It is never invoked by the
offline gate. Its lab URL and host are fixed examples in the copied script; no
--host/--url option is claimed to exist. Review these constants before an explicitly
authorized lab run. It requires two free session slots and noninteractive SSH.
PASS needs decoded frames after A exits, not merely a live B process. Client
exit reasons and SSH failure are distinguished; an incomplete probe is INCONCLUSIVE.
