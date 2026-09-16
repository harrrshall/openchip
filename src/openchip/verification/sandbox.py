"""Fail-closed Linux reference execution with Bubblewrap.

Only the interpreter's installation, trusted driver, individual read-only inputs,
and one writable result inode enter the sandbox. No workspace directory, secrets,
host processes, or host network are exposed. There is no unsandboxed fallback.
"""
from __future__ import annotations

import functools
import contextlib
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ENV = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"}
ENTRY = Path(__file__).with_name("sandbox_entry.py")


@functools.lru_cache(maxsize=8)
def _runtime(python: str) -> tuple[str, str]:
    exe = str(Path(python).resolve())
    proc = subprocess.run([exe, "-I", "-c", "import sys; print(sys.base_prefix)"],
                          env=ENV, capture_output=True, text=True, timeout=10, check=True)
    prefix = Path(proc.stdout.strip()).resolve()
    if prefix in (Path("/"), Path("/home"), Path("/root"), Path("/tmp")):
        raise ValueError("Unsafe Python installation prefix for reference sandbox")
    return exe, str(prefix)


def _base(python: str) -> tuple[list[str], str]:
    # CAD bundles may put their own bwrap wrapper on PATH. Use the operating
    # system package, including its distro namespace/AppArmor integration.
    bwrap = shutil.which("bwrap", path=ENV["PATH"])
    if sys.platform != "linux" or not bwrap:
        raise ValueError("Reference isolation requires Linux and Bubblewrap (bwrap); no unsafe fallback is permitted")
    exe, prefix = _runtime(python)
    argv = [bwrap, "--unshare-all", "--die-with-parent", "--new-session",
            "--clearenv", "--setenv", "PATH", ENV["PATH"], "--setenv", "LANG", ENV["LANG"],
            "--uid", "65534", "--gid", "65534", "--cap-drop", "ALL"]
    mounts = {"/usr", "/lib", "/lib64", prefix}
    for path in sorted(mounts):
        if Path(path).exists():
            argv.extend(["--ro-bind", path, path])
    argv.extend(["--dir", "/dev", "--ro-bind", "/dev/null", "/dev/null",
                 "--ro-bind", "/dev/urandom", "/dev/urandom",
                 "--size", str(64 * 1024**2), "--tmpfs", "/tmp", "--chdir", "/tmp"])
    return argv, exe


def sandbox_status() -> dict:
    try:
        argv, exe = _base(sys.executable)
        proc = subprocess.run([*argv, "--remount-ro", "/", "--", exe, "-I", "-c", "pass"], env=ENV,
                              capture_output=True, text=True, timeout=10)
        return {"ok": proc.returncode == 0, "version": "Bubblewrap reference isolation",
                "error": proc.stderr[-500:] if proc.returncode else ""}
    except (OSError, ValueError, subprocess.SubprocessError) as e:
        return {"ok": False, "version": "", "error": str(e)}


def run_isolated(script: Path, args: list[str | Path], output: Path, *,
                 python: str = sys.executable, timeout_s: float = 180) -> subprocess.CompletedProcess:
    try:
        argv, exe = _base(python)
    except (OSError, ValueError, subprocess.SubprocessError) as e:
        return subprocess.CompletedProcess([], 125, "", str(e))
    # The child can write this inode, but never choose a host path or substitute
    # a symlink for the file subsequently read by the parent.
    with contextlib.ExitStack() as stack:
        result = stack.enter_context(tempfile.NamedTemporaryFile(prefix="openchip-reference-"))
        stdout, stderr = [stack.enter_context(tempfile.TemporaryFile()) for _ in range(2)]
        # Bubblewrap maps the caller's host uid to the sandbox uid. Keep the
        # staging file caller-owned and private, never world-writable.
        fds = []
        def bind_input(path, target):
            source = stack.enter_context(Path(path).open("rb"))
            fds.append(source.fileno())
            argv.extend(["--ro-bind-data", str(source.fileno()), target])
        bind_input(ENTRY, "/entry.py")
        bind_input(script, "/runner.py")
        argv.extend(["--bind", result.name, "/result.json"])
        mapped = []
        for index, arg in enumerate(args):
            if isinstance(arg, Path):
                if arg.resolve() == output.resolve():
                    mapped.append("/result.json")
                else:
                    target = f"/input{index}{arg.suffix}"
                    bind_input(arg, target)
                    mapped.append(target)
            else:
                mapped.append(arg)
        argv.extend(["--remount-ro", "/", "--", exe, "-I", "/entry.py", "/runner.py", *mapped])
        proc = subprocess.run(argv, env=ENV, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr,
                              pass_fds=tuple(fds), timeout=timeout_s)
        result.seek(0)
        data = result.read(64 * 1024**2 + 1)
        if len(data) > 64 * 1024**2:
            return subprocess.CompletedProcess(argv, 125, "", "Reference result exceeded size limit")
        if proc.returncode == 0 and data:
            output.write_bytes(data)
        def tail(stream):
            stream.seek(max(0, stream.tell() - 200_000))
            return stream.read().decode("utf-8", errors="replace")
        return subprocess.CompletedProcess(argv, proc.returncode, tail(stdout), tail(stderr))
