"""Typed subprocess execution for deterministic EDA tools.

Every tool invocation is recorded as a ToolResult with command, cwd, exit status, duration,
truncated output, and the tool version, so evidence can be tied to exactly what ran.
Processes run in their own process group and the whole tree is killed on timeout.
"""
from __future__ import annotations

import shutil
import subprocess
import time
from collections.abc import Iterator
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

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


def stage_verilog_sources(sources: list[str], cwd: str | Path, *, prefix: str,
                          purpose: str) -> Iterator[tuple[Path, Path]]:
    """Yield each regular source and staged copy before staging the next input."""
    work = Path(cwd)
    for index, source in enumerate(sources):
        original = Path(source)
        if not original.is_absolute():
            original = work / original
        if original.is_symlink() or not original.is_file():
            raise ValueError(f"{purpose} input must be a regular file")
        destination = work / f"openchip_{prefix}_input_{index}.v"
        if destination.is_symlink():
            raise ValueError(f"{purpose} staging destination must not be a symlink")
        if original.resolve() != destination.resolve():
            shutil.copyfile(original, destination)
        yield original, destination


def tool_version(exe: str, args: tuple[str, ...] = ("--version",)) -> str:
    path = which(exe)
    if not path:
        return ""
    try:
        r = subprocess.run([path, *args], env={"PATH": str(Path(path).parent) + ":/usr/bin:/bin", "LANG": "C.UTF-8"}, capture_output=True, text=True, timeout=20)
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
    inputs: list[str | Path] | None = None,
) -> ToolResult:
    cwd = str(cwd)
    exe = which(argv[0])
    if exe is None:
        return ToolResult(tool, argv, cwd, None, 0.0, "", "", error=f"{argv[0]} not found on PATH", version=version)
    from .isolation import execute
    t0 = time.monotonic()
    try:
        code, out, err, timed_out = execute(exe, argv[1:], Path(cwd), inputs or [], timeout_s, stdin, env)
        return ToolResult(tool, argv, cwd, code, round(time.monotonic() - t0, 3),
                          out, err, timed_out=timed_out, version=version,
                          extra={"isolation": "bubblewrap"})
    except (OSError, ValueError, subprocess.SubprocessError) as e:
        return ToolResult(tool, argv, cwd, None, round(time.monotonic() - t0, 3), "", "",
                          error=f"EDA isolation failed: {e}", version=version)
