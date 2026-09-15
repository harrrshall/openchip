"""Replay the contract's own FSM transition table through the Python reference model.

The reference and the RTL are both written from the contract, so a misread request produces a
reference and an RTL that agree with each other and are both wrong; simulation cannot see it
(docs/research/false-acceptance-analysis.md §5). The contract's `fsm` section states the machine as
data rather than prose, which makes one more thing checkable without a model: whether the reference
actually behaves like the table the RTL was built from.

This module walks the table from the reset state, builds a directed stimulus that drives every
listed condition from every reachable state, replays it through the reference in a subprocess
(`refrows.py`, sequence mode), and compares the outputs the table declares for that cycle with the
outputs the reference produces. A disagreement means the design's two halves were built from
different readings of the same table, so sign-off is withheld.

Everything here is conservative: a condition, an output value or a state it cannot evaluate exactly
is skipped rather than guessed, and a section it cannot use at all reports `not_applicable`.
"""
from __future__ import annotations

import ast
import itertools
import json
import keyword
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from ..contracts.schema import Contract, Direction, Fsm

REFROWS = Path(__file__).with_name("refrows.py")
MAX_REPORTED = 6
MAX_PROBES = 48            # bound the stimulus: one sequence per (state, condition)
MAX_COVERAGE_PROBES = 24   # extra sequences that drive each value of each sampled one-bit input
MAX_CANDIDATES = 4096      # bound the search for an input vector satisfying a condition
DEFAULT_CONDITIONS = {"default", "else", "otherwise", "any", "any other", "-", "*", "true", "1", "all other inputs"}


class Unparseable(Exception):
    """The expression is not a plain Verilog boolean/arithmetic expression over the ports."""


# -- expression evaluation ----------------------------------------------------------------------

_VLOG_NUM = re.compile(r"(\d+)?'([sS])?([bBoOdDhH])([0-9a-fA-F_xXzZ?]+)")
_BASE = {"b": 2, "o": 8, "d": 10, "h": 16}


def _strip_literals(expr: str) -> str:
    def sub(m: re.Match) -> str:
        digits = m.group(4).replace("_", "")
        if re.search(r"[xXzZ?]", digits):
            raise Unparseable("x/z in a literal")
        return str(int(digits, _BASE[m.group(3).lower()]))

    return _VLOG_NUM.sub(sub, expr)


# Verilog port names that are Python keywords (`in` on a UART receiver, `is`, `not`, ...) are
# renamed before parsing and renamed back in the reported names.
_KEYWORDS = frozenset(keyword.kwlist)
_KW_PREFIX = "_vkw_"
_WORD = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\b")


def mangle(name: str) -> str:
    return _KW_PREFIX + name if name in _KEYWORDS else name


def demangle(name: str) -> str:
    return name[len(_KW_PREFIX):] if name.startswith(_KW_PREFIX) else name


def to_python(expr: str) -> str:
    """Rewrite a Verilog boolean expression as Python source. Raises Unparseable."""
    e = _WORD.sub(lambda m: mangle(m.group(1)), expr)
    e = _strip_literals(e)
    e = e.replace("===", "==").replace("!==", "!=")
    e = e.replace("~", "!")
    e = e.replace("&&", " and ").replace("||", " or ")
    e = re.sub(r"!(?!=)", " not ", e)
    if re.search(r"[{}$@#]", e):
        raise Unparseable("unsupported token")
    return e


_CMP = {ast.Eq: lambda a, b: a == b, ast.NotEq: lambda a, b: a != b, ast.Lt: lambda a, b: a < b,
        ast.LtE: lambda a, b: a <= b, ast.Gt: lambda a, b: a > b, ast.GtE: lambda a, b: a >= b}
_BIN = {ast.Add: lambda a, b: a + b, ast.Sub: lambda a, b: a - b, ast.Mult: lambda a, b: a * b,
        ast.Mod: lambda a, b: a % b, ast.BitAnd: lambda a, b: a & b, ast.BitOr: lambda a, b: a | b,
        ast.BitXor: lambda a, b: a ^ b, ast.LShift: lambda a, b: a << b, ast.RShift: lambda a, b: a >> b}


def _eval(node: ast.AST, env: dict[str, int]) -> int:
    if isinstance(node, ast.Expression):
        return _eval(node.body, env)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool):
            return int(node.value)
        if isinstance(node.value, int):
            return node.value
        raise Unparseable("non-integer constant")
    if isinstance(node, ast.Name):
        if node.id not in env:
            raise Unparseable(f"unknown name {node.id}")
        return env[node.id]
    if isinstance(node, ast.UnaryOp):
        if isinstance(node.op, ast.Not):
            return int(not _eval(node.operand, env))
        if isinstance(node.op, ast.USub):
            return -_eval(node.operand, env)
        if isinstance(node.op, ast.UAdd):
            return _eval(node.operand, env)
        raise Unparseable("unsupported unary operator")
    if isinstance(node, ast.BoolOp):
        vals = [_eval(v, env) for v in node.values]
        return int(all(vals) if isinstance(node.op, ast.And) else any(vals))
    if isinstance(node, ast.BinOp):
        fn = _BIN.get(type(node.op))
        if fn is None:
            raise Unparseable("unsupported binary operator")
        return int(fn(_eval(node.left, env), _eval(node.right, env)))
    if isinstance(node, ast.Compare):
        if len(node.ops) != 1:
            raise Unparseable("chained comparison")
        fn = _CMP.get(type(node.ops[0]))
        if fn is None:
            raise Unparseable("unsupported comparison")
        return int(fn(_eval(node.left, env), _eval(node.comparators[0], env)))
    if isinstance(node, ast.Subscript):
        base = _eval(node.value, env)
        sl = node.slice
        if isinstance(sl, ast.Slice):
            if sl.lower is None or sl.upper is None or sl.step is not None:
                raise Unparseable("unsupported part select")
            hi, lo = _eval(sl.lower, env), _eval(sl.upper, env)
            if hi < lo:
                hi, lo = lo, hi
            return (base >> lo) & ((1 << (hi - lo + 1)) - 1)
        return (base >> _eval(sl, env)) & 1
    raise Unparseable(f"unsupported syntax {type(node).__name__}")


def compile_expr(expr: str):
    """Return f(env)->int for a Verilog expression, or raise Unparseable."""
    src = to_python(expr)
    try:
        tree = ast.parse(src, mode="eval")
    except SyntaxError as e:
        raise Unparseable(str(e))
    names = {demangle(n.id) for n in ast.walk(tree) if isinstance(n, ast.Name)}

    def run(env: dict[str, int]) -> int:
        return _eval(tree, {mangle(k): v for k, v in env.items()})

    run.names = names  # type: ignore[attr-defined]
    return run


def constants_in(expr: str) -> set[int]:
    try:
        tree = ast.parse(to_python(expr), mode="eval")
    except (Unparseable, SyntaxError):
        return set()
    return {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, int) and not isinstance(n.value, bool)}


def is_default(condition: str) -> bool:
    return condition.strip().strip('"').lower() in DEFAULT_CONDITIONS


def inputs_named(condition: str, input_names: set[str]) -> set[str]:
    """Input ports a condition looks at. Falls back to word matching when it does not parse."""
    if is_default(condition):
        return set()
    try:
        return set(getattr(compile_expr(condition), "names", set())) & input_names
    except Unparseable:
        return {w for w in _WORD.findall(condition)} & input_names


# -- state completeness over the sampled inputs -------------------------------------------------

def input_blind_states(contract: Contract, fsm: Fsm) -> list[dict]:
    """States whose rows never look at a one-bit input that the rest of the table does sample.

    `evals/results/final-2026-09-14/.../seq_detect` is the pattern: a 1011 detector whose MATCH state
    carries the single row `default -> GOT1`, so the bit sampled during the match cycle is dropped and
    overlapping detection is lost. The reference is written from the same table, so the table check
    agrees with it and simulation cannot see the hole.

    Deliberately narrow, because a false rejection costs a whole run:

    * only one-bit inputs, so "add a row per value" is literally two rows;
    * only states whose rows mention NO input at all — a state that tests some other input is at
      least sampling, and different states legitimately watch different inputs;
    * a state that carries a `note` on any of its rows has said the omission is intended, so it passes.

    A state whose one default row is a self-loop with unchanged outputs (a true idle/hold) is exempt
    when no other state samples the input; that is already implied by the trigger, which fires only
    when another state does sample it, and is spelled out here so the intent is not lost.
    """
    input_names = {p.name for p in contract.data_inputs()}
    narrow = {p.name for p in contract.data_inputs() if p.width == 1}
    if not narrow:
        return []
    per_state: dict[str, set[str]] = {}
    for s in fsm.states:
        seen: set[str] = set()
        for t in fsm.transitions_from(s.name):
            seen |= inputs_named(t.condition, input_names)
        per_state[s.name] = seen
    findings: list[dict] = []
    for s in fsm.states:
        rows = fsm.transitions_from(s.name)
        if not rows or per_state[s.name] or any(t.note.strip() for t in rows):
            continue
        blind = sorted(x for x in narrow if any(x in per_state[o.name] for o in fsm.states if o.name != s.name))
        for x in blind:
            hold = len(rows) == 1 and rows[0].next_state == s.name and is_default(rows[0].condition)
            findings.append({"state": s.name, "input": x, "rows": len(rows), "self_loop": hold,
                             "tested_in": sorted(o.name for o in fsm.states if x in per_state[o.name])})
    return findings


def input_blind_message(findings: list[dict]) -> str:
    """The rejection text sent back to the model."""
    parts = "; ".join(f"state `{f['state']}` ignores input `{f['input']}` (its {f['rows']} row(s) never test it, "
                      f"while state(s) {', '.join('`' + s + '`' for s in f['tested_in'])} do)" for f in findings[:MAX_REPORTED])
    return ("the `fsm` transition table drops an input in at least one state: " + parts + ". Rows that never test the "
            "input sample nothing, so whatever arrives during that cycle is thrown away and the machine leaves that "
            "state the same way whatever the input was. Re-read the request and decide, "
            "for each state named above: if the next state or an output depends on that input there, add one row per "
            "value of it (for a one-bit input that is two rows, `x == 0` and `x == 1`) with the correct `next_state`; "
            "only if the request really does say the input is ignored in that state, keep the single row and put the "
            "sentence that says so in the row's `note` field. Do not add a note you cannot point at in the request.")


# -- stimulus from the table --------------------------------------------------------------------

@dataclass
class Probe:
    state: str
    condition: str
    rows: list[dict[str, int]]
    expected: dict[str, int]
    outputs: list[str] = field(default_factory=list)


def _candidate_vectors(contract: Contract, fsm: Fsm) -> list[dict[str, int]]:
    """Input vectors to search for one that selects a given row.

    Small by construction: 0, 1, the all-ones value, and every integer constant the table's own
    conditions mention, per input port.
    """
    consts: set[int] = set()
    for t in fsm.transitions:
        consts |= constants_in(t.condition)
    per_port: list[list[int]] = []
    names: list[str] = []
    for p in contract.data_inputs():
        mask = (1 << p.width) - 1
        vals = {0, 1, mask} | {c & mask for c in consts}
        names.append(p.name)
        per_port.append(sorted(vals)[:8])
    out: list[dict[str, int]] = []
    for combo in itertools.islice(itertools.product(*per_port), MAX_CANDIDATES):
        out.append(dict(zip(names, combo)))
    return out


def _idle(contract: Contract) -> dict[str, int]:
    cr = contract.clock_reset
    assert cr is not None
    vec = {cr.clock: 1}
    if cr.reset:
        vec[cr.reset] = 0 if cr.reset_active == "high" else 1
    return vec


def _row_selector(fsm: Fsm, state: str, inputs: set[str]) -> tuple[dict[int, object], list[int]]:
    """Compiled predicates for a state's rows, and the indices of its default rows.

    A condition naming anything but an input port (an internal counter, say) cannot be driven from
    outside, so that row is dropped rather than guessed at.
    """
    preds: dict[int, object] = {}
    defaults: list[int] = []
    for i, t in enumerate(fsm.transitions):
        if t.state != state:
            continue
        if is_default(t.condition):
            defaults.append(i)
            continue
        try:
            fn = compile_expr(t.condition)
        except Unparseable:
            continue
        if getattr(fn, "names", set()) - inputs:
            continue
        preds[i] = fn
    return preds, defaults


def _expected_outputs(t, vec: dict[str, int], out_ports: dict, input_names: set[str]) -> dict[str, int]:
    """The output values the table declares for row `t` under input vector `vec`, exactly evaluable ones only."""
    expected: dict[str, int] = {}
    for name, value in t.outputs.items():
        p = out_ports.get(name)
        if p is None or not str(value).strip():
            continue
        try:
            fn = compile_expr(str(value))
            if getattr(fn, "names", set()) - input_names:
                continue
            expected[name] = _mask(fn(vec), p.width)
        except Unparseable:
            continue
    return expected


def build_probes(contract: Contract, fsm: Fsm) -> tuple[list[Probe], dict[str, list[str]]]:
    """Directed stimulus: drive every listed condition from every reachable state, and both values of
    every sampled one-bit input from every reachable state.

    The second part exists for visibility. Where a state's rows ignore an input, the reference was
    written from the same table and will agree with it, so driving the missing value proves nothing
    by itself; what it does is put the undriven case on the record (`unexercised_inputs`) next to the
    intake finding, and exercise the reference on inputs it would otherwise never see.
    """
    candidates = _candidate_vectors(contract, fsm)
    if not candidates:
        return [], {}
    idle = _idle(contract)
    out_ports = {p.name: p for p in contract.ports if p.direction == Direction.output}
    input_names = {p.name for p in contract.data_inputs()}
    selectors = {s.name: _row_selector(fsm, s.name, input_names) for s in fsm.states}
    all_uncompiled = {s.name: any(t.state == s.name and not is_default(t.condition)
                                  and i not in selectors[s.name][0]
                                  for i, t in enumerate(fsm.transitions))
                      for s in fsm.states}

    cache: dict[tuple[str, int], dict[str, int] | None] = {}

    def pick(state: str, index: int) -> dict[str, int] | None:
        """An input vector that selects exactly row `index` of `state`, or None."""
        if (state, index) in cache:
            return cache[(state, index)]
        cache[(state, index)] = vec = _pick(state, index)
        return vec

    def _pick(state: str, index: int) -> dict[str, int] | None:
        preds, defaults = selectors[state]
        if index in defaults:
            if all_uncompiled[state]:
                return None          # a row we cannot evaluate might also match: do not guess
            for vec in candidates:
                if not any(bool(p(vec)) for p in preds.values()):  # type: ignore[operator]
                    return vec
            return None
        pred = preds.get(index)
        if pred is None:
            return None
        others = [p for i, p in preds.items() if i != index]
        for vec in candidates:
            if bool(pred(vec)) and not any(bool(p(vec)) for p in others):  # type: ignore[operator]
                return vec
        return None

    def match_row(state: str, vec: dict[str, int]) -> int | None:
        """The row of `state` that `vec` selects, or None when the table cannot say."""
        preds, defaults = selectors[state]
        for i, p in preds.items():
            if bool(p(vec)):  # type: ignore[operator]
                return i
        if len(defaults) == 1 and not all_uncompiled[state]:
            return defaults[0]
        return None

    # reachable states, with the input sequence that drives the machine there from reset
    paths: dict[str, list[dict[str, int]]] = {fsm.reset_state: []}
    queue = [fsm.reset_state]
    while queue:
        state = queue.pop(0)
        for i, t in enumerate(fsm.transitions):
            if t.state != state or t.next_state in paths:
                continue
            vec = pick(state, i)
            if vec is None:
                continue
            paths[t.next_state] = paths[state] + [vec]
            queue.append(t.next_state)

    probes: list[Probe] = []
    for i, t in enumerate(fsm.transitions):
        if t.state not in paths or len(probes) >= MAX_PROBES:
            continue
        vec = pick(t.state, i)
        if vec is None:
            continue
        expected = _expected_outputs(t, vec, out_ports, input_names)
        if not expected:
            continue
        rows = [{**idle, **v} for v in paths[t.state] + [vec]]
        probes.append(Probe(state=t.state, condition=t.condition, rows=rows,
                            expected=expected, outputs=sorted(expected)))

    # Both values of every sampled one-bit input, from every reachable state. A state whose rows do
    # not distinguish them still gets driven with each; what cannot be driven is reported instead.
    sampled = sorted({x for t in fsm.transitions for x in inputs_named(t.condition, input_names)})
    narrow = [x for x in sampled if x in {p.name for p in contract.data_inputs() if p.width == 1}]
    unexercised: dict[str, list[str]] = {}
    for state in sorted(paths):
        base = next((p.rows[-1] for p in probes if p.state == state), None)
        if base is None:
            base = next((v for i, t in enumerate(fsm.transitions)
                         if t.state == state and (v := pick(state, i)) is not None), None)
        if base is None:
            unexercised[state] = [f"{x}={v}" for x in narrow for v in (0, 1)]
            continue
        for x in narrow:
            for value in (0, 1):
                if any(p.state == state and p.rows[-1].get(x) == value for p in probes):
                    continue
                vec = {**{k: v for k, v in base.items() if k in input_names}, x: value}
                index = match_row(state, vec)
                expected = _expected_outputs(fsm.transitions[index], vec, out_ports, input_names) if index is not None else {}
                if not expected or len(probes) >= MAX_PROBES + MAX_COVERAGE_PROBES:
                    unexercised.setdefault(state, []).append(f"{x}={value}")
                    continue
                t = fsm.transitions[index]
                probes.append(Probe(state=state, condition=f"{t.condition} with {x}={value}",
                                    rows=[{**idle, **v} for v in paths[state] + [vec]],
                                    expected=expected, outputs=sorted(expected)))
    return probes, unexercised


def _mask(value: int, width: int) -> int:
    return int(value) & ((1 << width) - 1)


def moore_conflicts(contract: Contract, fsm: Fsm) -> list[dict]:
    """Outputs declared Moore that the table itself gives two values for in one state.

    A contradiction inside the contract, found without running anything: a Moore output depends on
    the state alone, so two rows of the same state cannot disagree about it.
    """
    out_widths = {p.name: p.width for p in contract.ports if p.direction == Direction.output}
    seen: dict[tuple[str, str], tuple[int, str, str]] = {}
    conflicts: list[dict] = []
    for t in fsm.transitions:
        for name, value in t.outputs.items():
            if fsm.style_of(name) != "moore" or name not in out_widths:
                continue
            try:
                fn = compile_expr(str(value))
                if getattr(fn, "names", set()):
                    continue                      # not a constant: not comparable across rows
                val = _mask(fn({}), out_widths[name])
            except Unparseable:
                continue
            key = (t.state, name)
            if key in seen and seen[key][0] != val:
                conflicts.append({"state": t.state, "output": name, "values": [seen[key][1], str(value)],
                                  "conditions": [seen[key][2], t.condition]})
            else:
                seen.setdefault(key, (val, str(value), t.condition))
    return conflicts


# -- the check ----------------------------------------------------------------------------------

def check_reference_against_fsm(
    contract: Contract, reference_py: Path, work: Path,
    python: str = sys.executable, timeout_s: float = 180.0,
) -> dict:
    """Return a verdict dict; `status` is one of not_applicable | ok | mismatch | error."""
    out: dict = {"status": "not_applicable", "probes": 0, "checks": 0, "mismatches": [], "conflicts": [],
                 "unexercised_inputs": {}, "detail": ""}
    fsm = contract.fsm
    if fsm is None or contract.clock_reset is None:
        return out
    conflicts = moore_conflicts(contract, fsm)
    widths = {p.name: int(getattr(p, "width", 1) or 1) for p in contract.ports}
    if conflicts and all(widths.get(c["output"], 1) > 1 for c in conflicts):
        # Every conflicting output is a multi-bit value: the "states" lump many values of a counter or
        # datapath register, so the table is not a control FSM. It cannot be checked; do not withhold on it.
        out["conflicts"] = conflicts
        out["detail"] = ("fsm table describes a multi-bit output as Moore with several values per state "
                         "(a counter or datapath, not a control FSM); table not checked: " + _conflict_detail(conflicts))
        return out
    out["conflicts"] = conflicts
    try:
        probes, unexercised = build_probes(contract, fsm)
    except Exception as e:  # noqa: BLE001 — a stimulus-builder crash must never fail a run
        out.update(status="error", detail=f"stimulus generation failed: {type(e).__name__}: {e}")
        return out
    out["probes"] = len(probes)
    out["unexercised_inputs"] = unexercised
    if not probes:
        if conflicts:
            out["status"] = "mismatch"
            out["detail"] = _conflict_detail(conflicts)
        return out
    work.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="fsm-", dir=work))
    contract_path = work / "contract.json"
    contract_path.write_text(contract.model_dump_json(indent=1))
    ports = sorted({n for p in probes for n in p.outputs})
    rows_path = work / "rows.json"
    res_path = work / "result.json"
    rows_path.write_text(json.dumps({"mode": "sequences", "rows": [p.rows for p in probes], "outputs": ports}))
    err = _eval_sequences(python, reference_py, contract_path, rows_path, res_path, work, timeout_s)
    if err:
        out.update(status="error", detail=err)
        return out
    data = json.loads(res_path.read_text())
    if data.get("error"):
        out.update(status="error", detail=data["error"][:600])
        return out
    mismatches: list[dict] = []
    checked = 0
    for probe, results in zip(probes, data["results"]):
        if not results:
            continue
        got = results[-1]
        for name, want in probe.expected.items():
            checked += 1
            actual = got.get(name)
            if actual is None or int(actual) != int(want):
                if len(mismatches) < MAX_REPORTED:
                    mismatches.append({"state": probe.state, "condition": probe.condition, "output": name,
                                       "table_says": int(want), "reference_says": actual,
                                       "cycles": len(probe.rows)})
    out["checks"] = checked
    out["mismatches"] = mismatches
    out["status"] = "mismatch" if (mismatches or conflicts) else "ok"
    details = [f"in state `{m['state']}` with `{m['condition']}` the contract's transition table says "
               f"{m['output']}={m['table_says']}, the reference computes {m['reference_says']}" for m in mismatches]
    if conflicts:
        details.append(_conflict_detail(conflicts))
    out["detail"] = "; ".join(details)
    return out


def _conflict_detail(conflicts: list[dict]) -> str:
    return "; ".join(f"the table gives the Moore output {c['output']} two values in state `{c['state']}` "
                     f"({' vs '.join(c['values'])})" for c in conflicts[:MAX_REPORTED])


def _eval_sequences(python, reference_py, contract_path, rows_path, res_path, work, timeout_s) -> str:
    try:
        proc = subprocess.run(
            [python, "-I", str(REFROWS), str(Path(reference_py).resolve()),
             str(contract_path.resolve()), str(rows_path.resolve()), str(res_path.resolve())],
            capture_output=True, text=True, timeout=timeout_s, cwd=str(work),
        )
    except subprocess.TimeoutExpired:
        return "reference model timed out on the contract's transition table"
    if proc.returncode != 0:
        return f"reference evaluation exited with code {proc.returncode}"
    if not res_path.is_file():
        return "reference evaluation produced no output"
    return ""
