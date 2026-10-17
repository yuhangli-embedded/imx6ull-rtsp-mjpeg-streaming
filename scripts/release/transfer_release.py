#!/usr/bin/env python3
"""Ubuntu LP2 upload helper. Default is local review ONLY, never SSH/SCP."""
import argparse
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

from release_package import ROOT, version, verify_package, digest

BOARD = "root@192.168.50.2"
OPTIONS = ["-o", "HostKeyAlgorithms=+ssh-rsa", "-o", "ConnectTimeout=5"]
HELPER = Path(__file__).with_name("board_release.sh")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("version")
    parser.add_argument("--execute", action="store_true", help="future explicit upload authorization; no activation")
    args = parser.parse_args()
    ver = version(args.version)
    package = ROOT / "releases" / ver
    if ROOT not in package.resolve().parents:
        raise ValueError("Package path escapes LP2")
    if not (package / "SHA256SUMS").is_file():
        raise ValueError("No completed fresh Release package; build it first")
    verify_package(package, ver)
    for tool in ("ssh", "scp"):
        if not shutil.which(tool):
            raise ValueError("Ubuntu dependency missing: " + tool)
    ssh = ["ssh"] + OPTIONS + [BOARD]
    commands = [(ssh + ["sh -s -- init"], True),
                (ssh + ["sh -s -- stage " + ver], True),
                (["scp"] + OPTIONS + ["-r", str(package) + "/.",
                                      BOARD + ":/opt/lp2-media/staging/" + ver + "/"], False),
                (ssh + ["sh -s -- verify-staged " + ver], True)]
    print("UPLOAD ONLY: no install, no switch, no stop/restart, no autostart.")
    # Review trusted local index against received index, not just a remote
    # package's self-consistency. Hash is passed as an exact shell-safe literal.
    expected_index = digest(package / "SHA256SUMS")
    commands.append((ssh + ["test \"$(sha256sum /opt/lp2-media/staging/" + ver +
                           "/SHA256SUMS | awk '{print $1}')\" = " + expected_index], False))
    for command, stdin in commands:
        print(shlex.join(command) + (" < " + shlex.quote(str(HELPER)) if stdin else ""))
        if args.execute:
            subprocess.run(command, input=HELPER.read_bytes() if stdin else None,
                           check=True, timeout=120)
    if not args.execute:
        print("DRY REVIEW: no remote connections were made. Use --execute only after approval.")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print("ERROR: " + str(error), file=sys.stderr)
        sys.exit(1)
