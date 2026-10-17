"""Offline CSV, SSH-failure and /proc fixture checks. Never contact the board."""
import csv
import datetime
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
import monitor_resources as monitor
import analyze_stability as analyzer


def row(slot, phase="IDLE", rss=4096, fds=12, threads=4, ok=True):
    result = dict.fromkeys(monitor.FIELDS, "")
    stamp = datetime.datetime(2026, 10, 13, tzinfo=datetime.timezone.utc) + datetime.timedelta(seconds=slot * 10)
    result.update(timestamp_utc=stamp.isoformat(), elapsed_sec=str(slot * 10),
                  sample_index=str(slot + 1), slot_index=str(slot), phase=phase,
                  phase_source="manual", sample_ok="1" if ok else "0")
    if ok:
        result.update(pid="42", start_ticks="100", vm_rss_kb=str(rss),
                      vm_size_kb="20000", vm_hwm_kb="19000", threads=str(threads),
                      open_fd_count=str(fds), process_state="S")
    else:
        result.update(error_kind="SSH_FAILURE", error="exit 255: connection lost")
    return result


class StabilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix=".lp2-stability-test-", dir=str(monitor.ROOT))
        self.directory = Path(self.temp.name)
        self.path = self.directory / "resources.csv"

    def tearDown(self):
        self.temp.cleanup()

    def write(self, rows):
        with self.path.open("w", newline="", encoding="utf-8") as output:
            writer = csv.DictWriter(output, fieldnames=monitor.FIELDS)
            writer.writeheader()
            writer.writerows(rows)

    def test_normal_resources_and_separate_idle_epochs(self):
        self.write([row(0), row(1, "PLAY", 5000, 15, 6), row(2, "PLAY", 5100, 15, 6),
                    row(3, "IDLE", 4500), row(4, "IDLE", 4500)])
        data = analyzer.analyze(self.path, warmup_sec=0)
        self.assertEqual(data["sample_count"], 5)
        self.assertEqual(data["elapsed_time_sec"], 40)
        self.assertEqual(data["overall"]["vm_rss_kb"]["growth"], 404)
        self.assertEqual(data["overall"]["open_fd_count"]["maximum"], 15)
        self.assertEqual(data["phases"]["IDLE"]["open_fd_count"]["median"], 12)
        self.assertEqual(len(data["phase_epochs"]), 3)
        self.assertIn("No leak-free", data["conclusion"])

    def test_empty_and_header_only_rejected(self):
        self.path.write_text("", encoding="utf-8")
        with self.assertRaises(ValueError):
            analyzer.analyze(self.path)
        self.write([])
        with self.assertRaises(ValueError):
            analyzer.analyze(self.path)

    def test_bad_data_rejected(self):
        for key, value in (("vm_rss_kb", "nan"), ("elapsed_sec", "nan"),
                           ("threads", "0"), ("phase", "ACTIVE"),
                           ("timestamp_utc", "2026-10-13T00:00:00"),
                           ("vm_hwm_kb", "1"), ("process_state", "?")):
            with self.subTest(key=key):
                entry = row(0)
                entry[key] = value
                self.write([entry])
                with self.assertRaises(ValueError):
                    analyzer.analyze(self.path)

    def test_missing_slots_and_failed_row_counted(self):
        self.write([row(0), row(1), row(3), row(4, ok=False)])
        data = analyzer.analyze(self.path)
        self.assertEqual(data["sample_count"], 3)
        self.assertEqual(data["missing_samples"], 2)
        self.assertEqual(data["failed_samples"], 1)

    def test_duplicate_time_and_process_restart_rejected(self):
        self.write([row(0), row(0)])
        with self.assertRaises(ValueError):
            analyzer.analyze(self.path)
        changed = row(1)
        changed["start_ticks"] = "101"
        self.write([row(0), changed])
        with self.assertRaises(ValueError):
            analyzer.analyze(self.path)

    def test_monitor_duration_distinct_from_sample_span(self):
        self.write([row(slot) for slot in range(179)])
        meta = dict(schema_version=1, interval_sec=10, requested_duration_sec=1800,
                    observed_duration_sec=1800, valid_samples=179, attempted_samples=179,
                    stop_reason="completed_duration")
        (self.directory / "metadata.json").write_text(json.dumps(meta), encoding="utf-8")
        data = analyzer.analyze(self.path)
        self.assertEqual(data["elapsed_time_sec"], 1780)
        self.assertEqual(data["metadata"]["observed_duration_sec"], 1800)
        self.assertEqual(data["missing_slots"], 1)

    def test_parse_probe_and_identity_fields(self):
        self.assertEqual(monitor.parse_probe("42,100,12,4096,20000,5000,4,S\n")["pid"], 42)
        for output in ("", "42,100,12,0,20,10,0,S", "42,100,12,nan,20,10,4,S"):
            with self.assertRaises(ValueError):
                monitor.parse_probe(output)

    def run_monitor(self, transport, duration=0.03, interval=0.01):
        args = SimpleNamespace(host="192.168.50.2", pid=None,
                               duration_sec=duration, interval_sec=interval, ssh_timeout_sec=1)
        with patch.object(monitor, "RESULTS", self.directory / "runs"), redirect_stdout(io.StringIO()):
            return monitor.monitor(args, transport)

    def test_ssh_failure_is_explicit_row_and_nonzero_exit(self):
        code, directory = self.run_monitor(lambda *args: subprocess.CompletedProcess([], 255, "", "connection lost"))
        self.assertEqual(code, 1)
        rows = analyzer.load_csv(directory / "resources.csv")
        self.assertEqual(rows[0]["sample_ok"], 0)
        self.assertEqual(rows[0]["vm_rss_kb"], "")
        self.assertEqual(rows[0]["error_kind"], "SSH_FAILURE")
        self.assertEqual(json.loads((directory / "metadata.json").read_text())["stop_reason"], "sample_failure")

    def test_pid_not_found_and_timeout_fail_fast(self):
        for transport in (
                lambda *args: subprocess.CompletedProcess([], 20, "", "LP2 process not found"),
                lambda *args: (_ for _ in ()).throw(subprocess.TimeoutExpired("ssh", 1))):
            code, directory = self.run_monitor(transport)
            self.assertEqual(code, 1)
            self.assertEqual(len(analyzer.load_csv(directory / "resources.csv")), 1)

    def test_monitor_pins_pid_and_detects_reuse(self):
        calls = []
        def transport(host, pid, timeout):
            calls.append(pid)
            start = 100 if len(calls) == 1 else 101
            return subprocess.CompletedProcess([], 0, "42,{},12,4096,20000,5000,4,S".format(start), "")
        code, directory = self.run_monitor(transport)
        self.assertEqual(code, 1)
        self.assertEqual(calls, [None, 42])
        rows = analyzer.load_csv(directory / "resources.csv")
        self.assertEqual(rows[-1]["error_kind"], "PROCESS_IDENTITY_CHANGED")

    def test_ssh_command_is_bounded_and_read_only(self):
        response = subprocess.CompletedProcess([], 255, "", "simulated")
        with patch.object(monitor.subprocess, "run", return_value=response) as execute:
            monitor.sample_ssh("192.168.50.2", 42, 15)
        command = execute.call_args.args[0]
        self.assertIn("HostKeyAlgorithms=+ssh-rsa", command)
        self.assertIn("BatchMode=yes", command)
        self.assertIn("sh -s -- /tmp/lp2_m5_rtsp_server 42", command[-1])
        self.assertEqual(execute.call_args.kwargs["timeout"], 15)

    def test_user_interrupt_keeps_prior_data_analyzable(self):
        calls = []
        def transport(*args):
            calls.append(1)
            if len(calls) > 1:
                raise KeyboardInterrupt
            return subprocess.CompletedProcess([], 0, "42,100,12,4096,20000,5000,4,S", "")
        code, directory = self.run_monitor(transport)
        self.assertEqual(code, 130)
        data = analyzer.analyze(directory / "resources.csv")
        self.assertEqual(data["sample_count"], 1)
        self.assertEqual(data["metadata"]["stop_reason"], "user_interrupt")

    def test_requested_pid_response_mismatch_refused(self):
        args = SimpleNamespace(host="192.168.50.2", pid=42, duration_sec=0.03,
                               interval_sec=0.01, ssh_timeout_sec=1)
        with patch.object(monitor, "RESULTS", self.directory / "runs"), redirect_stdout(io.StringIO()):
            code, directory = monitor.monitor(args, lambda *unused:
                subprocess.CompletedProcess([], 0, "43,100,12,4096,20000,5000,4,S", ""))
        self.assertEqual(code, 1)
        self.assertEqual(analyzer.load_csv(directory / "resources.csv")[0]["error_kind"], "PROCESS_IDENTITY_CHANGED")

    def test_all_failures_have_no_resource_trend(self):
        self.write([row(0, ok=False)])
        data = analyzer.analyze(self.path)
        self.assertIsNone(data["overall"])
        self.assertEqual(data["sample_count"], 0)


class ProbeFixtureTests(unittest.TestCase):
    def setUp(self):
        shell = os.environ.get("LP2_TEST_SHELL") or shutil.which("sh")
        if not shell:
            self.skipTest("Set LP2_TEST_SHELL to a local POSIX shell for proc fixtures")
        self.shell = shell
        self.temp = tempfile.TemporaryDirectory(prefix=".lp2-proc-test-", dir=str(monitor.ROOT))
        self.root = Path(self.temp.name)

    def tearDown(self):
        if hasattr(self, "temp"):
            self.temp.cleanup()

    def process(self, pid, exe=monitor.EXE, status=True):
        directory = self.root / str(pid)
        directory.mkdir()
        (directory / "exe").write_bytes((exe + "\n").encode("utf-8"))
        # A troublesome comm proves starttime isn't parsed by raw field number.
        (directory / "stat").write_bytes("{} (lp2 ) name) S {} 100\n".format(pid, " ".join(["0"] * 18)).encode("utf-8"))
        if status:
            (directory / "status").write_bytes(b"State:\tS (sleeping)\nVmRSS:\t4096 kB\nVmSize:\t20000 kB\nVmHWM:\t5000 kB\nThreads:\t4\n")
        (directory / "fd").mkdir()
        for number in range(3):
            (directory / "fd" / str(number)).write_text("fixture")

    def probe(self, pid=None, mapped=False, canonical_failure=False,
              executable=monitor.EXE, release_target="/opt/lp2-media/releases/v1/bin/lp2_rtsp_server"):
        env = dict(os.environ, LP2_PROC_ROOT=self.root.relative_to(monitor.ROOT).as_posix(),
                   LP2_TEST_CANONICAL_EXE=("/var/volatile/tmp/lp2_m5_rtsp_server" if mapped else monitor.EXE),
                   LP2_TEST_CANONICAL_FAIL="1" if canonical_failure else "0",
                   LP2_TEST_RELEASE_TARGET=release_target)
        # Only readlink is replaced for ordinary fixture files; all PID/comm/
        # status/fd handling executes the production shell probe.
        source = '''PATH=/usr/bin:/bin:$PATH
readlink() {
    if [ "$1" != -f ]; then cat "$1"; return; fi
    [ "$LP2_TEST_CANONICAL_FAIL" = 0 ] || return 1
    case "$2" in
        "$LP2_PROC_ROOT"/*/exe) raw=$(cat "$2") || return 1 ;;
        *) raw=$2 ;;
    esac
    case "$raw" in
        /tmp/lp2_m5_rtsp_server) printf '%s\\n' "$LP2_TEST_CANONICAL_EXE" ;;
        /opt/lp2-media/current/bin/lp2_rtsp_server) printf '%s\\n' "$LP2_TEST_RELEASE_TARGET" ;;
        *) printf '%s\\n' "$raw" ;;
    esac
}
''' + monitor.PROBE.read_text()
        return subprocess.run([self.shell, "-s", "--", executable] + ([str(pid)] if pid else []),
                              input=source, env=env, cwd=str(monitor.ROOT),
                              capture_output=True, text=True, timeout=10)

    def test_full_path_not_truncated_name_and_parentheses(self):
        self.process(42)
        self.process(43, monitor.EXE + "_other")
        response = self.probe()
        self.assertEqual(response.returncode, 0, response.stderr)
        data = monitor.parse_probe(response.stdout)
        self.assertEqual((data["pid"], data["start_ticks"], data["open_fd_count"]), (42, 100, 3))

    def test_not_found_ambiguous_and_explicit_pid(self):
        self.assertEqual(self.probe().returncode, 20)
        self.process(42)
        self.process(43)
        self.assertEqual(self.probe().returncode, 21)
        self.assertEqual(self.probe(42).returncode, 0)
        self.assertEqual(self.probe(99).returncode, 22)

    def test_missing_status_fails_instead_of_zero_metrics(self):
        self.process(42, status=False)
        response = self.probe()
        self.assertEqual(response.returncode, 23)
        self.assertEqual(response.stdout, "")

    def test_tmp_mapping_scans_and_explicit_pid(self):
        self.process(1042, "/var/volatile/tmp/lp2_m5_rtsp_server")
        for pid in (None, 1042):
            response = self.probe(pid, mapped=True)
            self.assertEqual(response.returncode, 0, response.stderr)
            self.assertEqual(monitor.parse_probe(response.stdout)["pid"], 1042)

    def test_mapped_similar_name_and_other_directory_refused(self):
        self.process(42, "/var/volatile/tmp/lp2_m5_rtsp_server_other")
        self.process(43, "/opt/unrelated/lp2_m5_rtsp_server")
        self.assertEqual(self.probe(mapped=True).returncode, 20)
        self.assertEqual(self.probe(43, mapped=True).returncode, 22)

    def test_mapped_deleted_image_refused(self):
        self.process(42, "/var/volatile/tmp/lp2_m5_rtsp_server (deleted)")
        self.assertEqual(self.probe(mapped=True).returncode, 20)

    def test_aliases_still_require_unique_pid(self):
        self.process(42, monitor.EXE)
        self.process(43, "/var/volatile/tmp/lp2_m5_rtsp_server")
        self.assertEqual(self.probe(mapped=True).returncode, 21)

    def test_canonicalization_failure_has_no_fuzzy_fallback(self):
        self.process(42)
        response = self.probe(canonical_failure=True)
        self.assertEqual(response.returncode, 22)
        self.assertIn("Cannot canonicalize", response.stderr)
        self.assertEqual(response.stdout, "")

    def test_persistent_release_exact_match(self):
        self.process(42, "/opt/lp2-media/releases/v1/bin/lp2_rtsp_server")
        self.process(43, "/opt/lp2-media/releases/v2/bin/lp2_rtsp_server")
        response = self.probe(executable=monitor.PERSISTENT_EXE)
        self.assertEqual(response.returncode, 0, response.stderr)
        self.assertEqual(monitor.parse_probe(response.stdout)["pid"], 42)
        self.assertEqual(self.probe(43, executable=monitor.PERSISTENT_EXE).returncode, 22)

    def test_persistent_current_may_not_escape_lp2(self):
        self.process(42, "/opt/unrelated/lp2_rtsp_server")
        for target in ("/opt/unrelated/lp2_rtsp_server",
                       "/opt/lp2-media/releases/a/b/bin/lp2_rtsp_server"):
            response = self.probe(executable=monitor.PERSISTENT_EXE, release_target=target)
            self.assertEqual(response.returncode, 22)


if __name__ == "__main__":
    unittest.main()
