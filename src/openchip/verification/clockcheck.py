"""Independent finite checks for an explicitly specified conventional BCD clock.

The supported prose/interface grammar is deliberately conservative. This is not
a classifier for arbitrary timekeeping circuits and never guesses missing wiring.
"""
from __future__ import annotations

import hashlib
import json
import re
import tempfile
import time
from pathlib import Path

from ..config import Config
from ..contracts.schema import Contract
from ..tools import iverilog
from .rtl_policy import check_rtl

CYCLES = 200_000


def _binding(request: str) -> dict[str, str] | None:
    text = " ".join(request.split())
    if not re.search(r"\b12[- ]hour clock\b", text, re.I) or "positive edge" not in text.lower():
        return None
    digits = re.search(r"\b(\w+),\s*(\w+),?\s+and\s+(\w+)\s+are two BCD\b", text, re.I)
    pm = re.search(r'\bsignal ["`]?([A-Za-z_]\w*)["`]? is asserted if the clock is PM\b', text, re.I)
    enable = re.search(r"\bpulse on ([A-Za-z_]\w*)\b", text, re.I)
    clock = re.search(r"\bclocked by (?:a )?(?:fast-running )?([A-Za-z_]\w*)\b", text, re.I)
    reset = re.search(r'\b([A-Za-z_]\w*) is the active high synchronous signal that resets the clock to ["`]?12:00 AM', text, re.I)
    if not all((digits, pm, enable, clock, reset)):
        return None
    declared = re.findall(r"^\s*-\s+(input|output)\s+([A-Za-z_]\w*)\s*(?:\((\d+) bits?\))?\s*$", request, re.M)
    by_lower = {name.lower(): name for _, name, _ in declared}
    raw = dict(zip(("hh", "mm", "ss"), digits.groups()))
    raw.update(pm=pm[1], enable=enable[1], clock=clock[1], reset=reset[1])
    if any(name.lower() not in by_lower for name in raw.values()):
        return None
    binding = {role: by_lower[name.lower()] for role, name in raw.items()}
    if len(set(binding.values())) != 7 or len(declared) != 7:
        return None
    expected = {binding[k]: ("input" if k in {"clock", "reset", "enable"} else "output",
                              8 if k in {"hh", "mm", "ss"} else 1) for k in binding}
    if {n: (d, int(w or 1)) for d, n, w in declared} != expected:
        return None
    return binding


def _scope(request: str) -> tuple[dict[str, str] | None, bool]:
    parts = re.split(r"\n\nChange request \(v\d+\): ", request)
    latest = _binding(parts[-1])
    if latest:
        return latest, False
    return _binding(parts[0]), len(parts) > 1


def requires_clock_check(request: str) -> bool:
    return _scope(request)[0] is not None


def check_clock(contract: Contract, request: str, rtl: Path, work: Path,
                cfg: Config, timeout_s: float = 60) -> dict:
    binding, incomplete_revision = _scope(request)
    if binding is None:
        return {"status": "not_applicable", "detail": "Request is outside the explicit standard-clock grammar."}
    result = {"status": "error", "kind": "standard_12h_clock", "binding": binding,
              "planned_cycles": CYCLES, "checked_cycles": 0}
    if incomplete_revision:
        return {**result, "detail": "The clock revision needs a complete updated specification before its independent standard-clock check can run."}
    expected = {binding[k]: ("input" if k in {"clock", "reset", "enable"} else "output",
                              8 if k in {"hh", "mm", "ss"} else 1) for k in binding}
    cr = contract.clock_reset
    if ({p.name: (p.direction.value, p.width) for p in contract.ports} != expected or contract.parameters
            or cr is None or cr.clock != binding["clock"] or cr.clock_edge != "posedge" or cr.reset != binding["reset"]
            or cr.reset_active != "high" or cr.reset_kind != "synchronous"):
        return {**result, "status": "mismatch", "detail": "Contract interface or reset contradicts the explicit standard-clock request."}
    if timeout_s <= 0:
        return {**result, "detail": "No remaining budget for the required standard-clock check."}
    work.mkdir(parents=True, exist_ok=True)
    run = Path(tempfile.mkdtemp(prefix="check-", dir=work))
    signals = {"clock": "clk", "reset": "rst", "enable": "ena", "pm": "pm", "hh": "hh", "mm": "mm", "ss": "ss"}
    connections = ", ".join(f".{binding[k]}({signals[k]})" for k in signals)
    bench = run / "clock_check.v"
    top = "openchip_clock_check" if contract.module_name != "openchip_clock_check" else "_openchip_clock_check"
    bench.write_text(f"""`timescale 1ns/1ps
module {top};
reg clk=0, rst=1, ena=0;
wire pm; wire [7:0] hh,mm,ss;
integer elapsed=0, cycle, checks=0, hours24, hours12;
{contract.module_name} dut({connections});
function [7:0] bcd;
input integer value;
begin bcd=((value/10)<<4)|(value%10); end
endfunction
initial begin
  for(cycle=0;cycle<{CYCLES};cycle=cycle+1) begin
    clk=0; rst=(cycle<3 || cycle==130000); ena=(cycle%7!=0); #1;
    clk=1;
    if(rst) elapsed=0; else if(ena) elapsed=(elapsed+1)%86400;
    hours24=elapsed/3600; hours12=hours24%12;
    if(hours12==0) hours12=12;
    #1; checks=checks+1;
    if(hh!==bcd(hours12) || mm!==bcd((elapsed/60)%60) || ss!==bcd(elapsed%60) || pm!==(hours24>=12)) begin
      $display("CLOCK MISMATCH cycle=%0d elapsed_seconds=%0d expected_hh=%h expected_mm=%h expected_ss=%h expected_pm=%0d got_hh=%h got_mm=%h got_ss=%h got_pm=%b",cycle,elapsed,bcd(hours12),bcd((elapsed/60)%60),bcd(elapsed%60),(hours24>=12),hh,mm,ss,pm);
      $display("CLOCK CHECKED cycles=%0d",checks); $fatal(1);
    end
  end
  $display("CLOCK PASS cycles=%0d",checks); $finish;
end
endmodule
""")
    result.update(artifacts={"checker": str(bench), "checker_sha256": hashlib.sha256(bench.read_bytes()).hexdigest(),
                             "rtl": str(rtl), "rtl_sha256": hashlib.sha256(rtl.read_bytes()).hexdigest()})
    started = time.monotonic()
    findings, policy = check_rtl(rtl, run, cfg.tools.iverilog, min(timeout_s, cfg.tools.timeout_s))
    result["rtl_policy"] = policy
    if findings:
        result["detail"] = "Standard-clock RTL policy check failed: " + "; ".join(f["message"] for f in findings)
        (run / "evidence.json").write_text(json.dumps(result, indent=2))
        return result
    remaining = timeout_s - (time.monotonic() - started)
    if remaining <= 0:
        return {**result, "detail": "Standard-clock check exhausted its time budget during RTL preprocessing."}
    comp = iverilog.compile_verilog([str(rtl.resolve()), str(bench.resolve())], top, "sim.vvp", run,
                                    cfg.tools.iverilog, min(remaining, cfg.tools.timeout_s))
    result["compile"] = comp.to_dict()
    if not comp.ok:
        result["detail"] = "Standard-clock checker could not compile: " + comp.tail(8)
    else:
        remaining = timeout_s - (time.monotonic() - started)
        if remaining <= 0:
            result["detail"] = "Standard-clock check exhausted its time budget after compilation."
        else:
            sim = iverilog.simulate("sim.vvp", run, cfg.tools.vvp, min(remaining, cfg.tools.timeout_s))
            result["simulation"] = sim.to_dict()
            match = re.search(r"^CLOCK MISMATCH .+$", sim.stdout, re.M)
            checked = re.search(r"^CLOCK CHECKED cycles=(\d+)$", sim.stdout, re.M)
            if match and checked:
                result.update(status="mismatch", detail=match[0], checked_cycles=int(checked[1]))
            elif sim.ok and re.findall(r"^CLOCK PASS cycles=(\d+)$", sim.stdout, re.M) == [str(CYCLES)]:
                result.update(status="ok", detail="Standard 12-hour clock matched across carries, noon/midnight, reset and enable holds.", checked_cycles=CYCLES)
            else:
                result["detail"] = "Standard-clock check did not complete successfully: " + sim.tail(8)
    (run / "evidence.json").write_text(json.dumps(result, indent=2))
    return result
