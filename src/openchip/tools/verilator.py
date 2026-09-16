"""Verilator lint adapter. `verilator --lint-only` is a strict second-opinion parser."""
from __future__ import annotations

import re
from pathlib import Path

from .base import ToolResult, run_tool, tool_version

MSG_RE = re.compile(r"^%(?P<kind>Error|Warning)(?:-(?P<code>[A-Z0-9_]+))?:\s*(?P<file>[^:]+):(?P<line>\d+):(?:\d+:)?\s*(?P<msg>.*)$")


def lint(sources: list[str], top: str, cwd: str | Path, exe: str = "verilator", timeout_s: float = 300.0,
         extra_args: list[str] | None = None) -> ToolResult:
    argv = [exe, "--lint-only", "-Wall", "-Wno-fatal", "-Wno-DECLFILENAME", "-Wno-UNUSEDPARAM", "-Wno-UNUSEDSIGNAL",
            "--top-module", top, *(extra_args or []), *sources]
    r = run_tool("verilator", argv, cwd, timeout_s, version=tool_version(exe), inputs=sources)
    r.extra["diagnostics"] = parse_diagnostics(r.stderr + "\n" + r.stdout)
    return r


def parse_diagnostics(text: str) -> list[dict]:
    out = []
    for line in text.splitlines():
        if "Exiting due to" in line:
            continue
        m = MSG_RE.match(line.strip())
        if m:
            out.append({"kind": m.group("kind").lower(), "code": m.group("code") or "", "file": Path(m.group("file")).name,
                        "line": int(m.group("line")), "message": m.group("msg").strip()})
    return out[:50]
