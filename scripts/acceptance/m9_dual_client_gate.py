#!/usr/bin/env python3
"""Bounded Ubuntu M9.3 gate. Only its own FFmpeg children receive signals."""
import argparse
import datetime
import json
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid

ROOT = Path(__file__).resolve().parents[2]
URL = "rtsp://192.168.50.2:8554/live"
PROBE = ROOT / "scripts/stability/board_resource_probe.sh"


class GateError(Exception):
    def __init__(self, verdict, reason, kind=None):
        super().__init__(reason)
        self.verdict = verdict
        self.kind = kind


def save(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def stage(directory, message):
    print(message, flush=True)
    with (directory / "stages.log").open("a", encoding="utf-8") as output:
        output.write(datetime.datetime.now(datetime.timezone.utc).isoformat() + " " + message + "\n")


def ssh_command():
    # Keep normal identity files/agent, but prohibit terminal interaction, proxy
    # helpers, inherited forwards and multiplexing of another SSH connection.
    options = ["HostKeyAlgorithms=+ssh-rsa", "BatchMode=yes", "ConnectTimeout=5",
               "ConnectionAttempts=1", "ServerAliveInterval=3", "ServerAliveCountMax=1",
               "NumberOfPasswordPrompts=0", "PasswordAuthentication=no",
               "KbdInteractiveAuthentication=no", "StrictHostKeyChecking=yes",
               "RequestTTY=no", "StdinNull=no", "ControlMaster=no", "ControlPath=none",
               "ProxyCommand=none", "ProxyJump=none", "PermitLocalCommand=no",
               "ClearAllForwardings=yes", "RemoteCommand=none"]
    command = ["ssh", "-T"]
    for option in options:
        command.extend(["-o", option])
    return command + ["root@192.168.50.2", "sh -s"]


def run_ssh(directory, label, script, timeout_sec=15, command=None):
    """Finite file stdin; outputs go straight to disk, never communicate pipes.

    Waiting for this owned SSH PID has an overall deadline independent of TCP
    keepalives and remote command execution. A timed-out/interrupted probe keeps
    partial output. No second unbounded communicate() occurs during cleanup.
    """
    cmd = ssh_command() if command is None else command
    save(directory / (label + "-ssh-command.json"), cmd)
    script_path = directory / (label + "-probe.sh")
    script_path.write_text(script, encoding="utf-8")
    info = dict(timeout_sec=timeout_sec, elapsed_sec=0, exit_code=None, outcome="starting")
    process = None
    started = time.monotonic()
    failure = None
    with script_path.open("rb") as source, \
            (directory / (label + "-board.txt")).open("wb") as output, \
            (directory / (label + "-ssh.stderr")).open("wb") as errors:
        try:
            process = subprocess.Popen(cmd, stdin=source, stdout=output, stderr=errors,
                                       start_new_session=True)
            info.update(pid=process.pid, outcome="running")
            save(directory / (label + "-ssh-result.json"), info)
            process.wait(timeout=timeout_sec)
            info["outcome"] = "completed" if process.returncode == 0 else "ssh_error"
        except subprocess.TimeoutExpired:
            info["outcome"] = "timeout"
            failure = GateError("INCONCLUSIVE", "{} SSH exceeded {}s; partial evidence saved".format(
                label, timeout_sec), "SSH_TIMEOUT")
        except KeyboardInterrupt:
            info["outcome"] = "interrupted"
            failure = GateError("INCONCLUSIVE", label + " SSH interrupted; partial evidence saved", "SSH_INTERRUPTED")
        except OSError as error:
            info["outcome"] = "launch_error"
            failure = GateError("INCONCLUSIVE", "Read-only SSH failed: " + str(error), "SSH_ERROR")
        finally:
            if process is not None:
                if process.poll() is None:
                    # The detached, still-owned SSH child only; never a broad kill.
                    process.kill()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    info["cleanup_error"] = "SSH PID did not reap within 2s after kill"
                    failure = GateError("INCONCLUSIVE", info["cleanup_error"], "SSH_CLEANUP")
                info["exit_code"] = process.returncode
            info["elapsed_sec"] = time.monotonic() - started
            save(directory / (label + "-ssh-result.json"), info)
    if failure:
        raise failure
    if process.returncode:
        detail = (directory / (label + "-ssh.stderr")).read_text(encoding="utf-8", errors="replace")[-2000:]
        raise GateError("INCONCLUSIVE", "{} SSH/probe exit {}: {}".format(
            label, process.returncode, detail.strip() or "no stderr; inspect partial board output"), "SSH_ERROR")
    return (directory / (label + "-board.txt")).read_text(encoding="utf-8", errors="replace")


def parse_snapshot(text):
    service = re.search(r"LP2: running pid=(\d+) start_ticks=(\d+) executable=(\S+)", text)
    recovery = re.search(r"desired=(\w+) locked=(\d+) attempts=(\d+)", text)
    wd = re.search(r"Watchdog identity verified pid=(\d+)", text)
    boot = re.search(r"^BOOT=([0-9a-f-]+)$", text, re.M)
    metrics = re.search(r"^PROBE=(\d+),(\d+),\d+,\d+,\d+,\d+,\d+,([A-Za-z])$", text, re.M)
    stat = re.search(r"^WDSTAT=(.+)$", text, re.M)
    if not all((service, recovery, wd, boot, metrics, stat)):
        raise GateError("INCONCLUSIVE", "Incomplete board identity/watchdog evidence")
    rest = stat[1].rsplit(") ", 1)[-1].split()
    try:
        wd_pid = int(stat[1].split(" ", 1)[0])
        wd_ticks = int(rest[19])
    except (ValueError, IndexError):
        raise GateError("INCONCLUSIVE", "Unparseable watchdog stat")
    pid, ticks, exe = service.groups()
    if (pid, ticks) != metrics.groups()[:2] or wd_pid != int(wd[1]):
        raise GateError("INCONCLUSIVE", "Identity changed during board probe")
    if metrics[3] in "ZXxTt" or rest[0] in "ZXxTt" or wd_ticks <= 0:
        raise GateError("FAIL", "Board service/watchdog is dead or stopped")
    if not re.fullmatch(r"/opt/lp2-media/releases/[A-Za-z0-9._-]+/bin/lp2_rtsp_server", exe):
        raise GateError("INCONCLUSIVE", "Service is not the persistent LP2 release")
    return dict(pid=int(pid), start_ticks=int(ticks), executable=exe,
                watchdog_pid=wd_pid, watchdog_ticks=wd_ticks, boot_id=boot[1],
                desired=recovery[1], locked=int(recovery[2]), attempts=int(recovery[3]))


def board_snapshot(directory, label):
    # No remote writes, signals, service start/stop, or network configuration.
    script = """set -eu
/etc/init.d/lp2-media status </dev/null
w=$(/etc/init.d/lp2-media watchdog-status </dev/null)
printf '%s\n' "$w"
p=$(printf '%s\n' "$w" | awk '/Watchdog identity verified pid=/ {sub(/.*pid=/, ""); print}')
case "$p" in ''|*[!0-9]*) exit 29 ;; esac
printf 'WDSTAT='; cat "/proc/$p/stat"
printf 'BOOT='; cat /proc/sys/kernel/random/boot_id
printf 'PROBE='
(
LP2_PROC_ROOT=/proc
export LP2_PROC_ROOT
set -- /opt/lp2-media/current/bin/lp2_rtsp_server
""" + PROBE.read_text(encoding="utf-8") + "\n)\nexit 0\n"
    return parse_snapshot(run_ssh(directory, label, script))


def compare_board(before, after):
    if before != after:
        raise GateError("FAIL", "Board service/watchdog identity or recovery state changed")
    if after["desired"] != "running" or after["locked"] != 0:
        raise GateError("FAIL", "Watchdog is stopped or locked")


def ffmpeg_command(executable):
    # Decode, do not stream-copy. Null muxer frame= progress counts decoder output.
    # No GUI, shared terminal stdin, shell wrapper, or group-wide kill.
    return [executable, "-nostdin", "-hide_banner", "-loglevel", "info", "-nostats",
            "-stats_period", "0.5", "-progress", "pipe:1", "-rtsp_transport", "udp",
            "-fflags", "nobuffer", "-flags", "low_delay", "-max_delay", "0",
            "-reorder_queue_size", "0", "-err_detect", "explode", "-i", URL,
            "-map", "0:v:0", "-an", "-sn", "-dn", "-vsync", "0", "-f", "null", "-"]


class Client:
    def __init__(self, name, command, directory, origin):
        self.name, self.directory, self.origin = name, directory, origin
        self.lock = threading.Lock()
        self.frames, self.updated = 0, origin
        self.stop_reason, self.stop_escalated = None, False
        self.cleaned = False
        self.reader_error = None
        self.log = (directory / (name + ".log")).open("w", encoding="utf-8")
        try:
            self.process = subprocess.Popen(command, stdin=subprocess.DEVNULL,
                                            stdout=subprocess.PIPE, stderr=self.log,
                                            text=True, bufsize=1, start_new_session=True)
        except BaseException:
            self.log.close()
            raise
        save(directory / (name + "-process.json"),
             dict(pid=self.process.pid, command=command, started_monotonic=time.monotonic()))
        self.reader = threading.Thread(target=self.read_progress, daemon=True)
        self.reader.start()

    def read_progress(self):
        try:
            with (self.directory / (self.name + "-progress.log")).open("w", encoding="utf-8") as raw, \
                    (self.directory / (self.name + "-frames.csv")).open("w", encoding="utf-8") as evidence:
                evidence.write("elapsed_sec,decoded_frames\n")
                for line in self.process.stdout:
                    raw.write(line); raw.flush()
                    if line.startswith("frame="):
                        count = int(line.partition("=")[2].strip())
                        now = time.monotonic()
                        with self.lock:
                            if count < self.frames:
                                raise ValueError("Decoded frame counter moved backwards")
                            if count > self.frames:
                                self.updated = now
                            self.frames = count
                        evidence.write("{:.6f},{}\n".format(now - self.origin, count))
                        evidence.flush()
        except Exception as error:
            self.reader_error = str(error)

    def sample(self):
        with self.lock:
            return dict(frames=self.frames, last_increase=self.updated,
                        alive=self.process.poll() is None, reader_error=self.reader_error)

    def stop(self, reason):
        if self.cleaned:
            return
        if self.stop_reason is None:
            self.stop_reason = reason if self.process.poll() is None else "already_exited"
        try:
            if self.process.poll() is None:
                self.process.send_signal(signal.SIGINT)
                self.process.wait(timeout=5)
        except (subprocess.TimeoutExpired, KeyboardInterrupt):
            # An interrupted graceful stop must still reap this owned child.
            if self.process.poll() is None:
                self.stop_escalated = True
                self.process.kill()
            self.process.wait(timeout=2)
            raise
        finally:
            if self.process.poll() is not None:
                self.reader.join(timeout=2)
                self.process.stdout.close()
                self.log.close()
                self.cleaned = True
                save(self.directory / (self.name + "-exit.json"), self.report())

    def report(self):
        text = (self.directory / (self.name + ".log")).read_text(encoding="utf-8", errors="replace")
        patterns = {
            "packet_loss": r"missing packets|dropping frame|RTP: missed|jitter buffer full|max delay reached",
            "decode": r"error while decoding|invalid data|corrupt|decode.*error|overread|No JPEG data",
            "network_protocol": r"connection refused|connection timed out|connection reset|method .* failed|Server returned|end of file|Input/output error",
        }
        lines = text.splitlines()
        errors = {key: [line for line in lines if re.search(pattern, line, re.I)]
                  for key, pattern in patterns.items()}
        return dict(pid=self.process.pid, exit_code=self.process.returncode,
                    stop_reason=self.stop_reason, forced_kill=self.stop_escalated,
                    decoded_frames=self.sample()["frames"], reader_error=self.reader_error,
                    error_counts={key: len(value) for key, value in errors.items()},
                    error_examples={key: value[:10] for key, value in errors.items()})


def healthy(client, startup=False, stall_sec=8):
    sample = client.sample()
    if sample["reader_error"]:
        raise GateError("INCONCLUSIVE", client.name + " progress: " + sample["reader_error"])
    if not sample["alive"]:
        raise GateError("INCONCLUSIVE" if startup else "FAIL", client.name + " exited unexpectedly")
    if not startup and time.monotonic() - sample["last_increase"] > stall_sec:
        raise GateError("FAIL", client.name + " stopped producing decoded frames")
    return sample["frames"]


def wait_ready(client, timeout, other=None, tick=0.25):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if other:
            healthy(other)
        if healthy(client, startup=True) >= 3:
            return
        time.sleep(tick)
    raise GateError("INCONCLUSIVE", client.name + " no decoded-frame startup evidence")


def observe(clients, seconds, directory, phase, tick=0.25, stall_sec=8):
    start = time.monotonic()
    initial = {c.name: healthy(c, stall_sec=stall_sec) for c in clients}
    deadline = start + seconds
    completed = False
    next_notice = start + 5
    try:
        with (directory / (phase + "-samples.jsonl")).open("w", encoding="utf-8") as log:
            while True:
                now = time.monotonic()
                sample = {c.name: healthy(c, stall_sec=stall_sec) for c in clients}
                log.write(json.dumps(dict(elapsed_sec=now-start, frames=sample)) + "\n")
                log.flush()
                if now >= next_notice:
                    stage(directory, "{}: {:.1f}/{:.1f}s frames={}".format(phase, now-start, seconds, sample))
                    next_notice = now + 5
                if now >= deadline:
                    break
                time.sleep(min(tick, deadline-now))
        if any(sample[name] <= initial[name] for name in initial):
            raise GateError("FAIL", phase + ": no decoded-frame increase")
        completed = True
    finally:
        final = {c.name: c.sample()["frames"] for c in clients}
        evidence = dict(duration_sec=time.monotonic()-start, initial=initial, final=final,
                        completed=completed,
                        increases={name: final[name]-initial[name] for name in initial})
        save(directory / (phase + "-result.json"), evidence)
    return evidence


def run_gate(directory, executable, post_seconds=30, startup_seconds=20,
             snapshot=board_snapshot, command_factory=ffmpeg_command,
             overlap_seconds=5, tick=0.25, stall_sec=8):
    clients = []
    result = dict(verdict="INCONCLUSIVE", reason="not completed", clients={}, url=URL)
    started = time.monotonic()
    interrupted = False
    try:
        stage(directory, "Board before: read-only SSH (15s deadline)")
        before = snapshot(directory, "before")
        result["board_before"] = before
        compare_board(before, before)
        stage(directory, "Board before verified: pid={} ticks={} watchdog={} attempts={}".format(
            before['pid'], before['start_ticks'], before['watchdog_pid'], before['attempts']))
        stage(directory, "Starting client A; waiting for decoded frames (20s deadline)")
        a = Client("A", command_factory(executable), directory, started); clients.append(a)
        wait_ready(a, startup_seconds, tick=tick)
        stage(directory, "A receiving: pid={} frames={}; starting B".format(a.process.pid, a.sample()['frames']))
        b = Client("B", command_factory(executable), directory, started); clients.append(b)
        wait_ready(b, startup_seconds, other=a, tick=tick)
        stage(directory, "Both receiving: A pid={} B pid={}; confirming overlap".format(a.process.pid, b.process.pid))
        result["overlap"] = observe(clients, overlap_seconds, directory, "overlap", tick, stall_sec)
        stage(directory, "Stopping A intentionally (SIGINT)")
        a.stop("intentional_A_disconnect_SIGINT")
        if a.stop_reason != "intentional_A_disconnect_SIGINT":
            raise GateError("FAIL", "A exited before the intended disconnect")
        result["A_exit_elapsed_sec"] = time.monotonic()-started
        result["B_at_A_exit"] = b.sample()
        stage(directory, "A exited code={}; observing B for {}s (frames={})".format(
            a.process.returncode, post_seconds, b.sample()['frames']))
        result["B_after_A"] = observe([b], post_seconds, directory, "B-after-A", tick, stall_sec)
        stage(directory, "B observation complete: {}; ending B".format(result['B_after_A']))
        b.stop("intentional_B_end_SIGINT")
        if b.stop_reason != "intentional_B_end_SIGINT":
            raise GateError("FAIL", "B exited before the intended end")
        if any(c.stop_escalated for c in clients):
            raise GateError("INCONCLUSIVE", "Client required SIGKILL after bounded SIGINT wait")
        if any(c.process.returncode not in (0, 255, -signal.SIGINT) for c in clients):
            raise GateError("INCONCLUSIVE", "Unexpected exit status during intentional SIGINT stop")
        result.update(verdict="PASS", reason="Both decoded concurrently; B decoded continuously after A exit")
    except GateError as error:
        result.update(verdict=error.verdict, reason=str(error))
        interrupted = error.kind == "SSH_INTERRUPTED"
        stage(directory, "{}: {}".format(error.verdict, error))
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        result.update(verdict="INCONCLUSIVE", reason=str(error))
    except KeyboardInterrupt:
        interrupted = True
        result.update(verdict="INCONCLUSIVE", reason="User interrupted gate")
    finally:
        stage(directory, "Cleaning up only this run's client processes")
        for client in clients:
            try:
                client.stop("gate_cleanup_SIGINT")
                result["clients"][client.name] = client.report()
                if client.reader_error and result["verdict"] == "PASS":
                    result.update(verdict="INCONCLUSIVE", reason="Progress reader failed at shutdown")
            except (OSError, subprocess.SubprocessError, KeyboardInterrupt) as error:
                result.update(verdict="INCONCLUSIVE", reason="Owned-child cleanup failed: " + str(error))
                if isinstance(error, KeyboardInterrupt):
                    interrupted = True
        for phase, key in (("overlap", "overlap"), ("B-after-A", "B_after_A")):
            evidence = directory / (phase + "-result.json")
            if evidence.is_file():
                result[key] = json.loads(evidence.read_text(encoding="utf-8"))
        result["media_verdict"] = result["verdict"]
        # Save the media evidence BEFORE any final network operation. Never show
        # a final PASS without the required post-check, or discard media evidence.
        if result["verdict"] == "PASS":
            result.update(verdict="INCONCLUSIVE", reason="Media check passed; board post-check pending")
        result["phase"] = "before_board_after"
        save(directory / "result.json", result)
        try:
            if interrupted or "board_before" not in result:
                result["board_after_skipped"] = "User interrupted or no valid pre-check; no redundant SSH retry"
                stage(directory, result["board_after_skipped"])
            else:
                stage(directory, "Board after: read-only SSH (15s deadline); media evidence already saved")
                result["board_after"] = snapshot(directory, "after")
                compare_board(result["board_before"], result["board_after"])
                if result["media_verdict"] == "PASS":
                    result.update(verdict="PASS", reason="Concurrent decoding and post-A decoding passed; board unchanged")
                stage(directory, "Board after verified unchanged")
        except (GateError, OSError, ValueError, KeyboardInterrupt) as error:
            result["board_check_error"] = str(error)
            verdict = getattr(error, "verdict", "INCONCLUSIVE")
            result.update(verdict=verdict, reason=str(error) or "Board after SSH interrupted")
            stage(directory, "Board after {}: {}".format(verdict, result['reason']))
        result["phase"] = "finished"
        result["elapsed_sec"] = time.monotonic()-started
        result["finished_utc"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        save(directory / "result.json", result)
        stage(directory, "Final M9.3: {} (media={}); result.json saved".format(result['verdict'], result['media_verdict']))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--post-seconds", type=int, default=30, choices=range(30, 121), metavar="30..120")
    args = parser.parse_args()
    # Route ordinary termination through run_gate's finally/owned-child cleanup.
    received_signal = False
    def interrupted(signum, frame):
        nonlocal received_signal
        if not received_signal:
            received_signal = True
            raise KeyboardInterrupt()
    signal.signal(signal.SIGINT, interrupted)
    signal.signal(signal.SIGTERM, interrupted)
    if hasattr(signal, "SIGHUP"):
        signal.signal(signal.SIGHUP, interrupted)
    directory = ROOT / "test-results/m9-dual-client" / (
        datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8])
    directory.mkdir(parents=True)
    print("Evidence: " + str(directory), flush=True)
    result = None
    try:
        stage(directory, "Checking native FFmpeg and SSH dependencies")
        if sys.platform != "linux":
            raise GateError("INCONCLUSIVE", "Run on Ubuntu/Linux, not the Windows host")
        executable = shutil.which("ffmpeg")
        if not executable or not shutil.which("ssh"):
            raise GateError("INCONCLUSIVE", "ffmpeg or ssh is unavailable")
        version = subprocess.run([executable, "-version"], stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT, text=True, timeout=5)
        (directory / "ffmpeg-version.txt").write_text(version.stdout, encoding="utf-8")
        if version.returncode:
            raise GateError("INCONCLUSIVE", "ffmpeg -version failed")
        result = run_gate(directory, executable, args.post_seconds)
    except (GateError, OSError, subprocess.SubprocessError, KeyboardInterrupt) as error:
        result = dict(verdict="INCONCLUSIVE", reason=str(error))
        save(directory / "result.json", result)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    print("M9.3: " + result["verdict"], flush=True)
    return {"PASS": 0, "FAIL": 1, "INCONCLUSIVE": 2}[result["verdict"]]


if __name__ == "__main__":
    sys.exit(main())
