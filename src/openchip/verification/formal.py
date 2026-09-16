"""Formal layer: bounded model checking of a model-written property checker against the RTL.

The model writes `<module>_props`, a checker module whose ports are the DUT's ports (all
inputs) plus its own shadow state, containing immediate `assert`/`assume`/`cover` statements
in `always @(posedge clk)` blocks. OpenChip generates the wrapper that instantiates DUT and
checker together and constrains reset to the first cycle. SymbiYosys runs BMC with the open
toolchain (immediate assertions only; concurrent SVA is not supported without Verific).

Results are classified as bounded_pass (at the stated depth), counterexample, timeout,
unknown, or error. A bounded pass is not a proof.
"""
from __future__ import annotations

import re
from pathlib import Path

from ..contracts.schema import Contract
from ..tools import sby as sbytool
from ..tools.base import ToolResult, run_tool, tool_version


def checker_name(contract: Contract) -> str:
    return f"{contract.module_name}_props"


def generate_formal_top(contract: Contract) -> str:
    cr = contract.clock_reset
    rst_on = "1'b1" if cr.reset_active == "high" else "1'b0"
    L = ["module formal_top(", "  input " + cr.clock + ","]
    din = contract.data_inputs()
    outs = contract.outputs()
    for p in din:
        L.append(f"  input [{p.width - 1}:0] {p.name},")
    L[-1] = L[-1].rstrip(",")
    L.append(");")
    L.append(f"  reg {cr.reset};")
    # Reset is held for the first two cycles: the formal initial state is unconstrained, the first edge
    # establishes the reset state and the second is a stable reset cycle. Clocked immediate assertions
    # sample the values just before the edge (i.e. the previous step), so BMC skips steps 0-1 (`skip 2`).
    L.append("  reg [1:0] init = 2'b11;")
    L.append(f"  always @(posedge {cr.clock}) init <= {{init[0], 1'b0}};")
    L.append(f"  always @* {cr.reset} = init[1] ? {rst_on} : ~{rst_on};")
    for p in outs:
        L.append(f"  wire [{p.width - 1}:0] {p.name};")
    params = contract.param_defaults()
    pstr = (" #(" + ", ".join(f".{k}({v})" for k, v in params.items()) + ")") if params else ""
    conns = ", ".join([f".{cr.clock}({cr.clock})", f".{cr.reset}({cr.reset})"] + [f".{p.name}({p.name})" for p in din + outs])
    L.append(f"  {contract.module_name}{pstr} dut ({conns});")
    L.append(f"  {checker_name(contract)}{pstr} chk ({conns});")
    L.append("endmodule")
    return "\n".join(L) + "\n"


def checker_skeleton(contract: Contract) -> str:
    """Port list the model must use for the checker module."""
    cr = contract.clock_reset
    ports = [f"input {cr.clock}", f"input {cr.reset}"]
    for p in contract.data_inputs() + contract.outputs():
        ports.append(f"input [{p.width - 1}:0] {p.name}")
    params = contract.parameters
    pstr = ("#(" + ", ".join(f"parameter {p.name} = {p.default}" for p in params) + ") ") if params else ""
    return f"module {checker_name(contract)} {pstr}(\n  " + ",\n  ".join(ports) + "\n);\n  // shadow state and immediate assertions here\nendmodule\n"


ACTION_BLOCK_RE = re.compile(r"(assert|assume|cover)\s*(\((?:[^()]|\([^()]*\))*\))\s*else\s*\$(?:error|display|fatal|warning|info)\s*\([^;]*\)\s*;", re.S)


def normalize_checker(text: str) -> str:
    """Rewrite SystemVerilog immediate-assertion action blocks (`assert(x) else $error(...)`) into the
    plain `assert(x);` form the open Yosys front end accepts. Concurrent SVA is left alone (rejected later)."""
    return ACTION_BLOCK_RE.sub(lambda m: f"{m.group(1)}{m.group(2)};", text)


def parse_check(props_path: Path, contract: Contract, cwd: Path, yosys: str = "yosys", timeout_s: float = 120.0) -> ToolResult:
    """Validate that the checker parses with the formal front end and declares the expected module/ports."""
    normalized = normalize_checker(props_path.read_text())
    props_path.write_text(normalized)
    if re.search(r"\b(assert|assume|cover)\s+property\b", normalized):
        r = ToolResult("yosys", [yosys], str(cwd), 1, 0.0, "", "", error="concurrent SVA (`assert property`) is not supported by the open toolchain; use immediate assert(...) inside always @(posedge clk)")
        return r
    script = f"read_verilog -formal -sv {props_path.name}; hierarchy -check -top {checker_name(contract)}; proc"
    r = run_tool("yosys", [yosys, "-q", "-p", script], cwd, timeout_s, version=tool_version(yosys, ("-V",)))
    text = props_path.read_text()
    problems = []
    if not re.search(rf"\bmodule\s+{re.escape(checker_name(contract))}\b", text):
        problems.append(f"checker must be named {checker_name(contract)}")
    if not re.search(r"\bassert\s*\(", text):
        problems.append("checker contains no assert(...)")
    if problems:
        r.error = (r.error + "; " if r.error else "") + "; ".join(problems)
    return r


def run_formal(contract: Contract, rtl_path: Path, props_path: Path, work: Path, sby: str = "sby", depth: int = 20, timeout_s: float = 600.0) -> ToolResult:
    work.mkdir(parents=True, exist_ok=True)
    top = work / "formal_top.v"
    top.write_text(generate_formal_top(contract))
    sources = [str(rtl_path.resolve()), str(props_path.resolve()), str(top.resolve())]
    sby_file = sbytool.write_sby(work, sources, "formal_top", depth)
    r = sbytool.run_bmc(sby_file, work, sby, timeout_s, inputs=sources)
    r.extra["depth"] = depth
    m = re.search(r"Assert failed in (\S+): ([^\s]+)", r.stdout + r.stderr)
    if m:
        r.extra["failed_assert"] = m.group(2)
    r.extra["diagnostics"] = [{"kind": "error", "file": "", "line": 0, "message": ln.strip()} for ln in (r.stdout + r.stderr).splitlines() if "ERROR" in ln or "Assert failed" in ln][:10]
    return r
