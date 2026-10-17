#!/usr/bin/env python3
"""LP2 release metadata/packaging; stdlib only, never connects to a board."""
import argparse
import hashlib
import json
import re
import shutil
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASELINE = "c1d0c7b0518cf21af091834c5cff400bbf538682b9560c02cce6932c2d9ba04e"
ARGS = "--device /dev/video2 --width 1280 --height 720 --fps 30 --rtsp-port 8554 --path /live --max-clients 2 --slow-client-id 0 --slow-client-delay-ms 0 --udp-gap-us 10 --udp-frame-budget-ms 100 --frames 0"
FILES = ("bin/lp2_rtsp_server", "manifest", "run-args.txt", "build-info.txt",
         "source-sha256.json", "elf.json")


def version(value):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", value):
        raise ValueError("invalid version (1..64 safe ASCII characters)")
    return value


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verify_package(directory, ver):
    entries = list(directory.rglob("*"))
    if any(p.is_symlink() for p in entries) or directory.is_symlink():
        raise ValueError("package symlinks forbidden")
    actual_names = {p.relative_to(directory).as_posix() for p in entries}
    if actual_names != set(FILES) | {"bin", "SHA256SUMS"}:
        raise ValueError("unexpected/missing package entries")
    if not (directory / "bin").is_dir() or any(not (directory / name).is_file()
                                               for name in FILES + ("SHA256SUMS",)):
        raise ValueError("package entries must be regular files and one bin directory")
    lines = (directory / "SHA256SUMS").read_text(encoding="ascii").splitlines()
    if len(lines) != len(FILES):
        raise ValueError("wrong checksum entry count")
    seen = set()
    for line in lines:
        match = re.fullmatch(r"([0-9a-f]{64})  (.+)", line)
        if not match or match[2] not in FILES or match[2] in seen:
            raise ValueError("unsafe checksum index")
        seen.add(match[2])
        if digest(directory / match[2]) != match[1]:
            raise ValueError("local package checksum mismatch: " + match[2])
    manifest = (directory / "manifest").read_text(encoding="ascii")
    if "version=" + version(ver) + "\n" not in manifest:
        raise ValueError("local package version mismatch")
    elf(directory / "bin/lp2_rtsp_server")


def sources():
    paths = []
    for module in ("m3_frame_pipeline", "m4_mjpeg_filesink", "m4_rtp_jpeg",
                   "m4_rtp_jpeg_check", "m5_rtsp_server"):
        paths += [p for p in (ROOT / module).rglob("*") if p.is_file() and
                  (p.suffix in (".cpp", ".h", ".hpp") or p.name == "CMakeLists.txt")]
    paths.append(ROOT / "cmake/toolchains/imx6ull-poky.cmake")
    if any(ROOT not in p.resolve().parents for p in paths):
        raise ValueError("source symlink escapes LP2")
    return {p.relative_to(ROOT).as_posix(): digest(p) for p in sorted(paths)}


def elf(path):
    data = Path(path).read_bytes()
    if len(data) < 52 or data[:7] != b"\x7fELF\x01\x01\x01":
        raise ValueError("requires ELF32 little-endian")
    machine = struct.unpack_from("<H", data, 18)[0]
    flags, = struct.unpack_from("<I", data, 36)
    if machine != 40 or flags & 0xFF000000 != 0x05000000 or not flags & 0x400:
        raise ValueError("requires ARM EABI5 hard-float ELF")
    off, = struct.unpack_from("<I", data, 28)
    entsize, count = struct.unpack_from("<HH", data, 42)
    if entsize < 32 or off + entsize * count > len(data):
        raise ValueError("invalid program header bounds")
    headers = [struct.unpack_from("<8I", data, off + i * entsize) for i in range(count)]
    for h in headers:
        if h[1] + h[4] > len(data):
            raise ValueError("invalid segment bounds")
    interp = [data[h[1]:h[1] + h[4]].rstrip(b"\0").decode("ascii") for h in headers if h[0] == 3]
    if interp != ["/lib/ld-linux-armhf.so.3"]:
        raise ValueError("unexpected dynamic interpreter")
    dynamic = []
    for h in headers:
        if h[0] == 2:
            if h[4] % 8:
                raise ValueError("invalid dynamic segment")
            for pos in range(h[1], h[1] + h[4], 8):
                tag, value = struct.unpack_from("<II", data, pos)
                if tag == 0:
                    break
                dynamic.append((tag, value))
    tables = [v for t, v in dynamic if t == 5]
    sizes = [v for t, v in dynamic if t == 10]
    if len(tables) != 1 or len(sizes) != 1:
        raise ValueError("missing/ambiguous dynamic string table")
    table = None
    for h in headers:
        if h[0] == 1 and h[2] <= tables[0] and tables[0] + sizes[0] <= h[2] + h[4]:
            start = h[1] + tables[0] - h[2]
            table = data[start:start + sizes[0]]
    if table is None:
        raise ValueError("dynamic string table outside load segment")
    needed = []
    for tag, value in dynamic:
        if tag == 1:
            end = table.find(b"\0", value)
            if value >= len(table) or end < 0:
                raise ValueError("invalid dependency string")
            needed.append(table[value:end].decode("ascii"))
    return dict(architecture="ARM ELF32 little-endian EABI5 hard-float", e_flags=hex(flags),
                interpreter=interp[0], needed=needed, sha256=digest(path), size=len(data))


def write_json(path, value):
    path.write_bytes((json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))


def create(ver):
    ver = version(ver)
    base = ROOT / "build/releases" / ver
    if ROOT not in base.resolve().parents:
        raise ValueError("build directory escapes LP2")
    binary = base / "build/lp2_m5_rtsp_server"
    info = base / "build-info.txt"
    if not info.is_file() or "fresh-poky-release-build" not in info.read_text():
        raise ValueError("fresh build provenance required; historical build directories are not accepted")
    snapshot = json.loads((base / "source-sha256.json").read_text())
    if snapshot != sources():
        raise ValueError("source changed during build; discard candidate and use a NEW version")
    details = elf(binary)
    package = ROOT / "releases" / ver
    if ROOT not in package.resolve().parents:
        raise ValueError("package directory escapes LP2")
    if package.exists() or package.is_symlink():
        raise ValueError("package already exists; never overwrite a published version")
    # Complete locally before upload; failure leaves no package to promote.
    package.mkdir(parents=True)
    (package / "bin").mkdir()
    shutil.copyfile(binary, package / "bin/lp2_rtsp_server")
    shutil.copyfile(info, package / "build-info.txt")
    shutil.copyfile(base / "source-sha256.json", package / "source-sha256.json")
    (package / "run-args.txt").write_bytes((ARGS + "\n").encode("ascii"))
    write_json(package / "elf.json", details)
    match = details["sha256"] == BASELINE
    (package / "manifest").write_bytes((
        "format=lp2-release-v1\nversion={}\nbinary_sha256={}\norigin=fresh-poky-release-build\n"
        "baseline_sha256={}\nbaseline_hash_equal={}\nhardware_gate=PENDING\n".format(
            ver, details["sha256"], BASELINE, "yes" if match else "no")).encode("ascii"))
    (package / "SHA256SUMS").write_bytes("".join("{}  {}\n".format(digest(package / n), n)
                                                for n in FILES).encode("ascii"))
    verify_package(package, ver)
    print(json.dumps(dict(package=str(package), binary=details,
                          package_index_sha256=digest(package / "SHA256SUMS"),
                          baseline_hash_equal=match, hardware_gate="PENDING"), indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("snapshot")
    audit = sub.add_parser("audit")
    audit.add_argument("binary", type=Path)
    package = sub.add_parser("create")
    package.add_argument("version")
    args = parser.parse_args()
    if args.action == "snapshot":
        print(json.dumps(sources(), indent=2))
    elif args.action == "audit":
        binary = args.binary.resolve()
        if ROOT not in binary.parents:
            raise ValueError("binary must be inside LP2")
        print(json.dumps(dict(binary=str(binary.relative_to(ROOT)), elf=elf(binary),
                              baseline_sha256=BASELINE, current_source_sha256=sources()), indent=2))
    else:
        create(args.version)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, struct.error) as error:
        print("ERROR: " + str(error), file=sys.stderr)
        sys.exit(1)
