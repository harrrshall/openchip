"""Generic self-checking Verilog testbench generated from the contract (not from the model).

Vectors come from the reference model. Each cycle: drive inputs at negedge, settle, compare
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
    with open(path_in, "w") as f:
        for cyc in vec["inputs"]:
            word = 0
            for p in din:
                word = (word << p.width) | (cyc[p.name] & ((1 << p.width) - 1))
            f.write(f"{word:x}\n")
    with open(path_out, "w") as f:
        for cyc in vec["outputs"]:
            word = 0
            for p in outs:
                word = (word << p.width) | (cyc[p.name] & ((1 << p.width) - 1))
            f.write(f"{word:x}\n")


def generate_testbench(contract: Contract, n_cycles: int, max_report: int = 20) -> str:
    if contract.clock_reset is None:
        return generate_comb_testbench(contract, n_cycles, max_report)
    cr = contract.clock_reset
    rst = (cr.reset or "").strip()
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
    L.append(f"  reg {cr.clock} = 1'b0;")
    if rst:
        L.append(f"  reg {rst} = {rst_on};")
    for p in din:
        L.append(f"  reg [{p.width - 1}:0] {p.name};  // starts X; driven at the first negedge so always @* blocks get an event")
    for p in outs:
        L.append(f"  wire [{p.width - 1}:0] {p.name};")
    L.append(f"  reg [{in_w - 1}:0] in_vec [0:{n_cycles - 1}];")
    L.append(f"  reg [{out_w - 1}:0] exp_vec [0:{n_cycles - 1}];")
    L.append(f"  reg [{out_w - 1}:0] got;")
    L.append("  integer i, mismatches, reported;")
    L.append("  reg [1023:0] vin_file, vexp_file;")
    pstr = ""
    if params:
        pstr = " #(" + ", ".join(f".{k}({v})" for k, v in params.items()) + ")"
    conns = [f".{cr.clock}({cr.clock})"]
    if rst:
        conns.append(f".{rst}({rst})")
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
    if rst:
        L.append(f"    {rst} = {rst_on};")
    L.append(f"    @(negedge {cr.clock});")
    if din:
        L.append("    {" + ", ".join(p.name for p in din) + "} = 0;")
    L.append(f"    repeat ({RESET_CYCLES}) @(posedge {cr.clock});")
    L.append(f"    for (i = 0; i < {n_cycles}; i = i + 1) begin")
    L.append(f"      @(negedge {cr.clock});")
    if rst:
        L.append(f"      {rst} = {rst_off};")
    L.append("      drive(i);")
    L.append("      #1;")
    L.append("      got = {" + ", ".join(p.name for p in outs) + "};")
    L.append("      if (got !== exp_vec[i]) begin")
    L.append("        mismatches = mismatches + 1;")
    L.append(f"        if (reported < {max_report}) begin")
    L.append("          reported = reported + 1;")
    # report per-port
    hi = out_w
    for p in outs:
        lo = hi - p.width
        L.append(f"          if ({p.name} !== exp_vec[i][{hi - 1}:{lo}]) $display(\"MISMATCH cycle=%0d port={p.name} expected=%0h got=%0h\", i, exp_vec[i][{hi - 1}:{lo}], {p.name});")
        hi = lo
    if din:
        L.append("          $display(\"  inputs: " + " ".join(f"{p.name}=%0h" for p in din) + "\", " + ", ".join(p.name for p in din) + ");")
    L.append("        end")
    L.append("      end")
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


def generate_comb_testbench(contract: Contract, n_cycles: int, max_report: int = 20) -> str:
    """Combinational DUT: apply each vector, settle, compare."""
    din = contract.data_inputs()
    outs = contract.outputs()
    in_w = max(1, sum(p.width for p in din))
    out_w = sum(p.width for p in outs)
    params = contract.param_defaults()
    L = ["`timescale 1ns/1ps", f"module tb_{contract.module_name};"]
    for p in din:
        L.append(f"  reg [{p.width - 1}:0] {p.name};")
    for p in outs:
        L.append(f"  wire [{p.width - 1}:0] {p.name};")
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
    L.append("      got = {" + ", ".join(p.name for p in outs) + "};")
    L.append("      if (got !== exp_vec[i]) begin")
    L.append("        mismatches = mismatches + 1;")
    L.append(f"        if (reported < {max_report}) begin")
    L.append("          reported = reported + 1;")
    hi = out_w
    for p in outs:
        lo = hi - p.width
        L.append(f"          if ({p.name} !== exp_vec[i][{hi - 1}:{lo}]) $display(\"MISMATCH cycle=%0d port={p.name} expected=%0h got=%0h\", i, exp_vec[i][{hi - 1}:{lo}], {p.name});")
        hi = lo
    if din:
        L.append("          $display(\"  inputs: " + " ".join(f"{p.name}=%0h" for p in din) + "\", " + ", ".join(p.name for p in din) + ");")
    L.append("        end")
    L.append("      end")
    L.append("    end")
    L.append(f"    if (mismatches == 0) $display(\"RESULT PASS cycles={n_cycles}\");")
    L.append(f"    else $display(\"RESULT FAIL mismatches=%0d cycles={n_cycles}\", mismatches);")
    L.append("    $finish;")
    L.append("  end")
    L.append("endmodule")
    return "\n".join(L) + "\n"


def dump_contract_json(contract: Contract, path: Path) -> None:
    path.write_text(json.dumps(contract.model_dump(mode="json"), indent=1))
