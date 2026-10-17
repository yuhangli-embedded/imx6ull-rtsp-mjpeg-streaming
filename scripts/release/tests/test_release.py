"""Offline LP2 packaging, promotion and rollback fixtures; never uses SSH."""
import hashlib
import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
import release_package as package
import transfer_release as transfer
from elf_fixture import arm_metadata_fixture, FIXTURE_SHA256


class FixtureEnvironmentError(RuntimeError):
    """A local filesystem/shell limitation, not a release-tool failure."""


def local_fixture_directory(prefix):
    # Explicit /tmp on Ubuntu: TMPDIR may itself point into VMware HGFS.
    # Only this uniquely generated directory is ever removed by cleanup().
    try:
        # Windows only uses plain-file PackageTests, never POSIX BoardTests.
        return tempfile.TemporaryDirectory(prefix=prefix, dir="/tmp" if os.name == "posix" else str(package.ROOT))
    except OSError as error:
        raise FixtureEnvironmentError("TEST ENVIRONMENT ERROR: cannot create unique local fixture: " + str(error)) from error


def posix_shell():
    if os.name != "posix":
        raise FixtureEnvironmentError(
            "TEST ENVIRONMENT ERROR: native POSIX symlink/rename tests require Ubuntu; "
            "Windows/MSYS emulation is not accepted. No release-tool verdict was made.")
    shell = os.environ.get("LP2_TEST_SHELL") or shutil.which("sh")
    if not shell:
        raise FixtureEnvironmentError("TEST ENVIRONMENT ERROR: local POSIX shell missing")
    return shell


def check_posix_fixture(shell, directory):
    # Test the actual selected local filesystem, including dangling /proc/exe
    # links and replacement of a link to a directory with mv -T.
    source = '''set -eu
PATH=/usr/bin:/bin:$PATH
mkdir posix-check
cd posix-check
mkdir v1 v2
ln -s v1 current
ln -s v2 next
ln -s /lp2-offline-nonexistent/executable exe
[ -L exe ]
[ "$(readlink exe)" = /lp2-offline-nonexistent/executable ]
mv -T next current
[ -L current ] && [ -d current ]
[ "$(readlink current)" = v2 ]
[ ! -e next ] && [ ! -L next ]
'''
    try:
        result = subprocess.run([shell, "-s"], input=source, text=True, encoding="utf-8",
                                capture_output=True, cwd=str(directory), timeout=15)
    except (OSError, subprocess.SubprocessError) as error:
        raise FixtureEnvironmentError("TEST ENVIRONMENT ERROR: POSIX fixture preflight: " + str(error)) from error
    if result.returncode:
        raise FixtureEnvironmentError(
            "TEST ENVIRONMENT ERROR: local fixture {} cannot perform native POSIX "
            "symlink/mv -T operations (exit {}): {}. Release assertions were not "
            "executed; fix the local filesystem/tools, do not skip tests.".format(
                directory, result.returncode, result.stderr.strip()))


class PackageTests(unittest.TestCase):
    def test_generated_artifact_identity_and_dependencies(self):
        with local_fixture_directory("lp2-elf-test-") as temp:
            binary = Path(temp) / "metadata-only.elf"
            binary.write_bytes(arm_metadata_fixture())
            details = package.elf(binary)
        self.assertEqual(details["sha256"], FIXTURE_SHA256)
        self.assertNotEqual(details["sha256"], package.BASELINE)
        self.assertEqual(details["interpreter"], "/lib/ld-linux-armhf.so.3")
        self.assertEqual(set(details["needed"]),
                         {"libpthread.so.0", "libstdc++.so.6", "libgcc_s.so.1", "libc.so.6"})

    def test_version_traversal_and_shell_injection_refused(self):
        for value in ("..", "../x", "/tmp/x", "a b", "a;id", "-x", "x" * 65, ""):
            with self.assertRaises(ValueError):
                package.version(value)
        self.assertEqual(package.version("m7.2-20261013"), "m7.2-20261013")

    def test_no_package_from_historical_build(self):
        with self.assertRaises(ValueError):
            package.create("offline-no-build-fixture")

    def test_bad_elf_bounds_rejected(self):
        with local_fixture_directory("lp2-elf-test-") as temp:
            path = Path(temp) / "bad"
            for data in (b"", b"not an ELF", b"\x7fELF\x01\x01\x01" + b"\0" * 45):
                path.write_bytes(data)
                with self.assertRaises(ValueError):
                    package.elf(path)


def proc_stat(pid, flags=0, ticks=100, comm="strange ) task ( name"):
    # Number fields by the Linux ABI, NOT by production parser indexes.
    # 3=state, 4=ppid, 8=tpgid, 9=flags, 18=priority, 20=num_threads,
    # 22=starttime. This prevents fixtures from repeating an index mistake.
    values = {3: "S", 4: "2", 8: "-1", 9: str(flags),
              18: "20", 20: "1", 22: str(ticks)}
    fields = [values.get(number, "0") for number in range(3, 23)]
    return "{} ({}) {}\n".format(pid, comm, " ".join(fields))


# Exact board-supplied raw prefix through field 22. The user's trailing "..."
# denotes omitted fields; do not fabricate them or put literal dots in stat.
BOARD_PID10_STAT = (
    b"10 (migration/0) S 2 0 0 0 -1 69238848 0 0 0 0 0 0 0 0 -100 0 1 0 2\n"
)


class ProcessScanTests(unittest.TestCase):
    """Execute production scanner with stat fixtures and controlled readlink.

    No native symlink/rename needed here; Windows MSYS can test scanner logic.
    The complete BoardTests still require Ubuntu's native POSIX filesystem.
    """
    def setUp(self):
        self.shell = os.environ.get("LP2_TEST_SHELL") or shutil.which("sh")
        if not self.shell:
            raise FixtureEnvironmentError("TEST ENVIRONMENT ERROR: set LP2_TEST_SHELL to test the scanner")
        self.temp = local_fixture_directory("lp2-process-test-")
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name).resolve()
        self.proc = self.directory / "proc"
        self.proc.mkdir()

    def process(self, pid=42, flags=0, ticks=100, target="/sbin/unrelated", comm="strange ) task ( name"):
        directory = self.proc / str(pid)
        directory.mkdir()
        (directory / "stat").write_bytes(proc_stat(pid, flags, ticks, comm).encode("ascii"))
        if target is not None:
            (directory / "exe").write_bytes((target + "\n").encode("ascii"))
        return directory

    def scan(self, readlink_body='cat "$1"', prefix=""):
        source = (SCRIPTS / "board_release.sh").read_text().rsplit("\ncheck_tools\n", 1)[0]
        source += '\nROOT="$PWD/board"\nPROC="$PWD/proc"\n'
        source += prefix + '\nreadlink() {\n' + readlink_body + '\n}\nidle_required\n'
        return subprocess.run([self.shell, "-s"], input="PATH=/usr/bin:/bin:$PATH\n" + source,
                              text=True, encoding="utf-8", capture_output=True,
                              cwd=str(self.directory), timeout=15)

    def test_kernel_without_executable_skips_readlink_only_after_flag_check(self):
        self.process(flags=0x00200000, ticks=0, target=None)
        result = self.scan('printf "unexpected readlink call\\n" >&2; return 99')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("unexpected", result.stderr)

    def test_board_pid10_observed_flags_and_starttime(self):
        # Literal raw board evidence, independent of the synthetic builder.
        directory = self.proc / "10"
        directory.mkdir()
        (directory / "stat").write_bytes(BOARD_PID10_STAT)
        rest = BOARD_PID10_STAT.decode("ascii").rsplit(") ", 1)[1].split()
        self.assertEqual(int(rest[6]), 69238848)  # original Linux field 9
        self.assertEqual(int(rest[19]), 2)       # original Linux field 22
        self.assertEqual(int(rest[6]) & 0x00200000, 0x00200000)
        result = self.scan('printf "unexpected readlink call\\n" >&2; return 99',
                           prefix='''identity=$(process_identity "$PROC/10")
printf 'identity=[%s] branch=[%s]\\n' "$identity" "${identity##* }"
''')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("identity=[2 1] branch=[1]", result.stdout)
        self.assertNotIn("unexpected", result.stderr)

    def test_fixture_flags_position_matches_linux_stat_abi(self):
        # Independent delimiter/count check, including comm with spaces/parens.
        rest = proc_stat(42, flags=69238848, ticks=2).rsplit(") ", 1)[1].split()
        self.assertEqual(rest[0], "S")
        self.assertEqual(rest[3], "0")   # original field 6, NOT flags
        self.assertEqual(rest[6], "69238848")
        self.assertEqual(rest[19], "2")

    def test_session_field_cannot_grant_kernel_thread_exemption(self):
        directory = self.process(target=None)
        head, tail = proc_stat(42, flags=0).rsplit(") ", 1)
        fields = tail.split()
        fields[3] = "2097152"  # original field 6=session; NOT field 9=flags
        (directory / "stat").write_bytes((head + ") " + " ".join(fields) + "\n").encode("ascii"))
        result = self.scan('return 1')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Cannot inspect user process executable: PID=42", result.stderr)

    def test_readable_non_lp2_user_and_unsigned_high_flags(self):
        self.process(flags=0x80000000)
        result = self.scan()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_user_missing_executable_is_not_a_kernel_thread(self):
        # Even a kernel-looking name does not replace the PF_KTHREAD check.
        self.process(target=None, comm="migration/0")
        result = self.scan('return 1')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Cannot inspect user process executable: PID=42", result.stderr)

    def test_unreadable_user_executable_even_when_entry_exists_refused(self):
        self.process()
        result = self.scan('printf "Permission denied\\n" >&2; return 1')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Cannot inspect user process executable: PID=42", result.stderr)

    def test_kernel_pid_reuse_cannot_bypass_user_executable_check(self):
        directory = self.process(flags=0x00200000, target=None)
        (directory / "replacement").write_bytes(proc_stat(42, flags=0, ticks=101).encode("ascii"))
        result = self.scan(prefix='''cat() {
            command cat "$@" || return 1
            case "$1" in */stat)
                if [ -f "${1%/stat}/replacement" ]; then
                    command mv "${1%/stat}/replacement" "${1%/stat}/stat" || return 1
                fi ;;
            esac
            return 0
        }
''')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Process identity changed", result.stderr)

    def test_process_exits_before_initial_stat_refused(self):
        (self.proc / "42").mkdir()
        result = self.scan()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Cannot inspect process stat: PID=42", result.stderr)

    def test_exact_lp2_and_deleted_lp2_rejected(self):
        directory = self.process()
        for target in ("/tmp/lp2_m5_rtsp_server", "/var/volatile/tmp/lp2_m5_rtsp_server",
                       "/var/volatile/tmp/lp2_m5_rtsp_server (deleted)"):
            with self.subTest(target=target):
                (directory / "exe").write_bytes((target + "\n").encode("ascii"))
                result = self.scan()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("still running", result.stderr)

    def test_persistent_lp2_release_executable_refused(self):
        self.process()
        result = self.scan('printf "%s\\n" "$ROOT/releases/v1/bin/lp2_rtsp_server"')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("still running", result.stderr)

    def test_exit_race_after_readlink_refused(self):
        self.process()
        result = self.scan('cat "$1"; command mv "${1%/exe}/stat" "${1%/exe}/stat.exited"')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("User process disappeared or became unreadable", result.stderr)

    def test_pid_reuse_after_readlink_refused(self):
        directory = self.process()
        (directory / "replacement").write_bytes(proc_stat(42, ticks=101).encode("ascii"))
        result = self.scan('cat "$1"; command cp "${1%/exe}/replacement" "${1%/exe}/stat"')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Process identity changed", result.stderr)

    def test_unreadable_or_malformed_stat_refused(self):
        directory = self.process()
        for contents in (b"", b"42 (bad) S\n", proc_stat(43).encode("ascii"),
                         proc_stat(42, flags=4294967296).encode("ascii"),
                         proc_stat(42).replace(" (strange ) task ( name)", " not-parenthesized").encode("ascii")):
            (directory / "stat").write_bytes(contents)
            result = self.scan()
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Cannot inspect process stat: PID=42", result.stderr)


class BoardTests(unittest.TestCase):
    def setUp(self):
        self.shell = posix_shell()
        self.temp = local_fixture_directory("lp2-release-test-")
        # addCleanup also runs if preflight or another part of setUp fails.
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name).resolve()
        check_posix_fixture(self.shell, self.directory)
        self.board = self.directory / "board"
        self.proc = self.directory / "proc"
        self.proc.mkdir()
        self.source = (SCRIPTS / "board_release.sh").read_text().replace(
            "ROOT=/opt/lp2-media", 'ROOT="$PWD/board"').replace(
            "PROC=/proc", 'PROC="$PWD/proc"')

    def run_board(self, *args, prefix=""):
        return subprocess.run([self.shell, "-s", "--"] + list(args),
                              input="PATH=/usr/bin:/bin:$PATH\nsync() { :; }\n" + prefix + self.source,
                              text=True, encoding="utf-8", capture_output=True,
                              cwd=str(self.directory), timeout=15)

    def ok(self, *args):
        result = self.run_board(*args)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def fixture(self, ver, suffix=b""):
        directory = self.board / "staging" / ver
        directory.mkdir()
        (directory / "bin").mkdir()
        binary = arm_metadata_fixture() + suffix
        (directory / "bin/lp2_rtsp_server").write_bytes(binary)
        sha = hashlib.sha256(binary).hexdigest()
        (directory / "manifest").write_bytes((
            "format=lp2-release-v1\nversion={}\nbinary_sha256={}\norigin=fresh-poky-release-build\n"
            "baseline_sha256={}\nbaseline_hash_equal={}\nhardware_gate=PENDING\n".format(
                ver, sha, package.BASELINE, "yes" if sha == package.BASELINE else "no")).encode("ascii"))
        (directory / "run-args.txt").write_bytes((package.ARGS + "\n").encode("ascii"))
        for name in ("build-info.txt", "source-sha256.json", "elf.json"):
            (directory / name).write_bytes(b"OFFLINE TEST FIXTURE ONLY\n")
        names = ["bin/lp2_rtsp_server", "manifest", "run-args.txt", "build-info.txt", "source-sha256.json", "elf.json"]
        (directory / "SHA256SUMS").write_bytes("".join(package.digest(directory / name) + "  " + name + "\n" for name in names).encode("ascii"))
        return directory, sha

    def test_init_dry_run_and_unowned_directory_protection(self):
        self.ok("init", "--dry-run")
        self.assertFalse(self.board.exists())
        self.board.mkdir()
        (self.board / "unrelated-service").write_text("preserve")
        self.assertNotEqual(self.run_board("init").returncode, 0)
        self.assertEqual((self.board / "unrelated-service").read_text(), "preserve")

    def test_install_switch_approval_and_rollback(self):
        self.ok("init")
        _, sha1 = self.fixture("v1")
        self.ok("install", "v1", "--dry-run")
        self.assertFalse((self.board / "releases/v1").exists())
        self.ok("install", "v1")
        self.assertFalse((self.board / "current").exists())
        self.assertNotEqual(self.run_board("switch", "v1", "0" * 64).returncode, 0)
        self.ok("switch", "v1", sha1, "--dry-run")
        self.assertFalse((self.board / "previous").exists())
        self.ok("switch", "v1", sha1)
        _, sha2 = self.fixture("v2", b"second offline fixture")
        self.ok("install", "v2")
        self.ok("switch", "v2", sha2)
        self.assertEqual((self.board / "previous").read_text().strip(), "v1")
        self.ok("rollback", "--dry-run")
        self.ok("rollback")
        self.assertEqual((self.board / "previous").read_text().strip(), "v2")
        self.ok("verify", "v1")
        self.assertNotEqual(self.run_board("install", "v1").returncode, 0)

    def test_tamper_missing_files_and_unsafe_checksum_paths(self):
        self.ok("init")
        directory, _ = self.fixture("v1")
        (directory / "bin/lp2_rtsp_server").write_bytes(b"damaged")
        self.assertNotEqual(self.run_board("install", "v1").returncode, 0)
        self.assertFalse((self.board / "releases/v1").exists())
        (directory / "SHA256SUMS").write_text("0" * 64 + "  /etc/passwd\n", encoding="ascii")
        result = self.run_board("verify-staged", "v1")
        self.assertIn("Unsafe checksum", result.stderr)
        (directory / "manifest").unlink()
        self.assertNotEqual(self.run_board("install", "v1").returncode, 0)

    def test_upload_review_never_connects(self):
        self.ok("init")
        directory, _ = self.fixture("v1")
        # Reuse the complete offline package under an isolated host root.
        host = self.directory / "host"
        (host / "releases").mkdir(parents=True)
        shutil.copytree(directory, host / "releases/v1")
        with patch.object(transfer, "ROOT", host), patch.object(sys, "argv", ["transfer", "v1"]), \
                patch.object(transfer.shutil, "which", return_value="fixture"), \
                patch.object(transfer.subprocess, "run") as network, redirect_stdout(io.StringIO()):
            transfer.main()
        network.assert_not_called()
        package.verify_package(host / "releases/v1", "v1")
        (host / "releases/v1/bin/lp2_rtsp_server").write_bytes(b"corrupted")
        with self.assertRaises(ValueError):
            package.verify_package(host / "releases/v1", "v1")

    def test_active_exact_lp2_process_blocks_switch(self):
        self.ok("init")
        _, sha = self.fixture("v1")
        self.ok("install", "v1")
        (self.proc / "42").mkdir()
        (self.proc / "42/stat").write_bytes(proc_stat(42).encode("ascii"))
        prefix = 'ln -s /var/volatile/tmp/lp2_m5_rtsp_server "$PWD/proc/42/exe"\n'
        result = self.run_board("switch", "v1", sha, prefix=prefix)
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("still running", result.stderr)
        self.assertFalse((self.board / "current").exists())

    def test_active_lp2_blocks_rollback(self):
        self.ok("init")
        _, sha = self.fixture("v1")
        self.ok("install", "v1")
        (self.board / "verified/v1").write_bytes((sha + "\n").encode("ascii"))
        (self.board / "previous").write_bytes(b"v1\n")
        (self.proc / "42").mkdir()
        (self.proc / "42/stat").write_bytes(proc_stat(42).encode("ascii"))
        for options in (("--dry-run",), ()):
            prefix = '' if not options else 'ln -s "$PWD/board/releases/v1/bin/lp2_rtsp_server" "$PWD/proc/42/exe"\n'
            result = self.run_board("rollback", *options, prefix=prefix)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("still running", result.stderr)
            self.assertFalse((self.board / "current").exists())

    def test_failed_atomic_rename_preserves_current(self):
        self.ok("init")
        _, sha1 = self.fixture("v1")
        self.ok("install", "v1")
        # Seed an already approved previous version in the offline fixture.
        (self.board / "verified/v1").write_bytes((sha1 + "\n").encode("ascii"))
        seeded = self.run_board("verify", "v1", prefix='ln -s releases/v1 "$PWD/board/current"\n')
        self.assertEqual(seeded.returncode, 0, seeded.stderr)
        _, sha2 = self.fixture("v2", b"second")
        self.ok("install", "v2")
        # Fail only current promotion, after previous and receipt writes.
        result = self.run_board("switch", "v2", sha2, prefix='''mv() {
            case "$*" in *current.next*) return 42 ;; esac
            command mv "$@"
        }
''')
        self.assertNotEqual(result.returncode, 0)
        # Inspect the actual POSIX link: failed promotion must preserve v1.
        result = self.run_board("verify", "v1", prefix='''[ "$(readlink "$PWD/board/current")" = releases/v1 ] || exit 99
''')
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_switch_dry_run_and_wrong_approval_do_not_activate(self):
        self.ok("init")
        _, sha = self.fixture("v1")
        self.ok("install", "v1", "--dry-run")
        self.assertFalse((self.board / "releases/v1").exists())
        self.ok("install", "v1")
        self.assertNotEqual(self.run_board("switch", "v1", "0" * 64).returncode, 0)
        self.ok("switch", "v1", sha, "--dry-run")
        self.assertFalse((self.board / "current").exists())
        self.assertFalse((self.board / "previous").exists())

    def test_unknown_current_and_traversal_rejected(self):
        self.ok("init")
        _, sha = self.fixture("v1")
        self.ok("install", "v1")
        for ver in ("../outside", "/tmp/other", "-bad"):
            self.assertNotEqual(self.run_board("switch", ver, sha).returncode, 0)
        self.assertNotEqual(self.run_board("rollback").returncode, 0)
        (self.board / "current").write_text("unrelated")
        self.assertNotEqual(self.run_board("switch", "v1", sha).returncode, 0)


if __name__ == "__main__":
    # Fail clearly once before unittest instead of reporting eight misleading
    # release-tool failures when the host cannot provide POSIX fixtures.
    try:
        shell = posix_shell()
        with local_fixture_directory("lp2-release-preflight-") as temp:
            check_posix_fixture(shell, Path(temp).resolve())
        print("Fixture environment: native POSIX checks passed on local /tmp; project stays unchanged", flush=True)
    except FixtureEnvironmentError as error:
        print(str(error), file=sys.stderr)
        sys.exit(2)
    unittest.main()
