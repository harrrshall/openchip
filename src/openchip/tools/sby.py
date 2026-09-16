"""SymbiYosys adapter for bounded model checking of immediate assertions embedded under `ifdef FORMAL.

Reports are classified explicitly: pass (bounded, at stated depth), fail (counterexample),
timeout, error/unsupported. A bounded pass is not a proof.
"""
from __future__ import annotations

from pathlib import Path
import shutil
import re

from .base import ToolResult, run_tool, tool_version

SBY_TEMPLATE = """[options]
mode bmc
depth {depth}
skip 2
multiclock off

[engines]
smtbmc {solver}

[script]
read_verilog -formal -sv -noautowire {files}
prep -top {top}

[files]
{file_list}
"""


def write_sby(work: Path, sources: list[str], top: str, depth: int, solver: str = "yices") -> Path:
    if type(depth) is not int or depth < 3:
        raise ValueError("formal depth must be at least 3: initialization skips steps 0 and 1")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", top):
        raise ValueError("formal top must be an ordinary Verilog identifier")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", solver):
        raise ValueError("formal solver must be a simple executable name")
    names = []
    for index, source in enumerate(sources):
        original = Path(source)
        if not original.is_absolute():
            original = work / original
        if original.is_symlink() or not original.is_file():
            raise ValueError("formal input must be a regular file")
        destination = work / f"openchip_formal_input_{index}.v"
        if destination.is_symlink():
            raise ValueError("formal staging destination must not be a symlink")
        if original.resolve() != destination.resolve():
            shutil.copyfile(original, destination)
        names.append(destination.name)
    cfg = SBY_TEMPLATE.format(depth=depth, solver=solver, files=" ".join(names),
                              top=top, file_list="\n".join(names))
    p = work / f"{top}.sby"
    p.write_text(cfg)
    return p


def run_bmc(sby_file: Path, cwd: str | Path, exe: str = "sby", timeout_s: float = 600.0, inputs: list[str] | None = None) -> ToolResult:
    r = run_tool("sby", [exe, "-f", sby_file.name], cwd, timeout_s, version=tool_version(exe), inputs=inputs)
    text = r.stdout + r.stderr
    if r.timed_out:
        status = "timeout"
    elif "DONE (PASS" in text:
        status = "bounded_pass"
    elif "DONE (FAIL" in text or "Assert failed" in text or "BMC failed" in text:
        status = "counterexample"
    elif "DONE (UNKNOWN" in text or "UNKNOWN" in text:
        status = "unknown"
    else:
        status = "error"
    r.extra["status"] = status
    return r
