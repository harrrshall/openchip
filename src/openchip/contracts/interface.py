"""Read the port list a request prints, and treat it as the authoritative interface.

A request that prints its interface ("- input clk", "- output q (3 bits)") has already decided the
module's boundary. Everything downstream is written from the contract, so a port the intake adds or
drops is never noticed again: measured, an invented `rst`/`reset` accounts for 7 of 57 false
acceptances and 9 further accepted designs violated the printed interface
(docs/research/false-acceptance-analysis.md section 6). Two runs on `Prob117_circuit9` died at
intake because the model invented a reset the request does not have.

This module does the mechanical part only. It declines unless *every* interface bullet in the
request parses, because a partially-read list would lock the contract to the wrong set.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# " - output q (3 bits)" / " - input  predict_valid," / " - inout io"
BULLET_RE = re.compile(
    r"^\s*[-*•]\s+(input|output|inout)\b(?P<rest>.*)$", re.I)
NAME_RE = re.compile(
    r"^\s*(?:wire\s+|reg\s+|logic\s+|signed\s+)*(?P<name>[A-Za-z_]\w*)\s*"
    r"(?:\(\s*(?P<width>\d+)\s*bits?\s*\))?\s*[,.;]?\s*$", re.I)
# "implement a module named TopModule with the following interface"
MODULE_NAME_RE = re.compile(r"\bmodule\s+(?:named|called)\s+`?(?P<name>[A-Za-z_]\w*)`?", re.I)
# a Verilog header printed in the request: "module TopModule (" / "module TopModule #("
MODULE_DECL_RE = re.compile(r"^\s*module\s+([A-Za-z_]\w*)\s*[(#;]", re.M)


def requested_module_name(request: str) -> str | None:
    """The module name the request asks for, or None when it does not name one.

    A request that says "a module named TopModule" has decided the module's name, and everything
    downstream is written from the contract: an intake that renames the module to `top_module`
    delivers a file nobody is looking for. 152 of the 156 VerilogEval v2 spec-to-rtl prompts name
    the module this way, and the eval reads `rtl/TopModule.v`, so a rename is a silent zero.
    """
    m = MODULE_NAME_RE.search(request)
    if m:
        return m.group("name")
    # A request that prints the module's own header has named it just as firmly: `Prob062_bugs_mux2`
    # shows `module TopModule (...)` and asks for a fixed version, and intake called it
    # `TopModule_fixed`. Only an unambiguous single declaration counts.
    decls = {d for d in MODULE_DECL_RE.findall(request)}
    return decls.pop() if len(decls) == 1 else None


@dataclass(frozen=True)
class InterfacePort:
    name: str
    direction: str  # "input" | "output" | "inout"
    width: int | None  # None when the bullet did not state a width


def parse_interface(request: str) -> tuple[InterfacePort, ...] | None:
    """The interface bullets of `request`, or None when the request does not print a readable one.

    Declining is the safe answer: the result is used to reject contracts and RTL, so a misread list
    would reject correct work.
    """
    ports: list[InterfacePort] = []
    for line in request.splitlines():
        m = BULLET_RE.match(line)
        if not m:
            continue
        n = NAME_RE.match(m.group("rest"))
        if not n:
            return None  # an interface bullet we cannot read: do not lock a partial list
        width = n.group("width")
        ports.append(InterfacePort(name=n.group("name"), direction=m.group(1).lower(),
                                   width=int(width) if width else None))
    if len(ports) < 2:
        return None
    names = [p.name for p in ports]
    if len(names) != len(set(names)):
        return None
    if not any(p.direction == "output" for p in ports):
        # A module with no output is not a module: the list was misread, or the request itself is
        # wrong. `Prob031_dff` prints "- input q" where its own reference declares `output q`;
        # locking that list gave a contract with no outputs, an unbuildable testbench and a lost
        # run. Declining hands the interface back to the model's own reading of the request.
        return None
    return tuple(ports)


def interface_violations(ports: tuple[InterfacePort, ...], declared: list[tuple[str, str, int]]) -> list[str]:
    """Human-readable differences between the requested interface and `declared` (name, direction, width).

    Width is compared only where the request states one; direction is always compared.
    """
    want = {p.name: p for p in ports}
    have = {name: (direction, width) for name, direction, width in declared}
    out: list[str] = []
    for name in have:
        if name not in want:
            out.append(f"port `{name}` is not in the request's interface list; remove it")
    for name, p in want.items():
        if name not in have:
            out.append(f"the request's interface list declares `{p.direction} {name}` but it is missing")
            continue
        direction, width = have[name]
        if direction != p.direction:
            out.append(f"port `{name}` must be an {p.direction}, not an {direction}")
        if p.width is not None and width is not None and width != p.width:
            out.append(f"port `{name}` must be {p.width} bits wide, not {width}")
    return out
