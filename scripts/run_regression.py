#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Run the existing Blender app tests with isolated settings and a timeout."""
import argparse
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]


def positive_seconds(value):
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError('must be positive finite seconds')
    return number


def stop_process(process):
    """Stop only the launched process and its descendants, including on Ctrl-C."""
    try:
        if os.name == 'nt':
            taskkill = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32/taskkill.exe'
            subprocess.run([str(taskkill), '/PID', str(process.pid), '/T', '/F'],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
        else:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=5)


def run_isolated(command, timeout):
    """Relay child output/status; discard temporary Blender settings afterwards."""
    if os.path.dirname(command[0]):
        command = [os.path.abspath(command[0]), *command[1:]]
    with tempfile.TemporaryDirectory(prefix='sith-tests-') as temporary:
        root = Path(temporary).resolve()
        env = {key: value for key, value in os.environ.items()
               if not key.startswith('BLENDER_USER_')
               and key not in ('PYTHONPATH', 'PYTHONHOME', 'PYTHONOPTIMIZE')}
        for name in ('CONFIG', 'SCRIPTS', 'DATAFILES', 'EXTENSIONS'):
            directory = root / name.lower()
            directory.mkdir()
            env['BLENDER_USER_' + name] = str(directory)
        env.update(PYTHONDONTWRITEBYTECODE='1', PYTHONNOUSERSITE='1',
                   OMP_NUM_THREADS='2', OPENBLAS_NUM_THREADS='2', MKL_NUM_THREADS='2')
        try:
            with subprocess.Popen(command, cwd=root, env=env,
                                  start_new_session=os.name != 'nt') as process:
                try:
                    return process.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    stop_process(process)
                    print(f'Blender tests exceeded {timeout:g} seconds', file=sys.stderr)
                    return 124
                except KeyboardInterrupt:
                    stop_process(process)
                    return 130
        except OSError as error:
            print(f'Could not run Blender tests: {error}', file=sys.stderr)
            return 127


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--blender', required=True, help='Blender 5.0+ executable path or command')
    parser.add_argument('--timeout', type=positive_seconds, default=600,
                        help='Maximum test process duration in seconds (default: 600)')
    args = parser.parse_args(argv)
    return run_isolated([args.blender, '--background', '--factory-startup',
                         '--offline-mode', '--disable-autoexec', '--threads', '2',
                         '--python-exit-code', '1', '--python', str(ROOT / 'tests/run.py'),
                         '--', '--suite', 'app'], args.timeout)


if __name__ == '__main__':
    raise SystemExit(main())
