"""Offline SysV service tests. Never SSH, execute media, or use real /etc."""
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import signal
import time
import re
import shlex
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[1]
PROJECT = SCRIPTS.parents[1]

BOARD_INIT_SHA = "29e0d4d2879d4c268f007e420fba85c5f86170a172d8f5beb6f6f217bef6ab6f"
BOARD_UNLOCK = '''diagnostic_unlock() {
    [ "${diag_lock_owned:-0}" = 1 ] || return 0
    diagnostic_lock_valid || {
        printf 'LP2 DIAGNOSTIC: lock instance changed; retained\\n' >&2; return 1;
    }
    rm owner || return 1
    [ ! -L "$diag_lock" ] && [ "$(stat -c '%d:%i' "$diag_lock")" = "$diag_token" ] || return 1
    rmdir "$diag_lock"
}
'''


def board_29e0_source():
    """Reconstruct exact frozen board bytes, not an invented simplified fixture."""
    source = (SCRIPTS / "lp2-media").read_text(encoding="utf-8")
    source = re.sub(r"diagnostic_unlock\(\) \{.*?\n\}\n(?=diagnostic_complete\(\))", BOARD_UNLOCK.replace("\\", "\\\\"), source, flags=re.S)
    source = re.sub(r"diagnostic_complete\(\) \{.*?\n\}\n(?=diagnostic\(\))", "", source, flags=re.S)
    source = source.replace("trap 'diagnostic_complete $?' EXIT", "trap 'diagnostic_unlock || :' EXIT")
    for number, sig in ((130, "INT"), (143, "TERM"), (129, "HUP")):
        source = source.replace("trap 'diagnostic_complete {}' {}".format(number, sig), "trap 'exit {}' {}".format(number, sig))
    source = source.replace("|| diagnostic_complete 1", "|| return 1").replace("    diagnostic_complete 0\n", "")
    if hashlib.sha256(source.encode("utf-8")).hexdigest() != BOARD_INIT_SHA:
        raise AssertionError("29e0 regression fixture bytes no longer match frozen board SHA")
    return source


def stat_line(pid=42, ticks=100, flags=0):
    fields = {3: "S", 4: "2", 8: "-1", 9: str(flags), 20: "1", 22: str(ticks)}
    return "{} (name ) with ( spaces) {}\n".format(pid, " ".join(fields.get(n, "0") for n in range(3, 23)))


def checked_external_mv(directory, candidate=None):
    """Select real external -T mv, never drop the flag or emulate rename.

    BusyBox ash standalone/prefer-applet builds can ignore PATH for mv, even
    with `command mv`. An absolute pathname bypasses that applet selection.
    """
    candidate = candidate or os.environ.get("LP2_TEST_MV", "/usr/bin/mv")
    if not os.path.isabs(candidate) or not os.path.isfile(candidate) or not os.access(candidate, os.X_OK):
        raise RuntimeError("TEST ENVIRONMENT ERROR: LP2_TEST_MV must name an executable absolute path supporting mv -T")
    # Keep argv[0]/applet basename: resolving a mv symlink to busybox would
    # accidentally invoke the BusyBox dispatcher instead of its mv applet.
    backend = os.path.abspath(candidate)
    help_result = subprocess.run([backend, "--help"], capture_output=True, timeout=10)
    if help_result.returncode != 0 or b"-T" not in help_result.stdout + help_result.stderr:
        raise RuntimeError("TEST ENVIRONMENT ERROR: selected external mv lacks -T: " + backend)
    with tempfile.TemporaryDirectory(prefix="mv-preflight-", dir=str(directory)) as tmp:
        probe = Path(tmp)
        source = probe / "source"
        target = probe / "target"
        source.write_bytes(b"new payload\n")
        target.write_bytes(b"old payload\n")
        source_inode = source.stat().st_ino
        result = subprocess.run([backend, "-T", str(source), str(target)], capture_output=True, timeout=10)
        if result.returncode != 0 or source.exists() or target.read_bytes() != b"new payload\n" or target.stat().st_ino != source_inode:
            raise RuntimeError("TEST ENVIRONMENT ERROR: mv -T did not preserve same-filesystem rename semantics: " + backend)
        source.write_bytes(b"must not move into directory\n")
        directory_target = probe / "directory-target"
        directory_target.mkdir()
        result = subprocess.run([backend, "-T", str(source), str(directory_target)], capture_output=True, timeout=10)
        if result.returncode == 0 or not source.is_file() or source.read_bytes() != b"must not move into directory\n" or list(directory_target.iterdir()):
            raise RuntimeError("TEST ENVIRONMENT ERROR: mv -T directory-target rejection changed: " + backend)
    return backend


class LogicTests(unittest.TestCase):
    def setUp(self):
        self.shell = os.environ.get("LP2_TEST_SHELL") or shutil.which("sh")
        if not self.shell:
            raise RuntimeError("TEST ENVIRONMENT ERROR: POSIX shell required")
        self.temp = tempfile.TemporaryDirectory(prefix="lp2-sysv-test-", dir="/tmp" if os.name == "posix" else str(PROJECT))
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.runtime = self.directory / "runtime"
        self.runtime.mkdir(mode=0o700)
        (self.runtime / ".lp2-owned").write_bytes(b"LP2-M7.3-RUNTIME-V1\n")
        self.proc = self.directory / "proc"
        self.proc.mkdir()
        (self.directory / "start.stat").write_bytes(stat_line().encode("ascii"))
        self.source = (SCRIPTS / "lp2-media").read_text().rsplit('\ncase "$action" in\n', 1)[0]
        # Keep the fixed board executable namespace as TEXT only. All functions
        # that open release files/launch a process are stubbed below; runtime
        # and proc files remain in the unique fixture. This also avoids MSYS's
        # Windows workspace spaces altering the board's three-field PID format.
        self.source = self.source.replace(
            "RUNTIME=/var/volatile/tmp/lp2-media-service", 'RUNTIME="$PWD/runtime"').replace(
            "PROC=/proc", 'PROC="$PWD/proc"').replace(
            "diag_base=/var/volatile/tmp/lp2-media-diagnostics", 'diag_base="$PWD/diag-volatile"')

    def record(self, pid=42, ticks=100, live_ticks=None, target=None):
        (self.runtime / "server.pid").write_bytes((str(pid) + "\n").encode("ascii"))
        prefix = "/opt/lp2-media/releases/v1/bin/lp2_rtsp_server"
        (self.runtime / "server.identity").write_bytes("{} {} {}\n".format(pid, ticks, prefix).encode("utf-8"))
        if live_ticks is not None:
            process = self.proc / str(pid)
            process.mkdir()
            (process / "stat").write_bytes(stat_line(pid, live_ticks).encode("ascii"))
            (process / "exe").write_bytes(((prefix if target is None else target) + "\n").encode("utf-8"))

    def run_shell(self, command, prefix="", stop_body=None):
        if stop_body is None:
            stop_body = 'rm "$PROC/$pid/exe" "$PROC/$pid/stat"; rmdir "$PROC/$pid"'
        stubs = '''
id() { printf '0\\n'; }
stat() { case "$2" in '%u:%a') printf '0:700\\n' ;; '%u') printf '0\\n' ;; *) command stat "$@" ;; esac; }
readlink() { case "$1" in "$PROC"/*/exe) cat "$1" ;; *) command readlink "$@" ;; esac; }
proc_visible() { return 0; } # isolated fake procfs, never inspect host processes
kill() { [ "$1" = -0 ] && [ -d "$PROC/$2" ]; }
diagnostic_writer_identity() { diag_writer_pid=123; diag_writer_ticks=100; diag_writer_boot=aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee; }
sleep() { :; }
release_ready() { executable="$ROOT/releases/v1/bin/lp2_rtsp_server"; arguments="$EXPECTED_ARGS"; }
camera_ready() { return 0; }
ssd_mock() {
  printf '%s\\n' "$*" >> "$PWD/ssd.calls"
  case "$1" in
    --start)
      printf '42\\n' > "$PIDFILE"
      mkdir "$PROC/42"
      cp "$PWD/start.stat" "$PROC/42/stat"
      printf '%s\\n' "$executable" > "$PROC/42/exe" ;;
    --stop) ''' + stop_body + ''' ;;
  esac
}
SSD=ssd_mock
CAMERA_WAIT=2
START_WAIT=2
STOP_WAIT=2
'''
        # Send exact LF bytes. Windows text-mode pipes otherwise inject CRLF,
        # which Bash may tolerate but dash correctly rejects (set -eu\r).
        script = "PATH=/usr/bin:/bin:$PATH\n" + self.source + stubs + prefix + "\n" + command
        result = subprocess.run([self.shell, "-s"], input=script.encode("utf-8"),
                                cwd=str(self.directory), capture_output=True, timeout=15)
        result.stdout = result.stdout.decode("utf-8")
        result.stderr = result.stderr.decode("utf-8")
        return result

    def test_start_and_duplicate_do_not_launch_twice(self):
        first = self.run_shell("start_service")
        self.assertEqual(first.returncode, 0, first.stderr)
        second = self.run_shell("start_service")
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(len((self.directory / "ssd.calls").read_text(encoding="utf-8").splitlines()), 1)
        self.assertIn("--device /dev/video2", (self.directory / "ssd.calls").read_text(encoding="utf-8"))

    def test_stale_pid_cleared_without_signalling_reused_process(self):
        self.record(live_ticks=101, target="/sbin/another-service")
        result = self.run_shell("stop_service")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.directory / "ssd.calls").exists())
        self.assertTrue((self.proc / "42/stat").exists())
        self.assertFalse((self.runtime / "server.pid").exists())

    def test_same_ticks_wrong_exe_is_unknown_and_never_signalled(self):
        self.record(live_ticks=100, target="/sbin/another-service")
        result = self.run_shell("stop_service")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("refusing to signal", result.stderr)
        self.assertFalse((self.directory / "ssd.calls").exists())

    def test_term_success_cleans_records(self):
        self.record(live_ticks=100)
        result = self.run_shell("stop_service")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--stop --signal TERM", (self.directory / "ssd.calls").read_text(encoding="utf-8"))
        self.assertFalse((self.runtime / "server.identity").exists())

    def test_stop_timeout_keeps_identity_and_prevents_restart(self):
        self.record(live_ticks=100)
        result = self.run_shell("stop_service\nstart_service", stop_body=":")
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue((self.runtime / "server.identity").exists())
        calls = (self.directory / "ssd.calls").read_text(encoding="utf-8")
        self.assertNotIn("--start", calls)
        self.assertNotIn("KILL", calls)

    def test_camera_timeout_is_bounded_and_no_launch(self):
        result = self.run_shell("start_service", prefix="camera_ready() { return 1; }\n")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Camera readiness timeout", result.stdout)
        self.assertFalse((self.directory / "ssd.calls").exists())

    def test_unmanaged_lp2_prevents_duplicate(self):
        process = self.proc / "55"
        process.mkdir()
        (process / "stat").write_bytes(stat_line(55).encode("ascii"))
        (process / "exe").write_bytes(b"/var/volatile/tmp/lp2_m5_rtsp_server\n")
        result = self.run_shell("start_service")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Unmanaged LP2", result.stderr)
        self.assertFalse((self.directory / "ssd.calls").exists())

    def test_real_kernel_flags_skip_exe_but_user_missing_exe_refused(self):
        process = self.proc / "10"
        process.mkdir()
        (process / "stat").write_bytes(b"10 (migration/0) S 2 0 0 0 -1 69238848 0 0 0 0 0 0 0 0 -100 0 1 0 2\n")
        result = self.run_shell("no_unmanaged_lp2")
        self.assertEqual(result.returncode, 0, result.stderr)
        (process / "stat").write_bytes(stat_line(10).encode("ascii"))
        result = self.run_shell("no_unmanaged_lp2")
        self.assertNotEqual(result.returncode, 0)

    def test_incomplete_pid_file_refuses_start(self):
        (self.runtime / "server.pid").write_bytes(b"42\n")
        result = self.run_shell("start_service")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.directory / "ssd.calls").exists())

    def test_log_rotation_is_bounded(self):
        (self.runtime / "events.log").write_bytes(b"x" * 32768)
        result = self.run_shell("event 'bounded test'")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.runtime / "events.log.1").stat().st_size, 32768)
        self.assertLess((self.runtime / "events.log").stat().st_size, 512)

    def test_status_identity_check_is_read_only(self):
        self.record(live_ticks=100)
        before = {p.relative_to(self.directory): p.read_bytes() for p in self.directory.rglob("*") if p.is_file()}
        result = self.run_shell('state_code; printf "state=%s\\n" "$state"')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("state=0", result.stdout)
        after = {p.relative_to(self.directory): p.read_bytes() for p in self.directory.rglob("*") if p.is_file()}
        self.assertEqual(before, after)

    def test_pid_changes_during_exe_read_no_signal(self):
        self.record(live_ticks=100)
        (self.directory / "replacement.stat").write_bytes(stat_line(ticks=101).encode("ascii"))
        result = self.run_shell("stop_service", prefix='''readlink() {
            case "$1" in "$PROC/42/exe")
                cat "$1"
                cp "$PWD/replacement.stat" "$PROC/42/stat" ;;
              *) command readlink "$@" ;;
            esac
        }
''')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.directory / "ssd.calls").exists())

    def test_unknown_runtime_owner_refused(self):
        (self.runtime / ".lp2-owned").write_bytes(b"somebody-else\n")
        result = self.run_shell("runtime_owned")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("refusing takeover", result.stderr)

    def diagnostic_prefix(self):
        root = self.directory / "root"
        root.mkdir()
        (root / ".lp2-owned").write_bytes(b"LP2-M7-RELEASE-V1\n")
        return '''ROOT="$PWD/root"
trap 'finish $?' EXIT
diagnostic entry pending || exit 99
'''

    def snapshot(self, name="last-exit.txt"):
        return (self.directory / "root/service-diagnostics" / name).read_text(encoding="utf-8")

    def test_boot_proc_scan_failure_persists_pid_phase_exit(self):
        process = self.proc / "55"
        process.mkdir()
        (process / "stat").write_bytes(stat_line(55).encode("ascii"))
        result = self.run_shell("start_service", prefix=self.diagnostic_prefix())
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.runtime / "events.log").exists())
        text = self.snapshot("last-failure.txt")
        self.assertIn("stage=proc_scan", text)
        self.assertIn("scan_pid=55", text)
        self.assertIn("scan_phase=readlink", text)
        self.assertIn("exit_code=1", text)
        self.assertIn("Cannot inspect user executable: PID=55", text)
        self.assertFalse((self.directory / "ssd.calls").exists())

    def test_present_pid_missing_stat_is_logged_not_ignored(self):
        (self.proc / "55").mkdir() # present at enumeration, stat has vanished
        result = self.run_shell("start_service", prefix=self.diagnostic_prefix())
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("scan_phase=stat_before", self.snapshot())
        self.assertIn("Cannot inspect process stat: PID=55", self.snapshot())
        self.assertFalse((self.directory / "ssd.calls").exists())

    def scan_process(self, pid, ticks=100):
        process = self.proc / str(pid)
        process.mkdir()
        (process / "stat").write_bytes(stat_line(pid, ticks).encode("ascii"))
        (process / "exe").write_bytes(b"/sbin/unrelated-service\n")

    def vanishing_reader(self):
        # Removal happens inside the shell AFTER directory enumeration and
        # inode acquisition, at the actual stat read. No static missing fixture.
        return '''cat() {
 case "$1" in "$PROC"/*/stat)
   race_dir=${1%/stat}
   command rm "$race_dir/stat" "$race_dir/exe"
   command rmdir "$race_dir"
   return 1 ;;
 *) command cat "$@" ;; esac
}
'''

    def test_exit_after_enumeration_requires_clean_second_sweep(self):
        self.scan_process(715)
        result = self.run_shell('no_unmanaged_lp2; printf "pass=%s\\n" "$scan_pass"',
                                prefix=self.vanishing_reader())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("pass=2", result.stdout)
        self.assertFalse((self.proc / "715").exists())

    def test_multiple_transient_processes_converge(self):
        for pid in (715, 716, 717):
            self.scan_process(pid)
        result = self.run_shell('no_unmanaged_lp2; printf "pass=%s\\n" "$scan_pass"',
                                prefix=self.vanishing_reader())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("pass=2", result.stdout)
        self.assertEqual(list(self.proc.iterdir()), [])

    def churn_prefix(self, last):
        self.scan_process(715)
        for pid in range(716, last + 1):
            (self.directory / (str(pid) + ".stat")).write_bytes(stat_line(pid).encode("ascii"))
        return self.vanishing_reader() + '''next_pid=716
sleep() {
 if [ "$next_pid" -le ''' + str(last) + ''' ]; then
  mkdir "$PROC/$next_pid"
  cp "$PWD/$next_pid.stat" "$PROC/$next_pid/stat"
  printf '/sbin/unrelated-service\\n' > "$PROC/$next_pid/exe"
  next_pid=$((next_pid + 1))
 fi
}
'''

    def test_boot_churn_converges_at_last_allowed_sweep(self):
        result = self.run_shell('no_unmanaged_lp2; printf "pass=%s\\n" "$scan_pass"',
                                prefix=self.churn_prefix(717))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("pass=4", result.stdout)

    def test_retry_limit_fails_with_pid_phase_reason_diagnostic(self):
        prefix = self.churn_prefix(718) + self.diagnostic_prefix()
        result = self.run_shell("no_unmanaged_lp2", prefix=prefix)
        self.assertNotEqual(result.returncode, 0)
        snapshot = self.snapshot()
        for field in ("scan_pid=718", "scan_phase=stat_before", "scan_pass=4",
                      "scan_exit_check=confirmed_absent_twice", "did not converge"):
            self.assertIn(field, snapshot)
        self.assertFalse((self.directory / "ssd.calls").exists())

    def test_pid_reappears_between_sweeps_refused(self):
        self.scan_process(715)
        (self.directory / "replacement.stat").write_bytes(stat_line(715, 101).encode("ascii"))
        prefix = self.vanishing_reader() + '''sleep() {
 mkdir "$PROC/715"
 cp "$PWD/replacement.stat" "$PROC/715/stat"
 printf '/sbin/unrelated-service\\n' > "$PROC/715/exe"
}
'''
        result = self.run_shell("no_unmanaged_lp2", prefix=prefix)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("PID reappeared", result.stderr)

    def test_pid_reuse_during_failed_stat_refused(self):
        self.scan_process(715)
        (self.directory / "replacement.stat").write_bytes(stat_line(715, 101).encode("ascii"))
        prefix = '''cat() {
 case "$1" in "$PROC/715/stat")
   mv "$PROC/715" "$PROC/retired-715"
   mkdir "$PROC/715"
   cp "$PWD/replacement.stat" "$PROC/715/stat"
   printf '/sbin/unrelated-service\\n' > "$PROC/715/exe"
   return 1 ;;
 *) command cat "$@" ;; esac
}
'''
        result = self.run_shell("no_unmanaged_lp2", prefix=prefix)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("exit_check=pid_present", result.stderr)
        self.assertTrue((self.proc / "retired-715").exists())

    def test_same_directory_start_ticks_change_refused(self):
        self.scan_process(715)
        (self.directory / "replacement.stat").write_bytes(stat_line(715, 101).encode("ascii"))
        prefix = '''readlink() {
 cp "$PWD/replacement.stat" "$PROC/715/stat"
 command cat "$1"
}
'''
        result = self.run_shell("no_unmanaged_lp2", prefix=prefix)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("PID reused", result.stderr)

    def test_present_stat_read_error_refused(self):
        self.scan_process(715)
        prefix = '''cat() {
 case "$1" in "$PROC/715/stat") return 1 ;; *) command cat "$@" ;; esac
}
'''
        result = self.run_shell("no_unmanaged_lp2", prefix=prefix)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("exit_check=pid_present", result.stderr)
        self.assertTrue((self.proc / "715/stat").exists())

    def test_uncertain_visibility_never_authorizes_exit_skip(self):
        self.scan_process(715)
        prefix = self.vanishing_reader() + '''proc_visible() {
 [ -d "$PROC/715" ]
}
'''
        result = self.run_shell("no_unmanaged_lp2", prefix=prefix)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("exit_check=proc_visibility_unknown", result.stderr)

    def test_pid_reappears_during_absence_inventory_refused(self):
        self.scan_process(715)
        (self.directory / "replacement.stat").write_bytes(stat_line(715, 101).encode("ascii"))
        prefix = self.vanishing_reader() + '''ls() {
 mkdir "$PROC/715"
 cp "$PWD/replacement.stat" "$PROC/715/stat"
 printf '/sbin/unrelated-service\\n' > "$PROC/715/exe"
 command ls "$@"
}
'''
        result = self.run_shell("no_unmanaged_lp2", prefix=prefix)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("exit_check=pid_reappeared", result.stderr)

    def test_exit_before_directory_token_read_retries(self):
        self.scan_process(715)
        prefix = '''stat() {
 case "$*" in "-c %d:%i $PROC/715")
   command rm "$PROC/715/stat" "$PROC/715/exe"
   command rmdir "$PROC/715"
   return 1 ;;
 *) command stat "$@" ;; esac
}
'''
        result = self.run_shell('no_unmanaged_lp2; printf "pass=%s\\n" "$scan_pass"', prefix=prefix)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("pass=2", result.stdout)

    def test_exit_during_executable_read_retries(self):
        self.scan_process(715)
        prefix = '''readlink() {
 command rm "$PROC/715/stat" "$PROC/715/exe"
 command rmdir "$PROC/715"
 return 1
}
'''
        result = self.run_shell('no_unmanaged_lp2; printf "pass=%s\\n" "$scan_pass"', prefix=prefix)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("pass=2", result.stdout)

    def test_exit_after_second_stat_before_directory_recheck(self):
        self.scan_process(715)
        prefix = '''stat() {
 case "$*" in "-c %d:%i $PROC/715")
   if [ -f "$PWD/token-read" ]; then
     command rm "$PROC/715/stat" "$PROC/715/exe"
     command rmdir "$PROC/715"
     return 1
   fi
   printf 'first\\n' > "$PWD/token-read" ;;
 esac
 command stat "$@"
}
'''
        result = self.run_shell('no_unmanaged_lp2; printf "pass=%s\\n" "$scan_pass"', prefix=prefix)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("pass=2", result.stdout)

    def test_observed_identity_changes_across_sweeps_refused(self):
        self.scan_process(714)
        self.scan_process(715)
        (self.directory / "replacement.stat").write_bytes(stat_line(714, 101).encode("ascii"))
        prefix = self.vanishing_reader().replace('"$PROC"/*/stat)', '"$PROC/715/stat")') + '''sleep() {
 cp "$PWD/replacement.stat" "$PROC/714/stat"
}
'''
        result = self.run_shell("no_unmanaged_lp2", prefix=prefix)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("identity changed across sweeps", result.stderr)

    def test_absence_does_not_override_live_pid_probe(self):
        self.scan_process(715)
        prefix = self.vanishing_reader() + 'kill() { return 0; }\n'
        result = self.run_shell("no_unmanaged_lp2", prefix=prefix)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("exit_check=pid_alive", result.stderr)

    def test_proc_visibility_checks_real_parser_not_mock(self):
        function = "proc_visible() {" + self.source.split("proc_visible() {", 1)[1].split("\nconfirmed_gone()", 1)[0]
        # Relative fake mountpoint has no HGFS/Windows spaces or escape rules.
        for mounts, expected in (
            ("none proc proc rw 0 0\n", 0),
            ("none proc proc rw,hidepid=0 0 0\n", 0),
            ("none proc proc rw,hidepid=2 0 0\n", 1),
            ("none proc tmpfs rw 0 0\n", 1),
            ("none proc proc rw 0 0\nnone proc proc rw 0 0\n", 1),
            ("", 1),
        ):
            with self.subTest(mounts=mounts):
                (self.proc / "mounts").write_bytes(mounts.encode("ascii"))
                result = self.run_shell("proc_visible", prefix=function + '\nPROC=proc\n')
                self.assertEqual(result.returncode, expected, result.stderr)

    def test_prepare_runtime_failure_captures_failure_before_events(self):
        (self.runtime / ".lp2-owned").write_bytes(b"unknown owner\n")
        result = self.run_shell("prepare_runtime", prefix=self.diagnostic_prefix())
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("stage=prepare_runtime", self.snapshot())
        self.assertIn("refusing takeover", self.snapshot())

    def test_tool_failure_captured_before_runtime_preparation(self):
        prefix = self.diagnostic_prefix() + '''SSD="$PWD/absent-ssd"
'''
        result = self.run_shell("check_tools", prefix=prefix)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("stage=check_tools", self.snapshot())
        self.assertIn("start-stop-daemon unavailable", self.snapshot())

    def test_release_check_failure_and_camera_timeout_recorded(self):
        prefix = self.diagnostic_prefix() + '''release_ready() { stage=release_ready; fail 'test missing approval'; }
'''
        result = self.run_shell("start_service", prefix=prefix)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("stage=release_ready", self.snapshot())
        # Next invocation: real test stub of release_ready succeeds; camera fails.
        result = self.run_shell("start_service", prefix='''ROOT="$PWD/root"
trap 'finish $?' EXIT
camera_ready() { return 1; }
''')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("stage=camera_wait", self.snapshot())
        self.assertIn("Camera readiness timeout", self.snapshot())

    def test_unhandled_set_e_exit_retains_original_exit_code(self):
        result = self.run_shell("stage=prepare_runtime; (exit 7)", prefix=self.diagnostic_prefix())
        self.assertEqual(result.returncode, 7)
        self.assertIn("exit_code=7", self.snapshot())
        self.assertIn("Unhandled command failure", self.snapshot())

    def test_diagnostic_snapshot_bound_and_last_failure_survives_success(self):
        prefix = self.diagnostic_prefix()
        result = self.run_shell('reason=$(printf "%05000d" 0); exit 9', prefix=prefix)
        self.assertEqual(result.returncode, 9)
        diag = self.directory / "root/service-diagnostics"
        failed = (diag / "last-failure.txt").read_bytes()
        self.assertLessEqual(len(failed), 2048)
        result = self.run_shell(":", prefix='''ROOT="$PWD/root"
trap 'finish $?' EXIT
diagnostic entry pending
''')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((diag / "last-failure.txt").read_bytes(), failed)
        for name in ("attempt.txt", "last-exit.txt", "last-failure.txt"):
            self.assertLessEqual((diag / name).stat().st_size, 2048)
        self.assertFalse((diag / "snapshot.next").exists())
        self.assertFalse((diag / "write.lock").exists())
        self.assertFalse((self.directory / "diag-volatile/write.lock").exists())

    def test_legacy_persistent_lock_ignored_and_retained(self):
        self.run_shell(":", prefix=self.diagnostic_prefix())
        lock = self.directory / "root/service-diagnostics/write.lock"
        lock.mkdir()
        result = self.run_shell("diagnostic entry pending", prefix='ROOT="$PWD/root"\n')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(lock.is_dir())
        self.assertFalse((self.directory / "diag-volatile/write.lock").exists())

    def test_successful_write_missing_exit_trap_reproduces_board_symptom(self):
        # Fault injection, NOT a claim that this is the board shell's cause.
        prefix = self.diagnostic_prefix()
        original = self.source
        self.source = board_29e0_source().rsplit('\ncase "$action" in\n', 1)[0].replace(
            "RUNTIME=/var/volatile/tmp/lp2-media-service", 'RUNTIME="$PWD/runtime"').replace(
            "PROC=/proc", 'PROC="$PWD/proc"').replace(
            "diag_base=/var/volatile/tmp/lp2-media-diagnostics", 'diag_base="$PWD/diag-volatile"')
        # Initialize without finish() writing again. Then remove the EXIT hook
        # only AFTER the real final rename has successfully committed the file.
        prefix = prefix.split("trap 'finish", 1)[0] + '''mv() { command mv "$@"; trap - EXIT; }
'''
        result = self.run_shell("diagnostic exit 0", prefix=prefix)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("exit_code=0", self.snapshot())
        self.assertTrue((self.directory / "diag-volatile/write.lock/owner").exists())
        self.source = original

    def test_explicit_completion_works_without_exit_hook_twice(self):
        prefix = self.diagnostic_prefix().split("trap 'finish", 1)[0] + '''mv() { command mv "$@"; trap - EXIT; }
'''
        result = self.run_shell("diagnostic entry pending; diagnostic exit 0", prefix=prefix)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("exit_code=0", self.snapshot())
        self.assertFalse((self.directory / "diag-volatile/write.lock").exists())

    def test_rmdir_runs_outside_the_lock_directory(self):
        prefix = self.diagnostic_prefix().split("trap 'finish", 1)[0] + '''rmdir() {
 [ "$PWD" != "$diag_lock" ] || return 1
 command rmdir "$@"
}
'''
        result = self.run_shell("diagnostic exit 0", prefix=prefix)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.directory / "diag-volatile/write.lock").exists())

    def test_unknown_volatile_holder_is_not_removed(self):
        self.run_shell(":", prefix=self.diagnostic_prefix())
        lock = self.directory / "diag-volatile/write.lock"
        lock.mkdir()
        (lock / "owner").write_bytes(b"unknown-holder\n")
        result = self.run_shell("diagnostic entry pending", prefix='ROOT="$PWD/root"\n')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((lock / "owner").read_bytes(), b"unknown-holder\n")

    def test_snapshot_residue_retained_and_new_lock_released(self):
        self.run_shell(":", prefix=self.diagnostic_prefix())
        snapshot = self.directory / "root/service-diagnostics/snapshot.next"
        snapshot.write_bytes(b"unfinished evidence\n")
        result = self.run_shell("diagnostic entry pending", prefix='ROOT="$PWD/root"\n')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(snapshot.read_bytes(), b"unfinished evidence\n")
        self.assertFalse((self.directory / "diag-volatile/write.lock").exists())

    def test_volatile_parent_missing_does_not_mask_service_exit(self):
        prefix = self.diagnostic_prefix()
        self.source = self.source.replace('diag_base="$PWD/diag-volatile"', 'diag_base="$PWD/not-ready/diag-volatile"')
        result = self.run_shell("exit 7", prefix=prefix.replace("diagnostic entry pending || exit 99", "diagnostic entry pending || :"))
        self.assertEqual(result.returncode, 7)
        self.assertIn("DIAGNOSTIC UNAVAILABLE", result.stderr)
        self.assertFalse((self.directory / "not-ready").exists())

    def test_early_diagnostic_independent_of_service_runtime(self):
        (self.runtime / ".lp2-owned").unlink()
        self.runtime.rmdir()
        result = self.run_shell(":", prefix=self.diagnostic_prefix())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.runtime.exists())
        self.assertTrue((self.directory / "diag-volatile/.lp2-owned").exists())

    def test_diagnostic_rename_failure_releases_lock_retains_original_exit(self):
        prefix = self.diagnostic_prefix() + 'mv() { return 1; }\n'
        result = self.run_shell("exit 7", prefix=prefix)
        self.assertEqual(result.returncode, 7)
        self.assertIn("DIAGNOSTIC UNAVAILABLE", result.stderr)
        self.assertFalse((self.directory / "diag-volatile/write.lock").exists())
        self.assertTrue((self.directory / "root/service-diagnostics/snapshot.next").exists())

    def test_diagnostic_unavailable_does_not_mask_lifecycle_error(self):
        root = self.directory / "root"
        root.mkdir()
        (root / ".lp2-owned").write_bytes(b"not LP2\n")
        result = self.run_shell("stage=release_ready; fail 'original refusal'", prefix='''ROOT="$PWD/root"
trap 'finish $?' EXIT
''')
        self.assertEqual(result.returncode, 1)
        self.assertIn("DIAGNOSTIC UNAVAILABLE", result.stderr)
        self.assertIn("original refusal", result.stderr)
        self.assertFalse((root / "service-diagnostics").exists())

    def test_own_action_lock_released_after_recording_exit(self):
        result = self.run_shell("prepare_runtime; stage=proc_scan; fail 'original scan failure'", prefix=self.diagnostic_prefix())
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.runtime / "action.lock").exists())
        self.assertIn("original scan failure", self.snapshot())

    def test_unknown_pid_state_refusal_persisted(self):
        (self.runtime / "server.pid").write_bytes(b"42\n")
        result = self.run_shell("start_service", prefix=self.diagnostic_prefix())
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("stage=pid_state", self.snapshot())
        self.assertIn("Unknown PID identity", self.snapshot())
        self.assertFalse((self.directory / "ssd.calls").exists())

    def test_ssd_failure_and_confirmation_timeout_recorded(self):
        prefix = self.diagnostic_prefix() + 'ssd_mock() { return 5; }\n'
        result = self.run_shell("start_service", prefix=prefix)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("stage=launch_ssd", self.snapshot())
        self.assertIn("launch failed: exit=5", self.snapshot())
        result = self.run_shell("start_service", prefix='''ROOT="$PWD/root"
trap 'finish $?' EXIT
ssd_mock() { return 0; } # background launch returns but no PID is confirmed
''')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("stage=confirm_start", self.snapshot())
        self.assertIn("Startup confirmation timeout", self.snapshot())

    def test_status_dispatch_does_not_create_persistent_diagnostics(self):
        root = self.directory / "root"
        root.mkdir()
        (root / ".lp2-owned").write_bytes(b"LP2-M7-RELEASE-V1\n")
        dispatch = (SCRIPTS / "lp2-media").read_text().rsplit('\ncase "$action" in\n', 1)[1]
        result = self.run_shell('case "$action" in\n' + dispatch,
                                prefix='ROOT="$PWD/root"\naction=status\n')
        self.assertEqual(result.returncode, 3, result.stderr)
        self.assertFalse((root / "service-diagnostics").exists())


class NativeDiagnosticTests(unittest.TestCase):
    def setUp(self):
        if os.name != "posix":
            raise RuntimeError("TEST ENVIRONMENT ERROR: real /proc/self and signals require native Ubuntu")
        self.shell = os.environ.get("LP2_TEST_SHELL") or shutil.which("sh")
        self.shell_args = shlex.split(os.environ.get("LP2_TEST_SHELL_ARGS", ""))
        self.temp = tempfile.TemporaryDirectory(prefix="lp2-diag-native-", dir="/tmp")
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        root = self.directory / "root"
        root.mkdir(mode=0o700)
        (root / ".lp2-owned").write_bytes(b"LP2-M7-RELEASE-V1\n")
        self.diag = root / "service-diagnostics"
        self.volatile = self.directory / "diag-volatile"
        self.mv_backend = checked_external_mv(self.directory)
        self.source = (SCRIPTS / "lp2-media").read_text().rsplit('\ncase "$action" in\n', 1)[0]
        self.source = self.source.replace("ROOT=/opt/lp2-media", 'ROOT="$PWD/root"').replace(
            "diag_base=/var/volatile/tmp/lp2-media-diagnostics", 'diag_base="$PWD/diag-volatile"')
        self.source += '''
id() { printf '0\\n'; }
stat() { case "$2" in '%u:%a') printf '0:700\\n' ;; '%u') printf '0\\n' ;; *) command stat "$@" ;; esac; }
''' + '\nfixture_mv() { ' + shlex.quote(self.mv_backend) + ' "$@"; }\nmv() { fixture_mv "$@"; }\n'
        print("diagnostic fixture: shell={} args={} external_mv={}".format(
            self.shell, self.shell_args, self.mv_backend), flush=True)
        result = self.invoke()
        self.assertEqual(result.returncode, 0, result.stderr)

    def invoke(self, body="diagnostic entry pending\n"):
        return subprocess.run([self.shell] + self.shell_args + ["-s"], input=self.source + '\n' + body,
                              cwd=str(self.directory), text=True, capture_output=True, timeout=10)

    def blocked_writer(self):
        # Real child shell, blocked inside mv() after acquiring the lock.
        suffix = '''ready="$PWD/ready"
release="$PWD/release"
mv() {
 printf 'ready\\n' > "$ready"
 while [ ! -f "$release" ]; do sleep 0.05; done
 fixture_mv "$@"
}
diagnostic entry pending
printf 'writer returned\\n'
'''
        child = subprocess.Popen([self.shell] + self.shell_args + ["-s"], cwd=str(self.directory), text=True,
                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        child.stdin.write(self.source + suffix)
        child.stdin.close()
        child.stdin = None
        def cleanup():
            (self.directory / "release").touch()
            if child.poll() is None:
                child.communicate(timeout=10)
        self.addCleanup(cleanup)
        deadline = time.monotonic() + 5
        while not (self.directory / "ready").exists():
            if child.poll() is not None or time.monotonic() > deadline:
                self.fail("writer did not reach lock-held checkpoint")
            time.sleep(0.02)
        owner = (self.volatile / "write.lock/owner").read_text().split()
        self.assertEqual(len(owner), 4)
        writer_pid = int(owner[1])
        self.assertNotEqual(writer_pid, child.pid, "must not record parent POSIX $$")
        raw = Path("/proc/{}/stat".format(writer_pid)).read_text()
        rest = raw.rsplit(") ", 1)[1].split()
        self.assertEqual(rest[19], owner[2])
        self.assertEqual(int(rest[1]), child.pid, "signal only verified fixture child")
        return child, writer_pid

    def interrupted(self, sig):
        child, writer_pid = self.blocked_writer()
        os.kill(writer_pid, sig)
        child.communicate(timeout=10)
        self.assertNotEqual(child.returncode, 0)
        self.assertFalse((self.volatile / "write.lock").exists())
        self.assertTrue((self.diag / "snapshot.next").exists())

    def test_sigterm_releases_lock_without_discarding_transaction(self):
        self.interrupted(signal.SIGTERM)

    def test_sighup_releases_lock_without_discarding_transaction(self):
        self.interrupted(signal.SIGHUP)

    def test_sigint_releases_lock_without_discarding_transaction(self):
        self.interrupted(signal.SIGINT)

    def test_two_normal_writes_and_parent_exit_trap_cleanup(self):
        for body in (
            "diagnostic entry pending; diagnostic exit 0\n",
            "trap 'finish $?' EXIT; diagnostic entry pending; :\n",
        ):
            result = self.invoke(body)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse((self.volatile / "write.lock").exists())
            self.assertFalse((self.volatile / "write.lock/owner").exists())
            self.assertIn("exit_code=0", (self.diag / "last-exit.txt").read_text())

    def test_frozen_board_completion_observed_not_assumed(self):
        # Observe the exact old program under the actual selected Linux shell.
        # Modern dash/ash may NOT reproduce the board's failure: report that,
        # rather than forcing a PASS by pretending a trap fault is native.
        current = self.source
        legacy = board_29e0_source().rsplit('\ncase "$action" in\n', 1)[0].replace(
            "ROOT=/opt/lp2-media", 'ROOT="$PWD/root"').replace(
            "diag_base=/var/volatile/tmp/lp2-media-diagnostics", 'diag_base="$PWD/diag-volatile"')
        self.source = legacy + current[current.index("\nid() {"):]
        try:
            result = self.invoke("trap 'finish $?' EXIT; :\n")
            complete = (self.diag / "last-exit.txt").exists()
            leaked = (self.volatile / "write.lock/owner").exists()
            print("29e0 actual-shell observation: shell={} args={} external_mv={} rc={} last_exit={} owner_retained={}".format(
                self.shell, self.shell_args, self.mv_backend, result.returncode, complete, leaked), flush=True)
            # Successful file writing must really have occurred. A retained
            # owner distinguishes the board symptom from ordinary write failure.
            self.assertTrue(complete, result.stderr)
        finally:
            self.source = current

    def test_sigkill_retains_lock_and_reboot_only_clears_volatile(self):
        child, writer_pid = self.blocked_writer()
        os.kill(writer_pid, signal.SIGKILL)
        child.communicate(timeout=10)
        self.assertTrue((self.volatile / "write.lock/owner").exists())
        self.assertNotEqual(self.invoke().returncode, 0) # same boot: no reclaim
        # Simulate tmpfs reset by archiving the unique fixture, NOT /var/volatile.
        self.volatile.rename(self.directory / "previous-boot-volatile")
        self.assertNotEqual(self.invoke().returncode, 0) # persistent next remains
        self.assertFalse((self.volatile / "write.lock").exists())
        # Explicit test-only evidence archival; never automatic production repair.
        (self.diag / "snapshot.next").rename(self.diag / "operator-archived-next")
        self.assertEqual(self.invoke().returncode, 0)
        self.assertTrue((self.diag / "operator-archived-next").exists())

    def test_two_writers_do_not_share_lock(self):
        child, _ = self.blocked_writer()
        owner = (self.volatile / "write.lock/owner").read_bytes()
        pending = (self.diag / "snapshot.next").read_bytes()
        self.assertNotEqual(self.invoke().returncode, 0)
        self.assertEqual(owner, (self.volatile / "write.lock/owner").read_bytes())
        self.assertEqual(pending, (self.diag / "snapshot.next").read_bytes())
        (self.directory / "release").touch()
        child.communicate(timeout=10)
        self.assertEqual(child.returncode, 0)
        self.assertFalse((self.volatile / "write.lock").exists())

    def test_replaced_directory_never_removed_by_old_writer(self):
        child, _ = self.blocked_writer()
        lock = self.volatile / "write.lock"
        lock.rename(self.volatile / "retired-instance")
        lock.mkdir(mode=0o700)
        (lock / "owner").write_bytes(b"replacement owner\n")
        (self.directory / "release").touch()
        _, stderr = child.communicate(timeout=10)
        self.assertIn("lock instance changed", stderr)
        self.assertEqual((lock / "owner").read_bytes(), b"replacement owner\n")
        self.assertTrue((self.volatile / "retired-instance/owner").exists())


class NativeInstallTests(unittest.TestCase):
    def setUp(self):
        if os.name != "posix":
            raise RuntimeError("TEST ENVIRONMENT ERROR: full service install/rename tests require native Ubuntu, not MSYS")
        self.shell = shutil.which("sh")
        self.temp = tempfile.TemporaryDirectory(prefix="lp2-sysv-install-", dir="/tmp")
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name).resolve()
        self.root = self.directory / "root"
        self.etc = self.directory / "etc"
        self.proc = self.directory / "proc"
        for name in ("releases/v1", "service-staging"):
            (self.root / name).mkdir(parents=True)
        (self.root / ".lp2-owned").write_bytes(b"LP2-M7-RELEASE-V1\n")
        (self.root / "current").symlink_to("releases/v1")
        for name in ("init.d", "rc5.d"):
            (self.etc / name).mkdir(parents=True)
        (self.proc / "1").mkdir(parents=True)
        (self.proc / "1/exe").symlink_to("/sbin/init.sysvinit")
        self.staged = self.root / "service-staging/lp2-media"
        self.staged.write_bytes(b"#!/bin/sh\n# LP2-M7.3-SERVICE-V1\ncase $1 in check) exit 0 ;; status) exit 3 ;; *) exit 99 ;; esac\n")
        self.sha = hashlib.sha256(self.staged.read_bytes()).hexdigest()
        self.source = (SCRIPTS / "manage_sysv.sh").read_text().replace(
            "ROOT=/opt/lp2-media", 'ROOT="$PWD/root"').replace("ETC=/etc", 'ETC="$PWD/etc"').replace("PROC=/proc", 'PROC="$PWD/proc"').replace(
            "/var/volatile/tmp/lp2-media-service/", str(self.directory / "fake-runtime") + "/")

    def run_installer(self, *args):
        stub = "PATH=/usr/bin:/bin:$PATH\nstat() { case \"$2\" in '%u:%a') printf '0:700\\n' ;; '%u') printf '0\\n' ;; *) command stat \"$@\" ;; esac; }\nid() { printf '0\\n'; }\n"
        return subprocess.run([self.shell, "-s", "--"] + list(args), input=stub + self.source,
                              cwd=str(self.directory), text=True, encoding="utf-8", capture_output=True, timeout=15)

    def test_install_dry_run_install_and_uninstall_preserve_other_entries(self):
        other = self.etc / "rc5.d/S20other-placeholder"
        other.write_bytes(b"DO NOT TOUCH\n")
        result = self.run_installer("install", self.sha, "--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.etc / "init.d/lp2-media").exists())
        self.assertFalse((self.root / "service-management").exists())
        result = self.run_installer("install", self.sha)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(os.readlink(self.etc / "rc5.d/S91lp2-media"), "../init.d/lp2-media")
        result = self.run_installer("uninstall", "--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.etc / "init.d/lp2-media").exists())
        result = self.run_installer("uninstall")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.etc / "init.d/lp2-media").exists())
        self.assertEqual(other.read_bytes(), b"DO NOT TOUCH\n")
        self.assertTrue((self.root / "releases/v1").exists())

    def test_unknown_name_collision_refused(self):
        (self.etc / "init.d/lp2-media").write_bytes(b"unrelated script\n")
        result = self.run_installer("install", self.sha)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((self.etc / "init.d/lp2-media").read_bytes(), b"unrelated script\n")

    def test_changed_installed_script_never_removed(self):
        self.assertEqual(self.run_installer("install", self.sha).returncode, 0)
        (self.etc / "init.d/lp2-media").write_bytes(b"changed by admin\n")
        result = self.run_installer("uninstall")
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue((self.etc / "rc5.d/S91lp2-media").is_symlink())

    def test_wrong_sha_refused_without_install(self):
        result = self.run_installer("install", "0" * 64)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.etc / "init.d/lp2-media").exists())

    def test_existing_link_to_other_service_refused(self):
        other = self.etc / "init.d/another-service"
        other.write_bytes(b"KEEP\n")
        (self.etc / "rc5.d/S91lp2-media").symlink_to("../init.d/another-service")
        result = self.run_installer("install", self.sha)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(os.readlink(self.etc / "rc5.d/S91lp2-media"), "../init.d/another-service")
        self.assertEqual(other.read_bytes(), b"KEEP\n")

    def test_service_checks_current_hash_approval_and_profile(self):
        release = self.root / "releases/v1"
        (release / "bin").mkdir()
        binary = release / "bin/lp2_rtsp_server"
        binary.write_bytes(b"OFFLINE METADATA FIXTURE; NEVER EXECUTED\n")
        binary.chmod(0o755)
        sha = hashlib.sha256(binary.read_bytes()).hexdigest()
        (self.root / "verified").mkdir()
        (self.root / "verified/v1").write_bytes((sha + "\n").encode("ascii"))
        (release / "manifest").write_bytes(("binary_sha256=" + sha + "\n").encode("ascii"))
        args = (PROJECT / "config/run-args.txt").read_bytes()
        (release / "run-args.txt").write_bytes(args)
        (release / "SHA256SUMS").write_bytes((hashlib.sha256(args).hexdigest() + "  run-args.txt\n").encode("ascii"))
        source = (SCRIPTS / "lp2-media").read_text().rsplit('\ncase "$action" in\n', 1)[0]
        source = source.replace("ROOT=/opt/lp2-media", 'ROOT="$PWD/root"')
        def check():
            return subprocess.run([self.shell, "-s"], input=source + "\nstat() { printf '0\\n'; }\nrelease_ready\n",
                                  cwd=str(self.directory), text=True, capture_output=True, timeout=15)
        good = check()
        self.assertEqual(good.returncode, 0, good.stderr)
        (self.root / "verified/v1").write_bytes(b"0" * 64 + b"\n")
        self.assertNotEqual(check().returncode, 0)
        (self.root / "verified/v1").write_bytes((sha + "\n").encode("ascii"))
        bad_args = b"--device /dev/video2 --udp-gap-us 50\n"
        (release / "run-args.txt").write_bytes(bad_args)
        (release / "SHA256SUMS").write_bytes((hashlib.sha256(bad_args).hexdigest() + "  run-args.txt\n").encode("ascii"))
        self.assertNotEqual(check().returncode, 0)


if __name__ == "__main__":
    if os.name != "posix":
        raise SystemExit("TEST ENVIRONMENT ERROR: run full suite on Ubuntu; no skipped/pseudo-passed POSIX tests")
    try:
        with tempfile.TemporaryDirectory(prefix="lp2-sysv-preflight-", dir="/tmp") as temp:
            probe = Path(temp)
            (probe / "v1").mkdir(); (probe / "v2").mkdir()
            (probe / "current").symlink_to("v1")
            (probe / "next").symlink_to("v2")
            os.replace(probe / "next", probe / "current")
            if os.readlink(probe / "current") != "v2":
                raise OSError("symlink replacement failed")
    except OSError as error:
        raise SystemExit("TEST ENVIRONMENT ERROR: /tmp must support native symlinks/rename: " + str(error))
    unittest.main()
