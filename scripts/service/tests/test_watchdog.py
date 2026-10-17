"""Offline M7.4 tests; unique mock procfs, no SSH or media execution."""
import importlib.util
import hashlib
import os
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location("sysv_fixture", Path(__file__).with_name("test_sysv.py"))
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)


class WatchdogTests(unittest.TestCase):
    run_shell = fixture.LogicTests.run_shell
    scan_process = fixture.LogicTests.scan_process

    def setUp(self):
        fixture.LogicTests.setUp(self)
        self.boot = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        path = self.proc / "sys/kernel/random"
        path.mkdir(parents=True)
        (path / "boot_id").write_bytes((self.boot + "\n").encode())
        self.clock(100)
        (self.directory / "wd.stat").write_bytes(fixture.stat_line(99, 500).encode())
        self.watchdog = (fixture.SCRIPTS / "lp2-watchdog").read_text(encoding="utf-8")

    def clock(self, seconds):
        (self.proc / "uptime").write_bytes((str(seconds) + ".00 0.00\n").encode())

    def wd_shell(self, command, extra=""):
        prefix = 'LP2_WD_LIBRARY=1\n' + self.watchdog + '''
wd_paths() { WD=/opt/lp2-media/service-tools/lp2-watchdog; WS="$PWD/recovery-state"; WL="$RUNTIME/watchdog.lock"; WP="$RUNTIME/watchdog.pid"; }
wd_paths
recovery_load() { recovery_enabled=1; }
check_tools() { printf 'checked\\n' >> "$PWD/recovery-check.calls"; }
wd_ssd_mock() {
 case "$*" in *"--pidfile $WP"*)
   case "$1" in
    --start)
     printf 'watchdog-start\\n' >> "$PWD/wd.calls"
     mkdir -m 700 "$WL" "$PROC/99"
     cp "$PWD/wd.stat" "$PROC/99/stat"
     printf '/bin/sh\\n' > "$PROC/99/exe"
     printf '/bin/sh\\000%s\\000run\\0005\\000' "$WD" > "$PROC/99/cmdline"
     printf '99\\n' > "$WP"
     printf '99 500 /bin/sh %s\\n' "''' + self.boot + '''" > "$WL/owner" ;;
    --stop)
     printf 'watchdog-stop\\n' >> "$PWD/wd.calls"
     rm "$PROC/99/stat" "$PROC/99/exe" "$PROC/99/cmdline"
     rmdir "$PROC/99"
     rm "$WL/owner" "$WP"; rmdir "$WL" ;;
   esac ;;
 *) ssd_mock "$@" ;;
 esac
}
SSD=wd_ssd_mock
umask 077
''' + extra
        return self.run_shell(command, prefix=prefix)

    def ok(self, command, extra=""):
        result = self.wd_shell(command, extra)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def crash(self, pid=42):
        process = self.proc / str(pid)
        for path in process.iterdir():
            path.unlink()
        process.rmdir()

    def test_wd_normal_poll_never_duplicates_server(self):
        self.ok("managed_start; recover_service; recover_service")
        self.assertEqual(len((self.directory / "ssd.calls").read_text(encoding="utf-8").splitlines()), 1)
        self.assertEqual((self.directory / "wd.calls").read_text().count("watchdog-start"), 1)

    def test_wd_crash_recovery_uses_existing_start_gate(self):
        self.ok("managed_start")
        self.crash()
        self.ok("recover_service")
        self.assertTrue((self.proc / "42/stat").exists())
        self.assertEqual(len((self.directory / "ssd.calls").read_text(encoding="utf-8").splitlines()), 2)
        self.assertTrue((self.directory / "recovery-check.calls").exists())
        self.assertIn("recovery_start_identity_confirmed", (self.directory / "recovery-state/events.log").read_text())

    def test_wd_manual_stop_disables_then_start_reenables(self):
        self.ok("managed_start; managed_stop; recover_service")
        self.assertFalse((self.proc / "42").exists())
        self.assertFalse((self.proc / "99").exists())
        self.assertIn("stopped 0", (self.directory / "recovery-state/state").read_text())
        self.ok("managed_start")
        self.crash()
        self.ok("recover_service")
        self.assertTrue((self.proc / "42/stat").exists())

    def test_wd_duplicate_start_identity_verified(self):
        self.ok("managed_start; wd_start; wd_start")
        self.assertEqual((self.directory / "wd.calls").read_text().count("watchdog-start"), 1)

    def test_wd_unknown_lp2_blocks_recovery(self):
        self.ok("managed_start")
        self.crash()
        self.scan_process(55)
        (self.proc / "55/exe").write_bytes(b"/var/volatile/tmp/lp2_m5_rtsp_server\n")
        result = self.wd_shell("recover_service")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Unmanaged LP2", result.stderr)
        self.assertFalse((self.proc / "42").exists())

    def test_wd_reused_server_pid_locks_without_signal(self):
        self.ok("managed_start")
        (self.proc / "42/stat").write_bytes(fixture.stat_line(42, 101).encode())
        result = self.wd_shell("recover_service")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("running 1", (self.directory / "recovery-state/state").read_text())
        self.assertEqual(len((self.directory / "ssd.calls").read_text(encoding="utf-8").splitlines()), 1)

    def test_wd_unknown_server_exe_locks(self):
        self.ok("managed_start")
        (self.proc / "42/exe").write_bytes(b"/sbin/unrelated\n")
        result = self.wd_shell("recover_service")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("identity_unknown_lock", (self.directory / "recovery-state/events.log").read_text())

    def test_wd_three_attempts_then_lock_and_explicit_reset(self):
        self.ok("managed_start")
        for number in range(3):
            self.crash()
            self.clock(105 + number * 5)
            self.ok("recover_service")
        self.crash()
        result = self.wd_shell("recover_service")
        self.assertNotEqual(result.returncode, 0)
        state = (self.directory / "recovery-state/state").read_bytes()
        self.clock(1000)
        self.ok("recover_service")
        self.assertEqual(state, (self.directory / "recovery-state/state").read_bytes())
        self.ok("wd_reset; recover_service")
        self.assertTrue((self.proc / "42").exists())

    def test_wd_window_expiry_and_cross_boot_clock(self):
        self.ok("wd_intent running; wd_reserve")
        self.clock(401)
        self.ok("wd_reserve; [ \"$wd_attempts\" = 1 ]")
        (self.proc / "sys/kernel/random/boot_id").write_bytes(b"11111111-2222-3333-4444-555555555555\n")
        self.clock(5)
        self.ok('wd_reserve; [ "$wd_attempts" = 2 ]; [ "$wd_window" = 5 ]')

    def test_wd_clock_regression_locks(self):
        self.ok("wd_intent running; wd_reserve")
        self.clock(99)
        result = self.wd_shell("wd_reserve")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("clock_regression_lock", (self.directory / "recovery-state/events.log").read_text())

    def test_wd_no_fixed_window_boundary_burst(self):
        self.ok("wd_intent running")
        for second in (390, 395, 399):
            self.clock(second)
            self.ok("wd_reserve")
        self.clock(401) # more than 300 since initialization, only 2 since retry
        result = self.wd_shell("wd_reserve")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("rate_limit_lock", (self.directory / "recovery-state/events.log").read_text())

    def test_wd_dead_watchdog_requires_manual_start(self):
        self.ok("managed_start")
        self.crash(99)
        self.ok("recover_service") # no indirect watchdog respawn
        self.assertEqual((self.directory / "wd.calls").read_text().count("watchdog-start"), 1)
        self.ok("managed_start")
        self.assertEqual((self.directory / "wd.calls").read_text().count("watchdog-start"), 2)

    def test_wd_reused_watchdog_pid_never_stopped_or_restarted(self):
        self.ok("managed_start")
        (self.proc / "99/stat").write_bytes(fixture.stat_line(99, 501).encode())
        result = self.wd_shell("wd_start")
        self.assertNotEqual(result.returncode, 0)
        result = self.wd_shell("managed_stop")
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("watchdog-stop", (self.directory / "wd.calls").read_text())
        self.assertIn("stopped", (self.directory / "recovery-state/state").read_text())

    def test_wd_log_rotation_and_stale_transaction_fail_closed(self):
        self.ok("wd_intent running")
        (self.directory / "recovery-state/events.log").write_bytes(b"x" * 16384)
        self.ok("wd_event test_rotation")
        self.assertEqual((self.directory / "recovery-state/events.log.1").stat().st_size, 16384)
        self.assertLess((self.directory / "recovery-state/events.log").stat().st_size, 256)
        (self.directory / "recovery-state/state.next").write_bytes(b"incomplete\n")
        result = self.wd_shell("wd_intent stopped")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((self.directory / "recovery-state/state.next").read_bytes(), b"incomplete\n")

    def test_wd_receipt_checked_before_library_execution(self):
        root = self.directory / "root"
        tools = root / "service-tools"
        control = root / "service-management"
        tools.mkdir(parents=True)
        control.mkdir()
        (tools / ".lp2-owned").write_bytes(b"LP2-M7.4-TOOLS-V1\n")
        (control / ".lp2-owned").write_bytes(b"LP2-M7.3-INSTALL-V1\n")
        helper = tools / "lp2-watchdog"
        helper.write_bytes(self.watchdog.encode())
        (control / "watchdog.sha256").write_bytes((hashlib.sha256(helper.read_bytes()).hexdigest() + "\n").encode())
        prefix = '''ROOT="$PWD/root"
stat() { case "$3" in "$ROOT/service-tools/lp2-watchdog"|"$ROOT/service-tools") printf '0:755\\n' ;;
 *) case "$2" in '%u:%a') printf '0:700\\n' ;; '%u') printf '0\\n' ;; *) command stat "$@" ;; esac ;; esac; }
'''
        result = self.run_shell('recovery_load; [ "$recovery_enabled" = 1 ]', prefix=prefix)
        self.assertEqual(result.returncode, 0, result.stderr)
        helper.write_bytes(b"printf hacked > unexpected-execution\n")
        result = self.run_shell("recovery_load", prefix=prefix)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("hash mismatch", result.stderr)
        self.assertFalse((self.directory / "unexpected-execution").exists())

    def test_wd_foreground_loop_recovers_and_cleans_own_record(self):
        # Execute the actual shell loop; mutate fake procfs between poll ticks.
        self.ok("wd_intent running; start_service")
        rest = fixture.stat_line(999, 500).split(" ", 1)[1].strip()
        prefix = '''mkdir "$PROC/$$"
printf '%s ''' + rest + '''\\n' "$$" > "$PROC/$$/stat"
printf '/bin/sh\\n' > "$PROC/$$/exe"
printf '%s\\n' "$$" > "$WP"
loop_tick=0
sleep() {
 loop_tick=$((loop_tick + 1))
 if [ "$loop_tick" = 2 ]; then
   rm "$PROC/42/stat" "$PROC/42/exe"; rmdir "$PROC/42"
 fi
}
wd_recover_command() {
 ( recover_service ) || exit 9
 [ "$loop_tick" -lt 2 ] || exit 0
}
'''
        self.ok("wd_run 5", extra=prefix)
        self.assertEqual(len((self.directory / "ssd.calls").read_text(encoding="utf-8").splitlines()), 2)
        self.assertFalse((self.runtime / "watchdog.lock").exists())
        self.assertFalse((self.runtime / "watchdog.pid").exists())


class NativeWatchdogInstallTests(unittest.TestCase):
    def setUp(self):
        # Reuse the native POSIX precondition and isolated symlink fixtures.
        fixture.NativeInstallTests.setUp(self)
        control = self.root / "service-management"
        control.mkdir(mode=0o700)
        (control / ".lp2-owned").write_bytes(b"LP2-M7.3-INSTALL-V1\n")
        self.staged = self.root / "service-staging/lp2-watchdog"
        self.staged.write_bytes((fixture.SCRIPTS / "lp2-watchdog").read_bytes())
        self.sha = hashlib.sha256(self.staged.read_bytes()).hexdigest()
        (self.directory / "status-fixture").write_bytes(b"exit 3\n")
        runtime = self.directory / "fake-runtime"
        runtime.mkdir(mode=0o700)
        (runtime / ".lp2-owned").write_bytes(b"LP2-M7.3-RUNTIME-V1\n")
        self.source = (fixture.SCRIPTS / "manage_watchdog.sh").read_text().replace(
            "ROOT=/opt/lp2-media", 'ROOT="$PWD/root"').replace(
            "RUNTIME=/var/volatile/tmp/lp2-media-service", 'RUNTIME="$PWD/fake-runtime"').replace(
            "/bin/sh /etc/init.d/lp2-media status", '/bin/sh "$PWD/status-fixture" status').replace(
            "/var/volatile/tmp/lp2-media-service/", str(self.directory / "fake-runtime") + "/")

    def run_installer(self, *args):
        import subprocess
        stub = '''PATH=/usr/bin:/bin:$PATH
id() { printf '0\\n'; }
stat() { case "$2" in '%u:%a') case "$3" in "$PWD/root/service-tools") printf '0:755\\n' ;; *) printf '0:700\\n' ;; esac ;; '%u') printf '0\\n' ;; *) command stat "$@" ;; esac; }
'''
        return subprocess.run([self.shell, "-s", "--"] + list(args), input=stub + self.source,
                              cwd=str(self.directory), text=True, capture_output=True, timeout=15)

    def test_helper_install_uninstall_preserves_init_release_and_state(self):
        init = self.etc / "init.d/lp2-media"
        init.write_bytes(b"FROZEN OLD INIT\n")
        state = self.root / "recovery-state"
        state.mkdir(); (state / "state").write_bytes(b"RETAIN DIAGNOSTIC\n")
        result = self.run_installer("install", self.sha, "--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.root / "service-tools").exists())
        result = self.run_installer("install", self.sha)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.root / "service-tools/lp2-watchdog").read_bytes(), self.staged.read_bytes())
        result = self.run_installer("uninstall", "--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.root / "service-tools/lp2-watchdog").exists())
        result = self.run_installer("uninstall")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(init.read_bytes(), b"FROZEN OLD INIT\n")
        self.assertEqual((state / "state").read_bytes(), b"RETAIN DIAGNOSTIC\n")

    def test_changed_helper_refuses_uninstall(self):
        self.assertEqual(self.run_installer("install", self.sha).returncode, 0)
        (self.root / "service-tools/lp2-watchdog").write_bytes(b"changed\n")
        self.assertNotEqual(self.run_installer("uninstall").returncode, 0)

    def test_live_service_or_runtime_lock_blocks_install(self):
        (self.directory / "status-fixture").write_bytes(b"exit 0\n")
        self.assertNotEqual(self.run_installer("install", self.sha).returncode, 0)
        (self.directory / "status-fixture").write_bytes(b"exit 3\n")
        runtime = self.directory / "fake-runtime"
        (runtime / "watchdog.lock").mkdir()
        self.assertNotEqual(self.run_installer("install", self.sha).returncode, 0)

    def test_unknown_tools_or_incomplete_receipt_blocks_install(self):
        tools = self.root / "service-tools"
        tools.mkdir(); (tools / "lp2-watchdog").write_bytes(b"unknown\n")
        self.assertNotEqual(self.run_installer("install", self.sha).returncode, 0)

    def test_wrong_approval_does_not_install(self):
        self.assertNotEqual(self.run_installer("install", "0" * 64).returncode, 0)
        self.assertFalse((self.root / "service-tools").exists())


if __name__ == "__main__":
    if os.name != "posix":
        raise SystemExit("TEST ENVIRONMENT ERROR: full suite requires native Ubuntu; no pseudo-passed install tests")
    unittest.main()
