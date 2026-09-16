"""Generic self-checking Verilog testbench generated from the contract (not from the model).

Vectors come from the reference model. Each cycle: drive inputs at the inactive edge, settle, compare
all outputs to the expected pre-edge values with `!==` (so X/Z is a mismatch), then clock.
"""
from __future__ import annotations

import json
from pathlib import Path

from ..contracts.schema import Contract

RESET_CYCLES = 3


def write_vectors(vec: dict, contract: Contract, path_in: Path, path_out: Path) -> None:
    """Write $readmemh files: one hex word per cycle (inputs concatenated in port order)."""
    din = contract.data_inputs()
    outs = contract.outputs()
    for key, ports, path in (("inputs", din, path_in), ("outputs", outs, path_out)):
        with open(path, "w") as stream:
            for cycle in vec[key]:
                word = 0
                for port in ports:
                    word = (word << port.width) | (cycle[port.name] & ((1 << port.width) - 1))
                stream.write(f"{word:x}\n")


def _with_private_signals(contract: Contract, n_cycles: int, max_report: int, generate) -> str:
    """DUT port names must not collide with testbench variables or tasks."""
    prefix = "__oc_signal_"
    names = [p.name for p in contract.ports] + [p.name for p in contract.parameters]
    while any(name.startswith(prefix) for name in names):
        prefix = "_" + prefix
    aliases = {p.name: f"{prefix}{i}" for i, p in enumerate(contract.ports)}
    private = contract.model_copy(deep=True)
    for port in private.ports:
        port.name = aliases[port.name]
    if private.clock_reset:
        private.clock_reset.conditioning = [{aliases[k]: v for k, v in row.items()} for row in private.clock_reset.conditioning]
        private.clock_reset.clock = aliases[private.clock_reset.clock]
        if private.clock_reset.reset is not None:
            private.clock_reset.reset = aliases[private.clock_reset.reset]
    text = generate(private, n_cycles, max_report)
    for original, alias in aliases.items():
        # DUT connections and user-facing diagnostics retain the actual names.
        text = text.replace(f".{alias}(", f".{original}(")
        text = text.replace(f"port={alias} ", f"port={original} ")
        text = text.replace(f"{alias}=%0h", f"{original}=%0h")
    return text


def generate_testbench(contract: Contract, n_cycles: int, max_report: int = 20) -> str:
    return _with_private_signals(contract, n_cycles, max_report, _generate_testbench)


def generate_comb_testbench(contract: Contract, n_cycles: int, max_report: int = 20) -> str:
    return _with_private_signals(contract, n_cycles, max_report, _generate_comb_testbench)


def _compare_outputs(din, outs, max_report: int) -> list[str]:
    """Compare packed outputs and emit capped per-port mismatch diagnostics."""
    L = []
    L.append("      got = {" + ", ".join(p.name for p in outs) + "};")
    L.append("      if (got !== exp_vec[i]) begin")
    L.append("        mismatches = mismatches + 1;")
    L.append(f"        if (reported < {max_report}) begin")
    L.append("          reported = reported + 1;")
    hi = sum(p.width for p in outs)
    for p in outs:
        lo = hi - p.width
        L.append(f"          if ({p.name} !== exp_vec[i][{hi - 1}:{lo}]) $display(\"MISMATCH cycle=%0d port={p.name} expected=%0h got=%0h\", i, exp_vec[i][{hi - 1}:{lo}], {p.name});")
        hi = lo
    if din:
        L.append("          $display(\"  inputs: " + " ".join(f"{p.name}=%0h" for p in din) + "\", " + ", ".join(p.name for p in din) + ");")
    L.append("        end")
    L.append("      end")
    return L


def _generate_testbench(contract: Contract, n_cycles: int, max_report: int = 20) -> str:
    if contract.clock_reset is None:
        return _generate_comb_testbench(contract, n_cycles, max_report)
    cr = contract.clock_reset
    inactive_edge = "negedge" if cr.clock_edge == "posedge" else "posedge"
    initial_clock = "1'b0" if cr.clock_edge == "posedge" else "1'b1"
    din = contract.data_inputs()
    outs = contract.outputs()
    in_w = max(1, sum(p.width for p in din))
    out_w = sum(p.width for p in outs)
    rst_on = "1'b1" if cr.reset_active == "high" else "1'b0"
    rst_off = "1'b0" if cr.reset_active == "high" else "1'b1"
    params = contract.param_defaults()
    L = []
    L.append("`timescale 1ns/1ps")
    L.append(f"module tb_{contract.module_name};")
    L.append(f"  reg {cr.clock} = {initial_clock};")
    if cr.reset is not None:
        L.append(f"  reg {cr.reset} = {rst_on};")
    for p in din:
        L.append(f"  reg [{p.lsb + p.width - 1}:{p.lsb}] {p.name};  // starts X; driven at the first inactive edge so always @* blocks get an event")
    for p in outs:
        L.append(f"  wire [{p.lsb + p.width - 1}:{p.lsb}] {p.name};")
    L.append(f"  reg [{in_w - 1}:0] in_vec [0:{n_cycles - 1}];")
    L.append(f"  reg [{out_w - 1}:0] exp_vec [0:{n_cycles - 1}];")
    L.append(f"  reg [{out_w - 1}:0] got;")
    L.append("  integer i, mismatches, reported;")
    L.append("  reg [1023:0] vin_file, vexp_file;")
    pstr = ""
    if params:
        pstr = " #(" + ", ".join(f".{k}({v})" for k, v in params.items()) + ")"
    conns = [f".{cr.clock}({cr.clock})"]
    if cr.reset is not None:
        conns.append(f".{cr.reset}({cr.reset})")
    conns += [f".{p.name}({p.name})" for p in din + outs]
    L.append(f"  {contract.module_name}{pstr} dut (" + ", ".join(conns) + ");")
    L.append(f"  always #5 {cr.clock} = ~{cr.clock};")
    # unpack inputs
    L.append("  task drive; input integer k; begin")
    if din:
        L.append("    {" + ", ".join(p.name for p in din) + "} = in_vec[k];")
    L.append("  end endtask")
    L.append("  initial begin")
    L.append("    mismatches = 0; reported = 0;")
    L.append('    if (!$value$plusargs("vin=%s", vin_file)) vin_file = "vectors_in.hex";')
    L.append('    if (!$value$plusargs("vexp=%s", vexp_file)) vexp_file = "vectors_exp.hex";')
    L.append("    $readmemh(vin_file, in_vec);")
    L.append("    $readmemh(vexp_file, exp_vec);")
    if cr.reset is not None:
        L.append(f"    {cr.reset} = {rst_on};")
    L.append(f"    @({inactive_edge} {cr.clock});")
    if din:
        L.append("    {" + ", ".join(p.name for p in din) + "} = 0;")
    if cr.reset is None and cr.conditioning:
        for index, vector in enumerate(cr.conditioning):
            if index:
                L.append(f"    @({inactive_edge} {cr.clock});")
            for p in din:
                L.append(f"    {p.name} = {p.width}'h{vector[p.name]:x};")
            L.append(f"    @({cr.clock_edge} {cr.clock});")
    else:
        L.append(f"    repeat ({RESET_CYCLES}) @({cr.clock_edge} {cr.clock});")
    L.append(f"    for (i = 0; i < {n_cycles}; i = i + 1) begin")
    L.append(f"      @({inactive_edge} {cr.clock});")
    if cr.reset is not None:
        L.append(f"      {cr.reset} = {rst_off};")
    L.append("      drive(i);")
    L.append("      #1;")
    L.extend(_compare_outputs(din, outs, max_report))
    L.append("    end")
    L.append(f"    @(negedge {cr.clock});")
    L.append(f"    if (mismatches == 0) $display(\"RESULT PASS cycles={n_cycles}\");")
    L.append(f"    else $display(\"RESULT FAIL mismatches=%0d cycles={n_cycles}\", mismatches);")
    L.append("    $finish;")
    L.append("  end")
    L.append("  initial begin")
    L.append(f"    #{(n_cycles + RESET_CYCLES + 10) * 10 * 4};")
    L.append('    $display("RESULT TIMEOUT");')
    L.append("    $finish;")
    L.append("  end")
    L.append("endmodule")
    return "\n".join(L) + "\n"


def _generate_comb_testbench(contract: Contract, n_cycles: int, max_report: int = 20) -> str:
    """Combinational DUT: apply each vector, settle, compare."""
    din = contract.data_inputs()
    outs = contract.outputs()
    in_w = max(1, sum(p.width for p in din))
    out_w = sum(p.width for p in outs)
    params = contract.param_defaults()
    L = ["`timescale 1ns/1ps", f"module tb_{contract.module_name};"]
    for p in din:
        L.append(f"  reg [{p.lsb + p.width - 1}:{p.lsb}] {p.name};")
    for p in outs:
        L.append(f"  wire [{p.lsb + p.width - 1}:{p.lsb}] {p.name};")
    L.append(f"  reg [{in_w - 1}:0] in_vec [0:{n_cycles - 1}];")
    L.append(f"  reg [{out_w - 1}:0] exp_vec [0:{n_cycles - 1}];")
    L.append(f"  reg [{out_w - 1}:0] got;")
    L.append("  integer i, mismatches, reported;")
    L.append("  reg [1023:0] vin_file, vexp_file;")
    pstr = (" #(" + ", ".join(f".{k}({v})" for k, v in params.items()) + ")") if params else ""
    conns = [f".{p.name}({p.name})" for p in din + outs]
    L.append(f"  {contract.module_name}{pstr} dut (" + ", ".join(conns) + ");")
    L.append("  initial begin")
    L.append("    mismatches = 0; reported = 0;")
    L.append('    if (!$value$plusargs("vin=%s", vin_file)) vin_file = "vectors_in.hex";')
    L.append('    if (!$value$plusargs("vexp=%s", vexp_file)) vexp_file = "vectors_exp.hex";')
    L.append("    $readmemh(vin_file, in_vec);")
    L.append("    $readmemh(vexp_file, exp_vec);")
    L.append(f"    for (i = 0; i < {n_cycles}; i = i + 1) begin")
    if din:
        L.append("      {" + ", ".join(p.name for p in din) + "} = in_vec[i];")
    L.append("      #10;")
    L.extend(_compare_outputs(din, outs, max_report))
    L.append("    end")
    L.append(f"    if (mismatches == 0) $display(\"RESULT PASS cycles={n_cycles}\");")
    L.append(f"    else $display(\"RESULT FAIL mismatches=%0d cycles={n_cycles}\", mismatches);")
    L.append("    $finish;")
    L.append("  end")
    L.append("endmodule")
    return "\n".join(L) + "\n"


def dump_contract_json(contract: Contract, path: Path) -> None:
    path.write_text(json.dumps(contract.model_dump(mode="json"), indent=1))
