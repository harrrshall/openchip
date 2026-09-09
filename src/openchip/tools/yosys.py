"""Yosys adapter: generic synthesis check and cell statistics.

Reports area in the units the flow provides (generic cells). No timing claim is made: Yosys
generic synthesis is not a source of post-route frequency.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .base import ToolResult, run_tool, tool_version


def synth_generic(sources: list[str], top: str, cwd: str | Path, exe: str = "yosys", timeout_s: float = 300.0,
                  json_out: str = "synth_stat.json") -> ToolResult:
    reads = " ".join(f"read_verilog -sv {s}" for s in sources)
    script = f"{reads}; hierarchy -check -top {top}; proc; flatten; opt; memory; opt; techmap; opt; tee -q -o {json_out} stat -json; check -assert"
    argv = [exe, "-q", "-p", script]
    r = run_tool("yosys", argv, cwd, timeout_s, version=tool_version(exe, ("-V",)))
    stat_path = Path(cwd) / json_out
    if stat_path.is_file():
        try:
            data = json.loads(stat_path.read_text())
            design = data.get("design") or next(iter(data.get("modules", {}).values()), {})
            r.extra["num_cells"] = design.get("num_cells")
            r.extra["num_wires"] = design.get("num_wires")
            r.extra["cells_by_type"] = design.get("num_cells_by_type", {})
        except Exception as e:  # noqa: BLE001
            r.extra["stat_parse_error"] = str(e)
    r.extra["diagnostics"] = parse_diagnostics(r.stderr + "\n" + r.stdout)
    return r


def parse_diagnostics(text: str) -> list[dict]:
    out = []
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("ERROR:") or s.startswith("Warning:"):
            m = re.search(r"([\w./-]+\.s?v):(\d+)", s)
            out.append({"kind": "error" if s.startswith("ERROR") else "warning",
                        "file": Path(m.group(1)).name if m else "", "line": int(m.group(2)) if m else 0, "message": s})
    return out[:50]
