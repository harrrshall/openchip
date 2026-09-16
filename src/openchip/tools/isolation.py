"""Fail-closed EDA execution in a private filesystem and network namespace."""
from __future__ import annotations

import contextlib
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile

from ..verification.sandbox import ENV, _base

LIMIT = 512 * 1024**2
MAX_FILES = 20000


def _copy_tree(source: Path, destination: Path) -> None:
    """Copy regular artifacts only; never follow a tool-created link onto the host."""
    total = count = 0
    for root, dirs, files in os.walk(source, followlinks=False):
        for name in dirs + files:
            path = Path(root) / name
            info = path.lstat()
            if not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
                raise ValueError(f"Unsafe sandbox artifact: {path.relative_to(source)}")
            count += 1
            total += info.st_size if stat.S_ISREG(info.st_mode) else 0
            if count > MAX_FILES or total > LIMIT:
                raise ValueError("EDA artifact size/count limit exceeded")
    # Validate the complete tree before copying anything. The sandbox has exited.
    for root, dirs, files in os.walk(source, followlinks=False):
        target = destination / Path(root).relative_to(source)
        if target.is_symlink():
            raise ValueError("Refusing symlink artifact destination")
        target.mkdir(parents=True, exist_ok=True)
        for name in files:
            dst = target / name
            if dst.is_symlink() or (dst.exists() and not dst.is_file()):
                raise ValueError("Refusing nonregular artifact destination")
            shutil.copyfile(Path(root) / name, dst)


def execute(exe: str, args: list[str], cwd: Path, inputs: list[str | Path],
            timeout_s: float, stdin: str | None, env: dict[str, str] | None):
    """Return (exit code, stdout, stderr, timeout); no host execution fallback."""
    if env:
        raise ValueError("EDA environment overrides are not supported by the isolation boundary")
    cwd = cwd.resolve(strict=True)
    if cwd in (Path('/'), Path('/home'), Path('/root'), Path('/tmp')):
        raise ValueError("EDA requires a dedicated work directory")
    command, python = _base(sys.executable)
    # Replace the reference runner's working directory below.
    del command[-2:]
    # Verilator redirects diagnostics to the inert null device.
    command[command.index("/dev/null") - 1] = "--dev-bind"
    executable = Path(exe).absolute()
    runtime = executable.parent.parent
    if executable.parent.name not in ('bin', 'libexec'):
        raise ValueError("EDA executable must belong to a dedicated bin/libexec installation")
    with contextlib.ExitStack() as stack:
        scratch = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix='openchip-eda-')))
        work = scratch / 'work'
        work.mkdir()
        _copy_tree(cwd, work)
        descriptors = []
        def bind(path: Path, target: str, writable: bool = False):
            if path.is_file() and not writable:
                handle = stack.enter_context(path.open('rb'))
                descriptors.append(handle.fileno())
                command.extend(['--ro-bind-data', str(handle.fileno()), target])
            else:
                command.extend(['--bind' if writable else '--ro-bind', str(path), target])
        if runtime != Path('/usr'):
            if runtime in (Path('/'), Path('/home'), Path('/root'), Path('/tmp')):
                raise ValueError("Unsafe EDA installation prefix")
            bind(runtime, str(runtime))
        command.extend(['--symlink', 'usr/bin', '/bin', '--symlink', 'usr/sbin', '/sbin',
                        '--proc', '/proc', '--setenv', 'PATH', f'{executable.parent}:/usr/bin:/bin',
                        '--setenv', 'HOME', '/tmp'])
        bind(work, str(cwd), writable=True)
        for item in inputs:
            source = Path(item)
            if not source.is_absolute():
                source = cwd / source
            source = source.absolute()
            if source.is_relative_to(cwd):
                continue
            if source.is_symlink() or not source.is_file():
                raise ValueError('EDA input must be a regular file')
            bind(source, str(source))
        entry = Path(__file__).with_name('isolation_entry.py')
        bind(entry, '/eda-entry.py')
        command.extend(['--chdir', str(cwd), '--remount-ro', '/', '--', python, '-I',
                        '/eda-entry.py', str(max(1, int(timeout_s))), str(executable), *args])
        streams = [stack.enter_context(tempfile.TemporaryFile()) for _ in range(3)]
        stdout, stderr, input_stream = streams
        if stdin is not None:
            input_stream.write(stdin.encode())
            input_stream.seek(0)
        proc = subprocess.Popen(command, env=ENV, stdin=input_stream, stdout=stdout, stderr=stderr,
                                pass_fds=tuple(descriptors), start_new_session=True)
        timed_out = False
        try:
            proc.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            timed_out = True
            # Killing the namespace init also terminates its descendants.
            proc.kill()
            proc.wait(timeout=10)
        _copy_tree(work, cwd)
        def tail(stream):
            stream.seek(0, 2)
            stream.seek(max(0, stream.tell() - 200000))
            return stream.read().decode('utf-8', errors='replace')
        return proc.returncode, tail(stdout), tail(stderr), timed_out
