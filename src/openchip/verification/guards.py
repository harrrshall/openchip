"""Deterministic acceptance guards derived from the false-acceptance analysis (docs/research).

Each guard checks a bounded syntactic condition in a contract or RTL. These
heuristics are not proofs of contradiction or semantic uncertainty:
  - contract says asynchronous reset but the RTL has no reset in any sensitivity list
  - the request is combinational (contract has no clock) but the RTL is clocked
  - contract says active-low reset but the RTL never tests the reset low
  - intake reasoning leaked into the behavior text ("Wait,", "???", "Let's re-map")
Findings of kind "rtl" are repairable defects (fed to the repair loop); kind "contract" makes the
result provisional (needs the user).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from ..contracts.schema import Contract

CONST_ASSIGN_RE = re.compile(r"<=\s*(\d*'[bBdDhH][0-9a-fA-F_xXzZ?]+|\d+\b|'0|\{)")
LEAK_RE = re.compile(r"\bWait,|\?\?\?|Let'?s re-?map|Hmm,|Actually,|I think\b", re.I)


@dataclass
class Finding:
    kind: str      # "rtl" (repairable) | "contract" (needs the user)
    code: str
    message: str


def acceptance_guards(contract: Contract, rtl: str) -> list[Finding]:
    out: list[Finding] = []
    cr = contract.clock_reset
    code = re.sub(r"//.*", "", rtl)
    code = re.sub(r"/\*.*?\*/", "", code, flags=re.S)
    sens = re.findall(r"always(?:_ff|_comb|_latch)?\s*@\s*\(([^)]*)\)", code)
    clocked = any("edge" in s for s in sens)
    if cr is None:
        if clocked:
            out.append(Finding("rtl", "clocked_combinational", "The contract is purely combinational (no clock), but the RTL contains a clocked always block. Remove the clock/reset and implement the logic combinationally."))
        return out
    opposite_edge = "negedge" if cr.clock_edge == "posedge" else "posedge"
    if any(re.search(rf"\b{opposite_edge}\s+{re.escape(cr.clock)}\b", s) for s in sens):
        out.append(Finding("rtl", "clock_edge_mismatch",
                           f"The contract requires {cr.clock_edge} `{cr.clock}`, but the RTL contains an always block triggered by {opposite_edge} `{cr.clock}`."))
    rst = (cr.reset or "").strip()
    if not rst or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_$]*", rst):
        return out  # no usable reset name: nothing deterministic to check
    if cr.reset_kind == "asynchronous":
        if not any(re.search(rf"\b(pos|neg)edge\s+{re.escape(rst)}\b", s) for s in sens):
            out.append(Finding("rtl", "async_reset_missing", f"The contract requires an ASYNCHRONOUS reset on `{rst}`, but no always block lists `{rst}` in its sensitivity list (expected `always @({cr.clock_edge} {cr.clock} or {'negedge' if cr.reset_active == 'low' else 'posedge'} {rst})`)."))
    if cr.reset_active == "low":
        low_test = re.search(rf"(!\s*{re.escape(rst)}\b|~\s*{re.escape(rst)}\b|{re.escape(rst)}\s*[!=]==?\s*1'b[01]\b|{re.escape(rst)}\s*[!=]==?\s*[01]\b|negedge\s+{re.escape(rst)}\b)", code)
        # the inverted form `if (rst_n) normal-path else reset-path` also tests the reset low; it is told apart
        # from the wrong-polarity form by what the `if (rst_n)` branch does first: a constant assignment is a reset path
        inverted = False
        m = re.search(rf"if\s*\(\s*{re.escape(rst)}\s*\)\s*(?:begin)?\s*([^;]*;)", code)
        if m and re.search(r"\belse\b", code) and not CONST_ASSIGN_RE.search(m.group(1)):
            inverted = True
        if not low_test and not inverted:
            out.append(Finding("rtl", "reset_polarity", f"The contract says `{rst}` is ACTIVE-LOW, but the RTL never tests it low (no `!{rst}`, `~{rst}`, `{rst} == 0` or `negedge {rst}`)."))
    elif cr.reset_active == "high":
        if re.search(rf"\bnegedge\s+{re.escape(rst)}\b", code) or re.search(rf"if\s*\(\s*[!~]\s*{re.escape(rst)}\s*\)\s*(begin)?\s*\n[^\n]*<=\s*(1'b0|0|'0|{{)", code):
            out.append(Finding("rtl", "reset_polarity", f"The contract says `{rst}` is ACTIVE-HIGH, but the RTL treats it as active-low (negedge or `!{rst}` guarding the reset assignments)."))
    return out


def contract_guards(contract: Contract) -> list[Finding]:
    out: list[Finding] = []
    # A declared state named WAIT is ordinary design vocabulary, not an aside.
    # Exempt only an explicit reference to that declared identifier; continue
    # scanning so "In WAIT, I think ..." still records uncertainty.
    states = set()
    for declaration in re.finditer(r"\bstates?\s*:\s*([^.;\n]+)", contract.behavior, re.I):
        for entry in declaration[1].split(","):
            name = re.match(r"\s*[`\"']?([A-Za-z_][A-Za-z0-9_]*)", entry)
            if name:
                states.add(name[1])
    leaks = []
    for match in LEAK_RE.finditer(contract.behavior):
        identifier = match[0].removesuffix(",")
        prefix = contract.behavior[max(0, match.start() - 64):match.start()]
        state_reference = (identifier.lower() == "wait" and identifier in states and
                           re.search(r"\b(?:in|from|to|state)\s+[`\"']?$", prefix, re.I))
        if not state_reference:
            leaks.append(match)
    if leaks:
        out.append(Finding("contract", "behavior_leak", "The behavior text contains reasoning fragments (e.g. 'Wait,' / '???'); the intake was unsure — the contract needs the user's confirmation."))
    return out
