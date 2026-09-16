"""SymbiYosys adapter for bounded model checking of immediate assertions embedded under `ifdef FORMAL.

Reports are classified explicitly: pass (bounded, at stated depth), fail (counterexample),
timeout, error/unsupported. A bounded pass is not a proof.
"""
from __future__ import annotations

from pathlib import Path

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
    names = [Path(s).name for s in sources]
    cfg = SBY_TEMPLATE.format(depth=depth, solver=solver, files=" ".join(names), top=top, file_list="\n".join(str(Path(s).resolve()) for s in sources))
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
