"""Replay the delivered RTL against the waveform printed in the request.

The dump in the request is ground truth that never passes through a model. ADR 0013 replayed it
through the Python reference, which can only observe one value per clock cycle: a transparent latch
and a falling-edge register are invisible to it, so `Prob145_circuit8` produced an unsatisfiable
check and no RTL at all, while every recorded acceptance on these two problems was false.

Simulating the RTL against the dump has neither limitation. The dump gives a value for every signal
at every printed timestamp, so this drives exactly those values and compares exactly those samples.
Each row is applied as the dump reads it: the clock moves first, then the data inputs, then the
outputs are sampled. That ordering is what the dump itself means — a signal printed at the time of
an edge is the value *after* that edge, and the edge acted on the values printed before it.

Cells printed `x` are not checked: the dump does not define them.
"""
from __future__ import annotations

import re
from pathlib import Path

from ..contracts.schema import Contract
from ..contracts.tables import WaveformTrace, parse_clocked_waveforms
from ..tools import iverilog

NS_RE = re.compile(r"^\s*(\d+)\s*ns\s*$", re.I)
SETUP = 0.2  # time units between the clock move, the data move, and the sample
MAX_REPORT = 20
MISMATCH_RE = re.compile(r"WAVE MISMATCH time=(\S+) port=(\w+) expected=(\S+) got=(\S+)(?: inputs: (.*))?")


def _times_ns(trace: WaveformTrace) -> list[int] | None:
    """The printed timestamps in nanoseconds, or None unless they are ns and strictly increasing."""
    if len(trace.times) != len(trace.samples):
        return None
    out: list[int] = []
    for t in trace.times:
        m = NS_RE.match(t)
        if not m:
            return None
        out.append(int(m.group(1)))
    if any(b - a < 1 for a, b in zip(out, out[1:])):
        return None
    return out


def generate_replay_testbench(contract: Contract, trace: WaveformTrace) -> str | None:
    """A self-checking testbench that drives `trace` into the module, or None when it does not apply."""
    cr = contract.clock_reset
    if cr is None or cr.clock != trace.clock:
        return None
    times = _times_ns(trace)
    if times is None or any(b - a <= 2 * SETUP for a, b in zip(times, times[1:])):
        return None
    ports = {p.name: p for p in contract.ports}
    if any(n not in ports for n in trace.columns if n != trace.clock):
        return None
    ins = [ports[n] for n in trace.columns if n != trace.clock and ports[n].direction == "input"]
    outs = [ports[n] for n in trace.columns if n != trace.clock and ports[n].direction == "output"]
    driven = {p.name for p in ins} | {cr.clock}
    if not outs or any(p.name not in driven for p in contract.inputs()):
        return None  # an input the dump does not pin: the replay would be driving an invented value
    col = {name: j for j, name in enumerate(trace.columns)}
    if any(s[col[p.name]] is None for s in trace.samples for p in ins):
        return None  # an undefined input: the dump does not say what to drive

    params = contract.param_defaults()
    pstr = (" #(" + ", ".join(f".{k}({v})" for k, v in params.items()) + ")") if params else ""
    L = ["`timescale 1ns/1ps", f"module tb_wave_{contract.module_name};"]
    L.append(f"  reg {cr.clock};")
    for p in ins:
        L.append(f"  reg [{p.width - 1}:0] {p.name};")
    for p in outs:
        L.append(f"  wire [{p.width - 1}:0] {p.name};")
    L.append("  integer mismatches, checks;")
    conns = [f".{cr.clock}({cr.clock})"] + [f".{p.name}({p.name})" for p in ins + outs]
    L.append(f"  {contract.module_name}{pstr} dut (" + ", ".join(conns) + ");")
    L.append("  initial begin")
    L.append("    mismatches = 0; checks = 0;")
    for k, sample in enumerate(trace.samples):
        t = times[k]
        L.append(f"    // {t}ns")
        L.append(f"    {cr.clock} = 1'b{sample[col[cr.clock]]};")
        L.append(f"    #{SETUP};")
        for p in ins:
            L.append(f"    {p.name} = {p.width}'d{sample[col[p.name]]};")
        L.append(f"    #{SETUP};")
        shown = ", ".join(f"{p.name}={sample[col[p.name]]}" for p in ins)
        for p in outs:
            want = sample[col[p.name]]
            if want is None:
                continue
            L.append("    checks = checks + 1;")
            L.append(f"    if ({p.name} !== {p.width}'d{want}) begin")
            L.append("      mismatches = mismatches + 1;")
            L.append(f"      if (mismatches <= {MAX_REPORT}) $display(\"WAVE MISMATCH time={t}ns port={p.name} "
                     f"expected={want} got=%0h inputs: {shown}\", {p.name});")
            L.append("    end")
        if k + 1 < len(times):
            L.append(f"    #{times[k + 1] - t - 2 * SETUP};")
    L.append("    if (mismatches == 0) $display(\"WAVE PASS checks=%0d\", checks);")
    L.append("    else $display(\"WAVE FAIL mismatches=%0d checks=%0d\", mismatches, checks);")
    L.append("    $finish;")
    L.append("  end")
    L.append("endmodule")
    return "\n".join(L) + "\n"


def replay_request_waveform(contract: Contract, request: str, rtl_path: Path, work: Path,
                            iverilog_exe: str = "iverilog", vvp_exe: str = "vvp",
                            timeout_s: float = 300.0) -> dict:
    """Simulate `rtl_path` against every clocked dump printed in `request`.

    `status` is not_applicable | pass | fail | error.
    """
    out: dict = {"status": "not_applicable", "checks": 0, "mismatches": [], "detail": ""}
    try:
        traces = parse_clocked_waveforms(request)
    except Exception as e:  # noqa: BLE001 — a parser fault must never fail a run
        return {**out, "status": "error", "detail": f"waveform parse failed: {type(e).__name__}: {e}"}
    benches = [(t, generate_replay_testbench(contract, t)) for t in traces]
    benches = [(t, b) for t, b in benches if b]
    if not benches:
        return out
    work.mkdir(parents=True, exist_ok=True)
    checks = 0
    mismatches: list[dict] = []
    for i, (_trace, bench) in enumerate(benches):
        tb = work / f"tb_wave_{i}.v"
        tb.write_text(bench)
        comp = iverilog.compile_verilog([str(rtl_path.resolve()), tb.name], f"tb_wave_{contract.module_name}",
                                        f"wave_{i}.vvp", work, iverilog_exe, timeout_s)
        if not comp.ok:
            return {**out, "status": "error", "detail": "the waveform replay testbench did not compile: " + comp.tail(15)}
        sim = iverilog.simulate(f"wave_{i}.vvp", work, vvp_exe, timeout_s)
        text = sim.stdout + sim.stderr
        (work / f"wave_{i}.log").write_text(text)
        m = re.search(r"WAVE (PASS|FAIL) (?:checks|mismatches)=(\d+)(?: checks=(\d+))?", text)
        if not m:
            return {**out, "status": "error", "detail": "the waveform replay produced no result line: " + sim.tail(15)}
        checks += int(m.group(3) or m.group(2))
        for mm in MISMATCH_RE.finditer(text):
            mismatches.append({"time": mm.group(1), "port": mm.group(2), "request_says": mm.group(3),
                               "rtl_says": mm.group(4), "inputs": (mm.group(5) or "").strip()})
    out.update(checks=checks, mismatches=mismatches[:MAX_REPORT],
               status="fail" if mismatches else "pass")
    if mismatches:
        out["detail"] = "; ".join(f"at {m['time']} with {m['inputs']} the request's waveform shows "
                                  f"{m['port']}={m['request_says']} but the RTL produces {m['rtl_says']}"
                                  for m in out["mismatches"][:6])
    return out
