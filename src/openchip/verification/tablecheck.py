"""Check a run's reference model against tables printed in the request itself.

Everything downstream of intake — the reference model and the RTL — is written from the contract,
so a request whose Karnaugh map, truth table or waveform was misread produces a reference and an
RTL that agree with each other and are both wrong; simulation cannot see it. Measured: tabular
misreading is the largest attributed cause of false acceptance (docs/research/false-acceptance-
analysis.md §5).

A table printed in the request is ground truth that does not pass through the model at all. This
module parses it (`contracts/tables.py`), binds its variables to contract ports, and evaluates the
reference on every row. A disagreement means the design's foundation contradicts the request.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from ..contracts.schema import Contract
from ..contracts.tables import (
    RequestTable, TableVar, WaveformTrace, classify_trace_outputs, parse_clocked_waveforms,
    parse_request_tables, posedge_indices,
)

REFROWS = Path(__file__).with_name("refrows.py")
MAX_REPORTED = 6


@dataclass
class BoundTable:
    table: RequestTable
    output_port: str
    rows: list[tuple[dict[str, int], int]]  # ({port: value}, expected output)


def bind(table: RequestTable, contract: Contract) -> BoundTable | None:
    """Map a parsed table onto contract ports, or None when it does not apply cleanly.

    Declines unless the table pins down every input the reference can see: a row that leaves an
    input free does not predict an output, and guessing a value for it would invent evidence.
    """
    if contract.clock_reset is not None:
        return None  # a sequential contract: one row does not determine an output
    ports = {p.name: p for p in contract.ports}
    op = ports.get(table.output.port)
    if op is None or op.direction != "output" or op.width != 1 or table.output.bit not in (None, 0):
        return None
    covered: set[tuple[str, int]] = set()
    for v in table.inputs:
        p = ports.get(v.port)
        if p is None or p.direction != "input":
            return None
        bit = 0 if v.bit is None else v.bit
        if v.bit is None and p.width != 1:
            return None
        if bit >= p.width:
            return None
        if (v.port, bit) in covered:
            return None
        covered.add((v.port, bit))
    # every input bit the reference can see must be pinned by the table
    for p in contract.ports:
        if p.direction != "input":
            continue
        for b in range(p.width):
            if (p.name, b) not in covered:
                return None
    rows: list[tuple[dict[str, int], int]] = []
    for values, expected in table.rows:
        vec: dict[str, int] = {p.name: 0 for p in contract.ports if p.direction == "input"}
        for v, val in zip(table.inputs, values):
            vec[v.port] |= (val & 1) << (0 if v.bit is None else v.bit)
        rows.append((vec, expected))
    return BoundTable(table=table, output_port=table.output.port, rows=rows)


@dataclass
class BoundTrace:
    trace: WaveformTrace
    inputs: tuple[str, ...]
    outputs: tuple[str, ...]
    steps: list[tuple[dict[str, int], dict[str, int]]]  # (inputs, expected defined outputs)


def bind_trace(trace: WaveformTrace, contract: Contract) -> BoundTrace | None:
    """Map a clocked dump onto a sequential contract, or None when it does not apply cleanly."""
    cr = contract.clock_reset
    if cr is None or cr.clock != trace.clock:
        return None
    ports = {p.name: p for p in contract.ports}
    clk_reset = {cr.clock} | ({cr.reset} if cr.reset else set())
    cols = set(trace.columns)
    data_in = [p.name for p in contract.ports if p.direction == "input" and p.name not in clk_reset]
    data_out = [p.name for p in contract.ports if p.direction == "output"]
    if any(n not in cols for n in data_in):
        return None
    outputs = tuple(n for n in trace.columns if n != trace.clock and n in ports and ports[n].direction == "output")
    if not outputs or any(n not in data_out for n in outputs):
        return None
    if any(n != trace.clock and n not in ports for n in trace.columns):
        return None
    # `Reference.step` is one rising edge, so the replay can only speak about outputs the dump shows
    # changing at a rising edge. A transparent latch and a falling-edge register are invisible to it:
    # replaying them produced an unsatisfiable check that rejected three correct references in a row
    # and left `Prob145_circuit8` with no RTL at all (ADR 0016 L2). They are checked against the dump
    # directly instead, by replaying the delivered RTL (`verification/wavecheck.py`).
    timings = classify_trace_outputs(trace, outputs)
    outputs = tuple(n for n in outputs if timings[n].kind in ("posedge", "constant"))
    if not outputs:
        return None
    rst_inactive = 0 if cr.reset_active == "high" else 1
    edges = posedge_indices(trace)
    started = False
    steps: list[tuple[dict[str, int], dict[str, int]]] = []
    for i in edges:
        # A dump sample printed at the time of an edge is the value the edge PRODUCED: in
        # `Prob117_circuit9` the sample at 45ns already carries the new `a` and the `q` that edge
        # wrote, and 50ns (clock low) repeats it. So the edge acted on the sample printed before it,
        # which is exactly what `step()` takes and returns: outputs as seen just before the edge,
        # then the update. Reading the edge's own sample as the pre-edge observation demanded a
        # fictitious power-up value (q=4 while the dump prints `x` at 0ns) and rejected correct
        # references.
        sample = dict(zip(trace.columns, trace.samples[i - 1]))
        if any(sample[n] is None for n in data_in):
            if started:
                return None
            continue
        started = True
        expected = {n: int(sample[n]) for n in outputs if sample[n] is not None}
        vec = {n: int(sample[n]) for n in data_in}
        vec[cr.clock] = int(sample[trace.clock]) if sample[trace.clock] is not None else 0
        if cr.reset:
            vec[cr.reset] = rst_inactive
        steps.append((vec, expected))
    if not steps or not any(e for _, e in steps):
        return None
    return BoundTrace(trace=trace, inputs=tuple(data_in), outputs=outputs, steps=steps)


def _describe(v: TableVar, value: int) -> str:
    return f"{v.name}={value}"


def check_reference_against_request_tables(
    contract: Contract, request: str, reference_py: Path, work: Path,
    python: str = sys.executable, timeout_s: float = 120.0,
) -> dict:
    """Return a verdict dict; `status` is one of not_applicable | ok | mismatch | error."""
    out: dict = {"status": "not_applicable", "tables": 0, "rows": 0, "mismatches": [], "detail": ""}
    try:
        tables = parse_request_tables(request)
    except Exception as e:  # noqa: BLE001 — a parser crash must never fail a run
        out.update(status="error", detail=f"table parse failed: {type(e).__name__}: {e}")
        return out
    bound = [b for b in (bind(t, contract) for t in tables) if b is not None]
    try:
        traces = parse_clocked_waveforms(request)
    except Exception as e:  # noqa: BLE001
        out.update(status="error", detail=f"waveform parse failed: {type(e).__name__}: {e}")
        return out
    bound_tr = [b for b in (bind_trace(t, contract) for t in traces) if b is not None]
    if not bound and not bound_tr:
        return out
    out["tables"] = len(bound) + len(bound_tr)
    work.mkdir(parents=True, exist_ok=True)
    # A resume/recheck must never read output left by a previous reference. Keep
    # every invocation's artifacts, but give the subprocess a fresh destination.
    work = Path(tempfile.mkdtemp(prefix="check-", dir=work))
    contract_path = work / "contract.json"
    contract_path.write_text(contract.model_dump_json(indent=1))
    mismatches: list[dict] = []
    checked = 0
    for i, b in enumerate(bound):
        rows_path = work / f"table{i}_rows.json"
        res_path = work / f"table{i}_result.json"
        rows_path.write_text(json.dumps({"rows": [r[0] for r in b.rows], "outputs": [b.output_port]}))
        err = _eval_rows(python, reference_py, contract_path, rows_path, res_path, work, timeout_s)
        if err:
            out.update(status="error", detail=err)
            return out
        data = json.loads(res_path.read_text())
        if data.get("error"):
            out.update(status="error", detail=data["error"][:600])
            return out
        for (vec, expected), got in zip(b.rows, data["results"]):
            checked += 1
            actual = got.get(b.output_port)
            if actual is None or int(actual) != int(expected):
                if len(mismatches) < MAX_REPORTED:
                    inputs = ", ".join(_describe(v, val) for v, val in zip(b.table.inputs, _row_values(b, vec)))
                    mismatches.append({"kind": b.table.kind, "output": b.output_port, "inputs": inputs,
                                       "request_says": int(expected), "reference_says": actual})
    for i, b in enumerate(bound_tr):
        rows_path = work / f"trace{i}_rows.json"
        res_path = work / f"trace{i}_result.json"
        rows_path.write_text(json.dumps({
            "mode": "sequence",
            "rows": [s[0] for s in b.steps],
            "outputs": list(b.outputs),
        }))
        err = _eval_rows(python, reference_py, contract_path, rows_path, res_path, work, timeout_s)
        if err:
            out.update(status="error", detail=err)
            return out
        data = json.loads(res_path.read_text())
        if data.get("error"):
            out.update(status="error", detail=data["error"][:600])
            return out
        for (vec, expected), got in zip(b.steps, data["results"]):
            for port, want in expected.items():
                checked += 1
                actual = got.get(port)
                if actual is None or int(actual) != int(want):
                    if len(mismatches) < MAX_REPORTED:
                        inputs = ", ".join(f"{n}={vec[n]}" for n in b.inputs)
                        mismatches.append({"kind": "clocked_waveform", "output": port, "inputs": inputs,
                                           "request_says": int(want), "reference_says": actual})
    out["rows"] = checked
    out["mismatches"] = mismatches
    out["status"] = "mismatch" if mismatches else "ok"
    if mismatches:
        out["detail"] = "; ".join(f"{m['inputs']} -> the request's {m['kind']} says "
                                  f"{m['output']}={m['request_says']}, the reference computes {m['reference_says']}"
                                  for m in mismatches)
    return out


def _eval_rows(python, reference_py, contract_path, rows_path, res_path, work, timeout_s) -> str:
    try:
        proc = subprocess.run(
            [python, "-I", str(REFROWS), str(Path(reference_py).resolve()),
             str(contract_path.resolve()), str(rows_path.resolve()), str(res_path.resolve())],
            capture_output=True, text=True, timeout=timeout_s, cwd=str(work),
        )
    except subprocess.TimeoutExpired:
        return "reference model timed out on the request table"
    if proc.returncode != 0:
        return f"reference evaluation exited with code {proc.returncode}"
    if not res_path.is_file():
        return "reference evaluation produced no output"
    return ""


def _row_values(b: BoundTable, vec: dict[str, int]) -> list[int]:
    return [(vec[v.port] >> (0 if v.bit is None else v.bit)) & 1 for v in b.table.inputs]
