"""Typed subprocess execution for deterministic EDA tools.

Every tool invocation is recorded as a ToolResult with command, cwd, exit status, duration,
truncated output, and the tool version, so evidence can be tied to exactly what ran.
Processes run in their own process group and the whole tree is killed on timeout.
"""
from __future__ import annotations

import os
import shutil
import signal
import subprocess
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

MAX_CAPTURE = 200_000  # characters kept per stream


@dataclass
class ToolResult:
    tool: str
    argv: list[str]
    cwd: str
    exit_code: Optional[int]
    duration_s: float
    stdout: str
    stderr: str
    timed_out: bool = False
    version: str = ""
    error: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.timed_out and not self.error

    def to_dict(self) -> dict:
        return asdict(self)

    def tail(self, n: int = 40) -> str:
        lines = (self.stdout + "\n" + self.stderr).strip().splitlines()
        return "\n".join(lines[-n:])


def which(name: str) -> Optional[str]:
    return shutil.which(name)


def tool_version(exe: str, args: tuple[str, ...] = ("--version",)) -> str:
    path = which(exe)
    if not path:
        return ""
    try:
        r = subprocess.run([path, *args], capture_output=True, text=True, timeout=20)
        out = (r.stdout or r.stderr).strip().splitlines()
        return out[0][:120] if out else ""
    except Exception as e:  # noqa: BLE001
        return f"error: {e}"


def run_tool(
    tool: str,
    argv: list[str],
    cwd: str | Path,
    timeout_s: float = 300.0,
    env: Optional[dict[str, str]] = None,
    version: str = "",
    stdin: Optional[str] = None,
) -> ToolResult:
    cwd = str(cwd)
    exe = which(argv[0])
    if exe is None:
        return ToolResult(tool, argv, cwd, None, 0.0, "", "", error=f"{argv[0]} not found on PATH", version=version)
    full_env = {**os.environ, **(env or {})}
    t0 = time.monotonic()
    timed_out = False
    try:
        proc = subprocess.Popen(
            [exe, *argv[1:]],
            cwd=cwd,
            env=full_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
            text=True,
            start_new_session=True,
        )
    except OSError as e:
        return ToolResult(tool, argv, cwd, None, 0.0, "", "", error=str(e), version=version)
    try:
        out, err = proc.communicate(input=stdin, timeout=timeout_s)
    except subprocess.TimeoutExpired:
        timed_out = True
        _kill_tree(proc)
        out, err = proc.communicate()
    dur = time.monotonic() - t0
    return ToolResult(
        tool=tool,
        argv=argv,
        cwd=cwd,
        exit_code=proc.returncode,
        duration_s=round(dur, 3),
        stdout=(out or "")[-MAX_CAPTURE:],
        stderr=(err or "")[-MAX_CAPTURE:],
        timed_out=timed_out,
        version=version,
    )


def _kill_tree(proc: subprocess.Popen) -> None:
    try:
        os.killpg(proc.pid, signal.SIGTERM)
        try:
            proc.wait(timeout=5)
            return
        except subprocess.TimeoutExpired:
            pass
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
