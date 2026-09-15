"""Deterministic acceptance guards derived from the false-acceptance analysis (docs/research).

Each guard is a cheap check of the contract against the RTL text or the request. They fire only on
contradictions that were observed to have zero false alarms across ten models' agent runs:
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
from .normalize import module_ports

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
    rst = (cr.reset or "").strip()
    if not rst or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_$]*", rst):
        return out  # no usable reset name: nothing deterministic to check
    if cr.reset_kind == "asynchronous":
        if not any(re.search(rf"\b(pos|neg)edge\s+{re.escape(rst)}\b", s) for s in sens):
            out.append(Finding("rtl", "async_reset_missing", f"The contract requires an ASYNCHRONOUS reset on `{rst}`, but no always block lists `{rst}` in its sensitivity list (expected `always @(posedge {cr.clock} or {'negedge' if cr.reset_active == 'low' else 'posedge'} {rst})`)."))
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
    if LEAK_RE.search(contract.behavior):
        out.append(Finding("contract", "behavior_leak", "The behavior text contains reasoning fragments (e.g. 'Wait,' / '???'); the intake was unsure — the contract needs the user's confirmation."))
    return out


_ALWAYS_RE = re.compile(r"always(?:_ff|_comb|_latch)?\s*(?:@\s*\(([^)]*)\))?")
_IDENT_RE = re.compile(r"\b[A-Za-z_][A-Za-z0-9_$]*\b")
_NONBLOCKING_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_$]*)\s*(?:\[[^\]]*\])?\s*<=(?!=)")
_ANY_ASSIGN_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_$]*)\s*(?:\[[^\]]*\])?\s*(?:<=(?!=)|=(?![=<>]))")
_VERILOG_KEYWORDS = frozenset("""begin end if else case casex casez endcase default posedge negedge or and not
 always assign wire reg logic integer parameter localparam module endmodule function endfunction task endtask
 for while repeat forever initial signed unsigned bit byte int input output inout""".split())


def _strip_comments(rtl: str) -> str:
    code = re.sub(r"//.*", "", rtl)
    return re.sub(r"/\*.*?\*/", "", code, flags=re.S)


def _always_blocks(code: str) -> list[tuple[str, str]]:
    """(sensitivity, body) for each always block; the body runs to the next always/endmodule/assign."""
    out: list[tuple[str, str]] = []
    starts = [(m.start(), m.end(), m.group(1) or "") for m in _ALWAYS_RE.finditer(code)]
    for i, (_, end, sens) in enumerate(starts):
        stop = starts[i + 1][0] if i + 1 < len(starts) else len(code)
        body = code[end:stop]
        cut = re.search(r"\bendmodule\b|^\s*assign\b", body, re.M)
        out.append((sens, body[: cut.start()] if cut else body))
    return out


def moore_output_findings(contract: Contract, rtl: str) -> list[Finding]:
    """A Moore output must be decoded from the state register, not flopped a second time.

    A Moore output is a combinational function of the current state: it changes in the same cycle the
    state changes. Registering that decode (`out <= (state == B);` in the clocked block) delays the
    output by one cycle, which is the single most common wrong answer on the FSM problems of
    VerilogEval v2: the RTL is otherwise exactly right and every cycle of the comparison is off by
    one. Registering the decode of the NEXT state (`out <= (next == B);`) is equivalent to the
    combinational form and is not a finding; only a value taken from a clocked register is.
    """
    if contract.fsm is None:
        return []
    code = _strip_comments(rtl)
    blocks = _always_blocks(code)
    clocked = [(sens, body) for sens, body in blocks if "edge" in sens]
    if not clocked:
        return []
    clocked_regs = {m.group(1) for _, body in clocked for m in _ANY_ASSIGN_RE.finditer(body)} - _VERILOG_KEYWORDS
    out: list[Finding] = []
    for port in contract.outputs():
        if contract.fsm.style_of(port.name) != "moore":
            continue
        for _, body in clocked:
            if not re.search(rf"\b{re.escape(port.name)}\s*(?:\[[^\]]*\])?\s*<=(?!=)", body):
                continue
            # everything that decides the assigned value: the right-hand sides and the conditions
            drivers = " ".join(re.findall(rf"\b{re.escape(port.name)}\s*(?:\[[^\]]*\])?\s*<=(?!=)([^;]*);", body))
            drivers += " " + " ".join(re.findall(r"\b(?:if|case[xz]?)\s*\(([^;]*?)\)", body))
            names = set(_IDENT_RE.findall(drivers)) - _VERILOG_KEYWORDS - {port.name}
            lagged = sorted(names & clocked_regs)
            if lagged:
                out.append(Finding("rtl", "moore_output_registered",
                                   f"Moore output {port.name} must be combinational from the state register. This RTL "
                                   f"assigns `{port.name}` with a non-blocking assignment inside a clocked always block, "
                                   f"from the CURRENT value of {', '.join('`' + n + '`' for n in lagged)}, so it appears one "
                                   f"cycle after the state it decodes. Drive it combinationally instead "
                                   f"(`assign {port.name} = (state == ...);`, or an `always @*` block); the state register "
                                   f"itself stays clocked. Registering the decode of the NEXT state value is the only "
                                   f"acceptable clocked form."))
                break
    return out


def interface_findings(contract: Contract, rtl: str) -> list[Finding]:
    """The delivered module must declare exactly the contract's ports; nothing added, nothing dropped.

    The contract's interface is the request's interface (`contracts/interface.py` locks it at intake),
    so a port here that the contract does not have is a port the user did not ask for. Measured: an
    invented `rst`/`reset` is behind 7 of 57 false acceptances, and 9 further accepted designs
    declared an interface the request did not describe (docs/research/false-acceptance-analysis.md
    section 6). Deterministic and cheap, so it runs before simulation and the difference is handed to
    the repair role by name.
    """
    declared = module_ports(rtl, contract.module_name)
    if declared is None:
        return []
    want = [p.name for p in contract.ports]
    extra = [n for n in declared if n not in want]
    missing = [n for n in want if n not in declared]
    dupes = sorted({n for n in declared if declared.count(n) > 1})
    if not extra and not missing and not dupes:
        return []
    parts = []
    if extra:
        parts.append("declares port(s) the contract does not have: " + ", ".join(f"`{n}`" for n in extra))
    if missing:
        parts.append("does not declare contract port(s): " + ", ".join(f"`{n}`" for n in missing))
    if dupes:
        parts.append("declares port(s) twice: " + ", ".join(f"`{n}`" for n in dupes))
    iface = ", ".join(f"{p.direction.value} {p.name}" for p in contract.ports)
    return [Finding("rtl", "interface_mismatch",
                    "The module header must be exactly the contract's port list, which is the interface the "
                    "request asked for. This module " + "; it ".join(parts) + ". Rewrite the module with exactly "
                    f"these ports and no others: {iface}. In particular do not add a reset or a clock the "
                    "contract does not declare, and do not drop one it does.")]
