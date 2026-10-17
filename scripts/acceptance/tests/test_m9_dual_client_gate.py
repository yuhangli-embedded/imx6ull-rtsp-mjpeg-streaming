"""Offline tests; dynamic child processes only. No camera, SSH or real FFmpeg."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "m9_dual_client_gate.py"
spec = importlib.util.spec_from_file_location("gate", SCRIPT)
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)

FAKE = r'''
import signal, sys, time
from pathlib import Path
name, mode, marker, stopfile = sys.argv[1:]
def stop(*args):
    if name == 'A': Path(marker).write_text('A exited')
    sys.exit(0)
signal.signal(signal.SIGINT, stop)
print('Fake offline decoder', file=sys.stderr, flush=True)
count = 0
while True:
    if Path(stopfile).exists(): stop()
    after = Path(marker).exists()
    if name == 'B' and after and mode == 'exit': sys.exit(0)
    if mode != 'no_frames' and not (name == 'B' and after and mode == 'stall'):
        count += 1
        print('frame=' + str(count), flush=True)
        print('progress=continue', flush=True)
    time.sleep(0.02)
'''

SNAPSHOT = """LP2: running pid=4242 start_ticks=100 executable=/opt/lp2-media/releases/m7.2-20261013-r1/bin/lp2_rtsp_server
desired=running locked=0 attempts=1
Watchdog identity verified pid=4343
WDSTAT=4343 (wd (helper)) S 1 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 1 0 101 0 0
BOOT=11111111-2222-4333-8444-555555555555
PROBE=4242,100,12,1024,2048,1024,5,S
"""


class GateTests(unittest.TestCase):
    def setUp(self):
        base = gate.ROOT / "test-results/m9-dual-client-selftests"
        base.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=base)
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)

    def test_parse_identity_and_parenthesized_comm(self):
        sample = gate.parse_snapshot(SNAPSHOT)
        self.assertEqual((sample['pid'], sample['start_ticks']), (4242, 100))
        self.assertEqual(sample['watchdog_ticks'], 101)

    def test_incomplete_or_racing_snapshot(self):
        for text in ("", SNAPSHOT.replace('PROBE=4242,', 'PROBE=9999,'),
                     SNAPSHOT.replace('WDSTAT=4343', 'WDSTAT=4344')):
            with self.assertRaises(gate.GateError) as caught:
                gate.parse_snapshot(text)
            self.assertEqual(caught.exception.verdict, 'INCONCLUSIVE')

    def test_restart_lock_attempt_and_watchdog_change_fail(self):
        before = gate.parse_snapshot(SNAPSHOT)
        for key in ('pid', 'start_ticks', 'watchdog_ticks', 'attempts', 'locked'):
            after = dict(before)
            after[key] += 1
            with self.assertRaises(gate.GateError) as caught:
                gate.compare_board(before, after)
            self.assertEqual(caught.exception.verdict, 'FAIL')

    def test_command_decodes_without_gui_or_frame_duplication(self):
        cmd = gate.ffmpeg_command('/usr/bin/ffmpeg')
        self.assertIn('-nostdin', cmd)
        self.assertNotIn('copy', cmd)
        self.assertEqual(cmd[cmd.index('-vsync') + 1], '0')
        self.assertEqual(cmd[cmd.index('-rtsp_transport') + 1], 'udp')
        self.assertIn('pipe:1', cmd)

    def simulate(self, mode='normal', change_board=False, ssh_failure=False, interrupt=False,
                 after_error=None):
        fake = self.directory / 'fake_decoder.py'
        fake.write_text(FAKE, encoding='utf-8')
        created = []
        original_popen = subprocess.Popen

        class TestProcess(original_popen):
            def send_signal(self, sig):
                if os.name == 'nt':
                    # Windows cannot deliver POSIX SIGINT to this detached Python.
                    # Only emulate that transport; real processes/progress/exit still run.
                    Path(self.args[-1]).write_text('test SIGINT', encoding='ascii')
                else:
                    super().send_signal(sig)

        def command(_):
            name = 'AB'[len(created)]
            created.append(name)
            return [sys.executable, '-u', str(fake), name, mode,
                    str(self.directory / 'A-ended'), str(self.directory / (name + '-signal'))]

        def snapshot(directory, label):
            if ssh_failure:
                raise gate.GateError('INCONCLUSIVE', 'simulated SSH failure')
            data = gate.parse_snapshot(SNAPSHOT)
            if label == 'after' and after_error:
                # The completed media evidence must exist before final SSH.
                checkpoint = json.loads((directory / 'result.json').read_text())
                self.assertEqual(checkpoint['media_verdict'], 'PASS')
                self.assertEqual(checkpoint['verdict'], 'INCONCLUSIVE')
                raise after_error
            if label == 'after' and change_board:
                data['attempts'] += 1
            return data

        original_observe = gate.observe
        def observe(*args, **kwargs):
            if interrupt and args[3] == 'B-after-A':
                raise KeyboardInterrupt()
            return original_observe(*args, **kwargs)

        with patch.object(gate.subprocess, 'Popen', TestProcess), \
                patch.object(gate, 'observe', observe):
            result = gate.run_gate(self.directory, sys.executable, post_seconds=0.6,
                                   startup_seconds=0.4 if mode == 'no_frames' else 3, snapshot=snapshot,
                                   command_factory=command, overlap_seconds=0.25,
                                   tick=0.02, stall_sec=0.2)
        self.assertTrue((self.directory / 'result.json').is_file())
        for name in created:
            self.assertIsNotNone(result['clients'][name]['exit_code'])
            self.assertFalse(result['clients'][name]['forced_kill'])
        return result

    def test_independent_real_children_b_increases_after_a_exit(self):
        result = self.simulate()
        self.assertEqual(result['verdict'], 'PASS')
        self.assertNotEqual(result['clients']['A']['pid'], result['clients']['B']['pid'])
        self.assertGreaterEqual(result['B_after_A']['duration_sec'], 0.6)
        self.assertGreater(result['B_after_A']['increases']['B'], 0)
        self.assertGreater(result['overlap']['increases']['A'], 0)
        self.assertGreater(result['overlap']['increases']['B'], 0)
        self.assertEqual(result['clients']['A']['stop_reason'], 'intentional_A_disconnect_SIGINT')
        self.assertEqual(result['clients']['B']['exit_code'], 0)

    def test_b_exits_zero_after_a_is_failure(self):
        result = self.simulate('exit')
        self.assertEqual(result['verdict'], 'FAIL')
        self.assertEqual(result['clients']['B']['exit_code'], 0)

    def test_b_alive_but_no_frames_is_failure(self):
        result = self.simulate('stall')
        self.assertEqual(result['verdict'], 'FAIL')
        self.assertIn('stopped producing', result['reason'])
        self.assertFalse(result['B_after_A']['completed'])
        self.assertIn('initial', result['B_after_A'])
        self.assertIn('final', result['B_after_A'])

    def test_new_watchdog_attempt_overrides_receiving_success(self):
        self.assertEqual(self.simulate(change_board=True)['verdict'], 'FAIL')

    def test_ssh_failure_not_pass(self):
        result = self.simulate(ssh_failure=True)
        self.assertEqual(result['verdict'], 'INCONCLUSIVE')
        self.assertEqual(result['clients'], {})

    def test_startup_without_frames_times_out_and_reaps_child(self):
        result = self.simulate('no_frames')
        self.assertEqual(result['verdict'], 'INCONCLUSIVE')
        self.assertIn('no decoded-frame', result['reason'])
        self.assertEqual(result['clients']['A']['decoded_frames'], 0)
        self.assertNotIn('B', result['clients'])

    def test_user_interrupt_reaps_children_without_new_ssh(self):
        result = self.simulate(interrupt=True)
        self.assertEqual(result['verdict'], 'INCONCLUSIVE')
        self.assertEqual(result['reason'], 'User interrupted gate')
        self.assertEqual(result['clients']['B']['stop_reason'], 'gate_cleanup_SIGINT')
        self.assertIn('board_after_skipped', result)
        self.assertNotIn('board_after', result)

    def test_after_ssh_timeout_preserves_media_evidence(self):
        result = self.simulate(after_error=gate.GateError('INCONCLUSIVE', 'SSH timed out', 'SSH_TIMEOUT'))
        self.assertEqual(result['verdict'], 'INCONCLUSIVE')
        self.assertEqual(result['media_verdict'], 'PASS')
        self.assertGreater(result['B_after_A']['increases']['B'], 0)
        self.assertIn('board_check_error', result)

    def test_after_ssh_interrupt_saves_final_result(self):
        result = self.simulate(after_error=KeyboardInterrupt())
        self.assertEqual(result['verdict'], 'INCONCLUSIVE')
        self.assertEqual(result['phase'], 'finished')
        self.assertEqual(result['media_verdict'], 'PASS')

    def test_ssh_options_noninteractive_without_discarding_script_stdin(self):
        command = gate.ssh_command()
        for value in ('BatchMode=yes', 'ConnectTimeout=5', 'StrictHostKeyChecking=yes',
                      'NumberOfPasswordPrompts=0', 'RequestTTY=no', 'StdinNull=no',
                      'ControlPath=none', 'ProxyCommand=none'):
            self.assertIn(value, command)
        self.assertNotIn('-n', command)
        self.assertEqual(command[-1], 'sh -s')

    def test_before_ssh_timeout_does_not_start_clients_or_retry_ssh(self):
        calls = []
        def snapshot(directory, label):
            calls.append(label)
            raise gate.GateError('INCONCLUSIVE', 'before deadline exceeded', 'SSH_TIMEOUT')
        result = gate.run_gate(self.directory, 'must-not-run', snapshot=snapshot)
        self.assertEqual(calls, ['before'])
        self.assertEqual(result['verdict'], 'INCONCLUSIVE')
        self.assertEqual(result['clients'], {})
        self.assertTrue((self.directory / 'result.json').is_file())

    def test_local_transport_reads_script_to_eof_and_keeps_outputs(self):
        command = [sys.executable, '-u', '-c',
                   "import sys; print(sys.stdin.read()); print('probe stderr', file=sys.stderr)"]
        output = gate.run_ssh(self.directory, 'local', 'finite script\n', command=command)
        self.assertIn('finite script', output)
        self.assertIn('probe stderr', (self.directory / 'local-ssh.stderr').read_text())
        self.assertEqual(json.loads((self.directory / 'local-ssh-result.json').read_text())['exit_code'], 0)

    def test_real_sleeping_transport_timeout_is_bounded_and_reaped(self):
        children = []
        original = subprocess.Popen
        def create(*args, **kwargs):
            child = original(*args, **kwargs)
            children.append(child)
            return child
        command = [sys.executable, '-u', '-c',
                   "import sys,time; print('partial output',flush=True); print('partial error',file=sys.stderr,flush=True); time.sleep(20)"]
        start = time.monotonic()
        with patch.object(gate.subprocess, 'Popen', create):
            with self.assertRaises(gate.GateError) as caught:
                gate.run_ssh(self.directory, 'timeout', 'script', timeout_sec=0.4, command=command)
        self.assertEqual(caught.exception.verdict, 'INCONCLUSIVE')
        self.assertEqual(caught.exception.kind, 'SSH_TIMEOUT')
        self.assertLess(time.monotonic()-start, 3)
        self.assertIsNotNone(children[0].poll())
        self.assertIn('partial output', (self.directory / 'timeout-board.txt').read_text())
        self.assertIn('partial error', (self.directory / 'timeout-ssh.stderr').read_text())
        self.assertEqual(json.loads((self.directory / 'timeout-ssh-result.json').read_text())['outcome'], 'timeout')

    def test_transport_interrupt_kills_owned_child_and_records_reason(self):
        original = subprocess.Popen
        children = []
        class InterruptProcess(original):
            interrupted = False
            def wait(self, timeout=None):
                if not self.interrupted:
                    self.interrupted = True
                    time.sleep(0.1)
                    raise KeyboardInterrupt()
                return super().wait(timeout=timeout)
        def create(*args, **kwargs):
            child = InterruptProcess(*args, **kwargs)
            children.append(child)
            return child
        with patch.object(gate.subprocess, 'Popen', create):
            with self.assertRaises(gate.GateError) as caught:
                gate.run_ssh(self.directory, 'interrupt', 'script', command=[
                    sys.executable, '-u', '-c', "import time; time.sleep(20)"])
        self.assertEqual(caught.exception.kind, 'SSH_INTERRUPTED')
        self.assertIsNotNone(children[0].poll())
        self.assertEqual(json.loads((self.directory / 'interrupt-ssh-result.json').read_text())['outcome'], 'interrupted')

    def test_ssh_auth_failure_is_inconclusive_with_stderr(self):
        with self.assertRaises(gate.GateError) as caught:
            gate.run_ssh(self.directory, 'auth', 'script', command=[sys.executable, '-c',
                "import sys; print('Permission denied (publickey)',file=sys.stderr); sys.exit(255)"])
        self.assertEqual(caught.exception.verdict, 'INCONCLUSIVE')
        self.assertIn('Permission denied', str(caught.exception))

    def test_malformed_progress_is_inconclusive(self):
        class Fake:
            name = 'B'
            def sample(self):
                return dict(alive=True, reader_error='bad frame counter')
        with self.assertRaises(gate.GateError) as caught:
            gate.healthy(Fake())
        self.assertEqual(caught.exception.verdict, 'INCONCLUSIVE')


if __name__ == '__main__':
    unittest.main()
