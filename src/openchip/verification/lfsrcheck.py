"""Finite reference checks for explicitly specified right-shifting Galois LFSRs."""
from __future__ import annotations

import hashlib
import json
import re
import tempfile
from pathlib import Path

from ..contracts.schema import Contract
from .harness import run_reference

CYCLES = 4096
VERSION = "galois-request-v2-complete-scope"


def _binding(request: str) -> dict | None:
    if len(request) > 100_000:
        return None
    text = " ".join(request.split())
    if not all(re.search(p, text, re.I) for p in
               (r"Galois LFSR", r"shifts right", r"XOR", r"active high synchronous", r"positive edge of the clock")):
        return None
    if re.search(r"\b(?:XNOR|Fibonacci|left[- ]shift|zero[- ]based)\b", text, re.I):
        return None
    widths = set(re.findall(r"\b(\d{1,2})[- ]bit Galois LFSR", text, re.I))
    taps = re.findall(r"taps at bit positions ([0-9, and]+)\.", text, re.I)
    seed = re.findall(r"reset the output (\w+) to (\d{1,2})'h([0-9a-fA-F][0-9a-fA-F_]{0,31})\b", text, re.I)
    declarations = list(re.finditer(r"^\s*-\s+(input|output)\s+(\w+)\s*(?:\((\d{1,2}) bits?\))?\s*$", request, re.M))
    declared = [m.groups() for m in declarations]
    if len(widths) != 1 or len(taps) != 1 or len(seed) != 1 or len(declared) != 3:
        return None
    width = int(next(iter(widths)))
    if len(taps[0]) > 512 or re.search(r"\d{3}", taps[0]):
        return None
    positions = [int(p) for p in re.findall(r"\d+", taps[0])]
    if not 2 <= width <= 64 or not positions or len(set(positions)) != len(positions):
        return None
    if width not in positions or any(p < 1 or p > width for p in positions):
        return None
    output, seed_width, seed_hex = seed[0]
    initial = int(seed_hex.replace("_", ""), 16)
    if int(seed_width) != width or not 0 < initial < (1 << width):
        return None
    ports = {n: (d, int(w or 1)) for d, n, w in declared}
    # The supported prose names no alternate controls; do not guess their roles.
    if ports != {"clk": ("input", 1), "reset": ("input", 1), output: ("output", width)}:
        return None
    # Trusted checks may not discard unparsed behavioral clauses. Recognize the
    # complete supported request form, rather than finding keywords inside it.
    header = " ".join(request[:declarations[0].start()].split())
    if not re.fullmatch(r"I would like you to implement a module named [A-Za-z_]\w* with the following interface\. "
                        r"All input and output ports are one bit unless otherwise specified\.", header, re.I):
        return None
    if any(request[a.end():b.start()].strip() for a, b in zip(declarations, declarations[1:])):
        return None
    body = " ".join(request[declarations[-1].end():].split())
    explanation = ('A linear feedback shift register is a shift register usually with a few XOR gates to produce the next state of the shift register. '
                   'A Galois LFSR is one particular arrangement that shifts right, where a bit position with a "tap" is XORed with the LSB output bit (q[0]) '
                   'to produce its next value, while bit positions without a tap shift right unchanged.')
    if body.lower().startswith(explanation.lower()):
        body = body[len(explanation):].strip()
    expected = (f"The module should implement a {width}-bit Galois LFSR with taps at bit positions {' '.join(taps[0].split())}. "
                f"Reset should be active high synchronous, and should reset the output {output} to {seed_width}'h{seed_hex}. "
                "Assume all sequential logic is triggered on the positive edge of the clock.")
    if body.lower() != expected.lower():
        return None
    return {"clock": "clk", "reset": "reset", "output": output, "width": width,
            "seed": initial, "tap_positions": positions, "xor_mask": sum(1 << (p - 1) for p in positions)}


def _scope(request: str) -> tuple[dict | None, bool]:
    parts = re.split(r"\n\nChange request \(v\d+\): ", request)
    latest = _binding(parts[-1])
    return (latest, False) if latest else (_binding(parts[0]), len(parts) > 1)


def requires_lfsr_check(request: str) -> bool:
    return _scope(request)[0] is not None


def _compatible(contract: Contract, binding: dict) -> bool:
    cr = contract.clock_reset
    return (not contract.parameters and cr is not None and cr.clock == binding["clock"]
            and cr.reset == binding["reset"] and cr.clock_edge == "posedge"
            and cr.reset_active == "high" and cr.reset_kind == "synchronous"
            and {p.name: (p.direction.value, p.width) for p in contract.ports} ==
            {"clk": ("input", 1), "reset": ("input", 1), binding["output"]: ("output", binding["width"])})


def lfsr_properties(contract: Contract, request: str) -> str | None:
    """Complete one-step registered-output properties from the supported request."""
    b, incomplete = _scope(request)
    if b is None or incomplete or not _compatible(contract, b):
        return None
    prefix = "__oc_lfsr_"
    while any(p.name.startswith(prefix) for p in contract.ports):
        prefix = "_" + prefix
    width, output = b["width"], b["output"]
    return f"""// Request-derived Galois transition checker; no DUT-state assumptions.
module {contract.module_name}_props(input clk, input reset, input [{width-1}:0] {output});
  reg {prefix}valid = 1'b0;
  reg {prefix}reset;
  reg [{width-1}:0] {prefix}state;
  always @(posedge clk) begin
    if ({prefix}valid) begin
      if ({prefix}reset) assert({output} == {width}'h{b['seed']:x});
      else assert({output} == (({prefix}state >> 1) ^
                  ({prefix}state[0] ? {width}'h{b['xor_mask']:x} : {width}'h0)));
    end
    {prefix}state <= {output};
    {prefix}reset <= reset;
    {prefix}valid <= 1'b1;
  end
endmodule
"""


def check_lfsr(contract: Contract, request: str, reference: Path, work: Path,
               timeout_s: float = 60) -> dict:
    binding, incomplete_revision = _scope(request)
    if binding is None:
        return {"status": "not_applicable", "detail": "Outside the explicit right-shift Galois grammar."}
    result = {"status": "error", "kind": "galois_lfsr", "checker_version": VERSION,
              "binding": binding, "planned_cycles": CYCLES, "checked_cycles": 0}
    if incomplete_revision:
        return {**result, "detail": "Provide a complete updated LFSR specification before its independent check can run."}
    if not _compatible(contract, binding):
        return {**result, "detail": "Contract interface/reset cannot represent the explicit LFSR request."}
    if timeout_s <= 0:
        return {**result, "detail": "No remaining budget for the independent LFSR check."}
    work.mkdir(parents=True, exist_ok=True)
    run = Path(tempfile.mkdtemp(prefix="check-", dir=work))
    cp = run / "contract.json"
    cp.write_text(contract.model_dump_json(indent=2))
    data = run_reference(reference, cp, 0, CYCLES, run / "reference.json", timeout_s=timeout_s)
    if data.get("error") or len(data.get("outputs", [])) != CYCLES:
        return {**result, "detail": "Reference evaluation did not complete: " + str(data.get("error") or "incomplete cycle count")[:600]}
    state = binding["seed"]
    mismatches = []
    for cycle, outputs in enumerate(data["outputs"]):
        actual = outputs.get(binding["output"])
        if actual != state and len(mismatches) < 6:
            mismatches.append({"cycle": cycle, "request_says": state, "reference_says": actual})
        state = (state >> 1) ^ (binding["xor_mask"] if state & 1 else 0)
    result.update(status="mismatch" if mismatches else "ok", checked_cycles=CYCLES,
                  mismatches=mismatches, reference_sha256=hashlib.sha256(reference.read_bytes()).hexdigest(),
                  detail=("Reference contradicts explicit right-shift Galois transitions: " + json.dumps(mismatches)
                          if mismatches else "Reference matches all checked request-derived Galois transitions."))
    (run / "result.json").write_text(json.dumps(result, indent=2))
    return result
