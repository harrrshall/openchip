"""Icarus Verilog adapter: compile and simulate. Parses errors into a compact, model-readable form."""
from __future__ import annotations

import re
from pathlib import Path

from .base import ToolResult, run_tool, tool_version

ERR_RE = re.compile(r"^(?P<file>[^:\s]+):(?P<line>\d+):\s*(?P<kind>error|warning|sorry)?:?\s*(?P<msg>.*)$", re.I)


def compile_verilog(
    sources: list[str], top: str, out: str, cwd: str | Path, exe: str = "iverilog", timeout_s: float = 300.0,
    generation: str = "2012", defines: dict[str, str] | None = None,
) -> ToolResult:
    argv = [exe, f"-g{generation}", "-Wall", "-Wno-timescale", "-o", out, "-s", top]
    for k, v in (defines or {}).items():
        argv.append(f"-D{k}={v}")
    argv += sources
    r = run_tool("iverilog", argv, cwd, timeout_s, version=tool_version(exe, ("-V",)), inputs=sources)
    r.extra["diagnostics"] = parse_diagnostics(r.stderr + "\n" + r.stdout)
    return r


def simulate(vvp_file: str, cwd: str | Path, exe: str = "vvp", timeout_s: float = 300.0, plusargs: list[str] | None = None) -> ToolResult:
    argv = [exe, "-n", vvp_file, *(plusargs or [])]
    return run_tool("vvp", argv, cwd, timeout_s, version=tool_version(exe, ("-V",)), inputs=[vvp_file])


def parse_diagnostics(text: str) -> list[dict]:
    diags = []
    for line in text.splitlines():
        m = ERR_RE.match(line.strip())
        if m and (m.group("kind") or "error" in line.lower()):
            diags.append({"file": Path(m.group("file")).name, "line": int(m.group("line")), "kind": (m.group("kind") or "error").lower(), "message": m.group("msg").strip()})
    return diags[:50]
