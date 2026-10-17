#!/usr/bin/env python3
"""Ubuntu-side read-only SSH resource sampler for LP2; Python stdlib only."""
import argparse
import csv
import datetime
import functools
import ipaddress
import json
import math
import os
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "results" / "stability"
PROBE = Path(__file__).with_name("board_resource_probe.sh")
EXE = "/tmp/lp2_m5_rtsp_server"
PERSISTENT_EXE = "/opt/lp2-media/current/bin/lp2_rtsp_server"
PHASES = ("UNKNOWN", "PLAY", "IDLE")
FIELDS = ["timestamp_utc", "elapsed_sec", "sample_index", "slot_index", "phase",
          "phase_source", "sample_ok", "pid", "start_ticks", "vm_rss_kb",
          "vm_size_kb", "vm_hwm_kb", "threads", "open_fd_count", "process_state",
          "error_kind", "error"]


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="milliseconds")


def positive_seconds(value):
    value = float(value)
    if not math.isfinite(value) or value <= 0:
        raise argparse.ArgumentTypeError("seconds must be finite and positive")
    return value


def parse_probe(output):
    values = output.strip().split(",")
    if len(values) != 8 or any(not value.isascii() or not value.isdigit() for value in values[:7]):
        raise ValueError("malformed board resource response")
    pid, start, fds, rss, size, hwm, threads = map(int, values[:7])
    state = values[7]
    if pid <= 0 or start <= 0 or threads <= 0 or hwm < rss or size < rss:
        raise ValueError("invalid board resource values")
    if len(state) != 1 or state not in "RSDTtXZxIKWP":
        raise ValueError("invalid process state")
    return dict(pid=pid, start_ticks=start, open_fd_count=fds, vm_rss_kb=rss,
                vm_size_kb=size, vm_hwm_kb=hwm, threads=threads, process_state=state)


def sample_ssh(host, pid, timeout_sec, executable=EXE):
    if executable not in (EXE, PERSISTENT_EXE):
        raise ValueError("Only explicit LP2 executable paths are allowed")
    # BatchMode gives a bounded failure instead of waiting for a password.
    command = ["ssh", "-o", "HostKeyAlgorithms=+ssh-rsa", "-o", "BatchMode=yes",
               "-o", "ConnectTimeout=5", "-o", "ServerAliveInterval=5",
               "-o", "ServerAliveCountMax=1", "root@" + host,
               "LP2_PROC_ROOT=/proc sh -s -- " + executable + (" " + str(pid) if pid else "")]
    return subprocess.run(command, input=PROBE.read_text(), stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, universal_newlines=True, timeout=timeout_sec)


def write_json(path, data):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(str(temporary), str(path))


def mark(run_directory, phase):
    directory = Path(run_directory).resolve()
    if RESULTS.resolve() not in directory.parents or not (directory / "metadata.json").is_file():
        raise ValueError("run directory must be an existing LP2 results/stability run")
    temporary = directory / "phase.tmp"
    temporary.write_text(phase + "\n", encoding="ascii")
    os.replace(str(temporary), str(directory / "phase.txt"))
    with (directory / "phase_events.csv").open("a", newline="", encoding="utf-8") as output:
        csv.writer(output).writerow([utc_now(), phase, "manual"])
    print("Manual phase marked: " + phase)


def monitor(args, transport=sample_ssh):
    # Fixed workspace-local output; no remote file creation or process signals.
    run_name = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid.uuid4().hex[:8]
    directory = RESULTS / run_name
    directory.mkdir(parents=True)
    (directory / "phase.txt").write_text("UNKNOWN\n", encoding="ascii")
    (directory / "phase_events.csv").write_text("timestamp_utc,phase,source\n", encoding="ascii")
    metadata = dict(schema_version=1, host=args.host, expected_exe=getattr(args, "executable", EXE),
                    interval_sec=args.interval_sec, requested_duration_sec=args.duration_sec,
                    started_utc=utc_now(), finished_utc=None, observed_duration_sec=0,
                    valid_samples=0, attempted_samples=0, stop_reason="running")
    write_json(directory / "metadata.json", metadata)
    print("Run directory: " + str(directory), flush=True)
    print("SSH is read-only; phase is manual UNKNOWN until marked PLAY/IDLE.", flush=True)
    start = time.monotonic()
    slot = 0
    identity = None
    reason = "completed_duration"
    exit_code = 0
    with (directory / "resources.csv").open("w", newline="", encoding="utf-8") as output, \
            (directory / "monitor.log").open("w", encoding="utf-8") as log:
        writer = csv.DictWriter(output, fieldnames=FIELDS)
        writer.writeheader()
        output.flush()
        try:
            while True:
                now = time.monotonic() - start
                if now >= args.duration_sec:
                    break
                due = slot * args.interval_sec
                if now < due:
                    time.sleep(min(due - now, args.duration_sec - now))
                    continue
                row = dict(timestamp_utc=utc_now(), elapsed_sec="{:.6f}".format(now),
                           sample_index=metadata["attempted_samples"] + 1, slot_index=slot,
                           phase="UNKNOWN", phase_source="manual", sample_ok=0)
                metadata["attempted_samples"] += 1
                try:
                    phase = (directory / "phase.txt").read_text(encoding="ascii").strip()
                    if phase not in PHASES:
                        raise ValueError("invalid manual phase marker")
                    row["phase"] = phase
                    response = transport(args.host, identity[0] if identity else args.pid,
                                         args.ssh_timeout_sec)
                    if response.returncode:
                        row["error_kind"] = "SSH_FAILURE" if response.returncode == 255 else "REMOTE_PROBE_FAILURE"
                        raise RuntimeError("exit {}: {}".format(response.returncode, response.stderr.strip()))
                    metrics = parse_probe(response.stdout)
                    current = (metrics["pid"], metrics["start_ticks"])
                    if identity is None and args.pid is not None and current[0] != args.pid:
                        row["error_kind"] = "PROCESS_IDENTITY_CHANGED"
                        raise RuntimeError("response PID does not match requested PID")
                    if identity is not None and identity != current:
                        row["error_kind"] = "PROCESS_IDENTITY_CHANGED"
                        raise RuntimeError("PID/starttime changed; server restart or PID reuse")
                    identity = current
                    row.update(metrics)
                    row["sample_ok"] = 1
                    metadata["valid_samples"] += 1
                except KeyboardInterrupt:
                    if row["sample_ok"]:
                        metadata["valid_samples"] -= 1
                    row["sample_ok"] = 0
                    for key in ("pid", "start_ticks", "vm_rss_kb", "vm_size_kb", "vm_hwm_kb",
                                "threads", "open_fd_count", "process_state"):
                        row.pop(key, None)
                    row["error_kind"] = "USER_INTERRUPT"
                    row["error"] = "in-flight sample interrupted by user"
                    reason = "user_interrupt"
                    exit_code = 130
                except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
                    row.setdefault("error_kind", "SAMPLE_FAILURE")
                    row["error"] = str(error)
                    reason = "sample_failure"
                    exit_code = 1
                row["timestamp_utc"] = utc_now()
                row["elapsed_sec"] = "{:.6f}".format(time.monotonic() - start)
                writer.writerow(row)
                output.flush()
                line = "sample={} slot={} phase={} ok={} pid={} error={}\n".format(
                    row["sample_index"], slot, row["phase"], row["sample_ok"],
                    row.get("pid", ""), row.get("error", ""))
                log.write(line)
                log.flush()
                print(line.rstrip(), flush=True)
                if exit_code:
                    break
                # Missed slots remain visible in CSV instead of burst sampling.
                slot = max(slot + 1, int((time.monotonic() - start) / args.interval_sec) + 1)
        except KeyboardInterrupt:
            reason = "user_interrupt"
            exit_code = 130
        finally:
            metadata.update(finished_utc=utc_now(), observed_duration_sec=time.monotonic() - start,
                            stop_reason=reason, process_identity=identity)
            write_json(directory / "metadata.json", metadata)
    print("Stopped: {} valid={} duration={:.3f}s".format(
        reason, metadata["valid_samples"], metadata["observed_duration_sec"]), flush=True)
    return exit_code, directory


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    sample = sub.add_parser("monitor")
    sample.add_argument("--host", type=lambda value: str(ipaddress.IPv4Address(value)), default="192.168.50.2")
    sample.add_argument("--pid", type=int, help="optional PID, still verified against full executable path")
    sample.add_argument("--executable", choices=(EXE, PERSISTENT_EXE), default=EXE,
                        help="canonical full path matching; old /tmp default is retained")
    sample.add_argument("--interval-sec", type=positive_seconds, default=10.0)
    sample.add_argument("--duration-sec", type=positive_seconds, default=1800.0)
    sample.add_argument("--ssh-timeout-sec", type=positive_seconds, default=15.0)
    phase = sub.add_parser("mark")
    phase.add_argument("run_directory")
    phase.add_argument("phase", choices=PHASES)
    args = parser.parse_args()
    if args.action == "mark":
        mark(args.run_directory, args.phase)
        return 0
    if args.pid is not None and args.pid <= 0:
        parser.error("--pid must be positive")
    def interrupted(signum, frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, interrupted)
    return monitor(args, functools.partial(sample_ssh, executable=args.executable))[0]


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError) as error:
        print("ERROR: " + str(error), file=sys.stderr)
        sys.exit(1)
