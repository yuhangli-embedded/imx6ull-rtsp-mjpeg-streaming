#!/usr/bin/env python3
"""Six offline C++ checks. Windows results are NOT a native Linux CMake Gate."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cxx', default='g++')
    args = parser.parse_args()
    compiler = shutil.which(args.cxx)
    if not compiler:
        parser.error('Native offline C++ compiler unavailable')
    parent = ROOT / '_validation/portable'
    parent.mkdir(parents=True, exist_ok=True)
    out = Path(tempfile.mkdtemp(prefix='run-', dir=str(parent)))
    temp = ROOT / '_validation/temp'
    temp.mkdir(parents=True, exist_ok=True)
    # Relative ASCII output/temp paths avoid Windows GCC's Unicode argv issues.
    environment = dict(os.environ, TEMP='_validation/temp', TMP='_validation/temp', TMPDIR='_validation/temp')
    includes = ['m5_rtsp_server/include', 'm3_frame_pipeline/include',
                'm4_mjpeg_filesink/include', 'm4_rtp_jpeg/include', 'm4_rtp_jpeg_check/include']
    pool = ['m5_rtsp_server/src/fanout_frame_pool.cpp', 'm3_frame_pipeline/src/frame_pool.cpp',
            'm3_frame_pipeline/src/bounded_frame_queue.cpp']
    codec = ['m4_rtp_jpeg/src/rtp_jpeg.cpp', 'm4_rtp_jpeg_check/src/jpeg_rtp_inspector.cpp',
             'm4_rtp_jpeg_check/src/rfc2435_huffman.cpp']
    fixture = ['tests/fixtures/synthetic_720p.jpg']
    jobs = [
        ('protocol', ['m5_rtsp_server/tests/rtsp_protocol_tests.cpp', 'm5_rtsp_server/src/rtsp_protocol.cpp'], []),
        ('wire', ['m5_rtsp_server/tests/rtsp_rtp_tests.cpp'] + codec, fixture),
        ('ownership', ['m5_rtsp_server/tests/fanout_frame_pool_tests.cpp'] + pool, []),
        ('isolation', ['m5_rtsp_server/tests/slow_client_session_tests.cpp',
                       'm5_rtsp_server/src/rtsp_client_session.cpp'] + pool, []),
        ('packetizer', ['m4_rtp_jpeg/tests/rtp_jpeg_tests.cpp'] + codec, fixture),
        ('inspector', ['m4_rtp_jpeg_check/tests/jpeg_rtp_tests.cpp',
                       'm4_rtp_jpeg_check/src/jpeg_rtp_inspector.cpp',
                       'm4_rtp_jpeg_check/src/rfc2435_huffman.cpp'], fixture),
    ]
    results = []
    for name, sources, arguments in jobs:
        binary = out / (name + ('.exe' if os.name == 'nt' else ''))
        print('Building ' + name, flush=True)
        objects = []
        for index, source in enumerate(sources):
            obj = str((out / (name + '-' + str(index) + '.o')).relative_to(ROOT))
            command = [compiler, '-std=c++11', '-Wall', '-Wextra', '-Wpedantic', '-Werror', '-pthread', '-pipe']
            command += ['-I' + path for path in includes] + ['-c', source, '-o', obj]
            subprocess.run(command, cwd=str(ROOT), env=environment, check=True, timeout=120)
            objects.append(obj)
        subprocess.run([compiler, '-pthread'] + objects + ['-o', str(binary.relative_to(ROOT))],
                       cwd=str(ROOT), env=environment, check=True, timeout=120)
        result = subprocess.run([str(binary)] + arguments, cwd=str(ROOT), env=environment,
                                capture_output=True, text=True, timeout=20)
        (out / (name + '.log')).write_text(result.stdout + result.stderr, encoding='utf-8')
        print(result.stdout, end='', flush=True)
        result.check_returncode()
        results.append(dict(name=name, exit_code=result.returncode))
    (out / 'result.json').write_text(json.dumps(dict(platform=os.name, checks=results), indent=2)+'\n')
    print('Portable checks: 6/6 PASS; logs=' + str(out))


if __name__ == '__main__':
    main()
