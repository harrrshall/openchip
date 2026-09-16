"""Finite tables derived from explicit combinational one-hot state diagrams.

Only complete, unambiguous request diagrams are accepted. Invalid one-hot input
words are outside the checked domain; no generated contract supplies semantics.
"""
from __future__ import annotations

import itertools
import re

from .tables import RequestTable, TableVar

_IDENT = r"[A-Za-z_]\w*"
_PORT = re.compile(rf"^\s*-\s+(input|output)\s+({_IDENT})\s*(?:\(\s*(\d+)\s*bits?\s*\))?\s*$", re.M)
_ENCODING = re.compile(rf"\((?P<states>(?:{_IDENT}\s*,\s*)+{_IDENT})\)\s*=\s*\((?P<codes>[^()]*)\)")
_EDGE = re.compile(rf"^\s*({_IDENT})\s*\(([^()]*)\)\s*--\s*(.*?)\s*-->\s*({_IDENT})\s*$")
_ASSIGN = re.compile(rf"({_IDENT})\s*=\s*([01])")


def _code(token: str, width: int) -> int | None:
    match = re.fullmatch(r"(\d+)'[bB]([01_]+)", token.strip())
    if not match or int(match[1]) != width:
        return None
    bits = match[2].replace("_", "")
    if len(bits) > width:
        return None
    value = int(bits, 2)
    return value if value and value & (value - 1) == 0 else None


def parse_state_tables(request: str) -> list[RequestTable]:
    """Recognize bounded, explicitly encoded combinational Moore/next-state tables."""
    if len(request) > 100_000 or re.search(r"\n\nChange request \(v\d+\):", request):
        return []
    prose = " ".join(request.lower().split())
    if not all(term in prose for term in ("one-hot encoding", "combinational logic portion", "assume outputs are 0")):
        return []
    declarations = [(d, n, int(w or 1)) for d, n, w in _PORT.findall(request)]
    if len({n for _, n, _ in declarations}) != len(declarations):
        return []
    vectors = [(n, w) for d, n, w in declarations if d == "input" and w > 1]
    if len(vectors) != 1:
        return []
    state_port, width = vectors[0]
    controls = [n for d, n, w in declarations if d == "input" and w == 1]
    outputs = [n for d, n, _ in declarations if d == "output"]
    if (not 2 <= width <= 16 or len(controls) > 4 or not 1 <= len(outputs) <= 16
            or any(w != 1 for d, _, w in declarations if d == "output")):
        return []
    encodings = []
    for match in _ENCODING.finditer(request):
        states = tuple(s.strip() for s in match["states"].split(","))
        tokens = [s.strip() for s in match["codes"].split(",")]
        if len(states) != width or len(set(states)) != width:
            continue
        if len(tokens) >= 4 and tokens[-2] in {"...", "…"} and 2 <= len(tokens) - 2 < width - 1:
            if ([_code(t, width) for t in tokens[:-2]] != [1 << i for i in range(len(tokens) - 2)]
                    or _code(tokens[-1], width) != 1 << (width - 1)):
                continue
            codes = tuple(1 << i for i in range(width))
        elif len(tokens) == width:
            codes = tuple(_code(t, width) for t in tokens)
            if None in codes or len(set(codes)) != width:
                continue
        else:
            continue
        encodings.append(tuple(zip(states, codes)))
    if len(set(encodings)) != 1:
        return []
    encoding = dict(encodings[0])
    next_outputs = {out: out[:-5] for out in outputs if out.endswith("_next")}
    if not next_outputs or any(state not in encoding for state in next_outputs.values()):
        return []
    moore_outputs = set(outputs) - set(next_outputs)
    edges: dict[str, list[tuple[tuple[str, int] | None, str]]] = {s: [] for s in encoding}
    values: dict[str, dict[str, int]] = {}
    for line in request.splitlines():
        if "-->" not in line:
            continue
        if re.fullmatch(r"\s*state\s*\(outputs?\)\s*--inputs?-->\s*next\s+state\s*", line, re.I):
            continue
        match = _EDGE.fullmatch(line)
        if not match:
            return []
        state, assignments, condition, target = match.groups()
        if state not in encoding or target not in encoding:
            return []
        assigned = {out: 0 for out in moore_outputs}
        seen = set()
        for part in assignments.split(",") if assignments.strip() else []:
            assignment = _ASSIGN.fullmatch(part.strip())
            if not assignment or assignment[1] not in moore_outputs or assignment[1] in seen:
                return []
            seen.add(assignment[1])
            assigned[assignment[1]] = int(assignment[2])
        if state in values and values[state] != assigned:
            return []
        values[state] = assigned
        if " ".join(condition.lower().split()) in {"always", "(always go to next cycle)"}:
            predicate = None
        else:
            cond = _ASSIGN.fullmatch(condition)
            if not cond or cond[1] not in controls:
                return []
            predicate = (cond[1], int(cond[2]))
        edges[state].append((predicate, target))
    if any(not edges[state] for state in encoding):
        return []
    inputs = tuple(TableVar(f"{state_port}[{i}]", state_port, i) for i in range(width)) + tuple(TableVar(n, n, None) for n in controls)
    rows: dict[str, list] = {out: [] for out in outputs}
    for state, word in encoding.items():
        for bits in itertools.product((0, 1), repeat=len(controls)):
            ctrl = dict(zip(controls, bits))
            targets = [target for predicate, target in edges[state]
                       if predicate is None or ctrl[predicate[0]] == predicate[1]]
            if len(targets) != 1:
                return []  # overlapping or missing transition: do not choose a priority
            vector = tuple((word >> i) & 1 for i in range(width)) + bits
            for out in outputs:
                expected = int(targets[0] == next_outputs[out]) if out in next_outputs else values[state][out]
                rows[out].append((vector, expected))
    outside_domain = ((1 << width) - width) * (1 << len(controls))
    return [RequestTable("one_hot_state_table", inputs, TableVar(out, out, None),
                         tuple(rows[out]), outside_domain, request) for out in outputs]
