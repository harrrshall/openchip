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
from .sandbox import run_isolated
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from ..contracts.schema import Contract
from ..contracts.tables import RequestTable, TableVar, parse_request_tables

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
    if op is None or op.direction != "output":
        return None
    if (table.output.bit is None and op.width != 1) or (table.output.bit is not None and not 0 <= table.output.bit < op.width):
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


def _describe(v: TableVar, value: int) -> str:
    return f"{v.name}={value}"


def check_reference_against_request_tables(
    contract: Contract, request: str, reference_py: Path, work: Path,
    python: str = sys.executable, timeout_s: float = 120.0,
) -> dict:
    """Return a verdict dict; `status` is one of not_applicable | ok | mismatch | error."""
    out: dict = {"status": "not_applicable", "tables": 0, "rows": 0, "mismatches": [], "detail": ""}
    try:
        tables = parse_request_tables(request, include_external_mux=True)
    except Exception as e:  # noqa: BLE001 — report the error and withhold sign-off without crashing
        out.update(status="error", detail=f"table parse failed: {type(e).__name__}: {e}")
        return out
    bound = [b for b in (bind(t, contract) for t in tables) if b is not None]
    if not bound:
        return out
    out["tables"] = len(bound)
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
        try:
            proc = run_isolated(REFROWS, [Path(reference_py), contract_path, rows_path, res_path],
                                res_path, python=python, timeout_s=timeout_s)
        except subprocess.TimeoutExpired:
            out.update(status="error", detail="reference model timed out on the request table")
            return out
        if proc.returncode != 0:
            out.update(status="error", detail=f"reference evaluation exited with code {proc.returncode}")
            return out
        if not res_path.is_file():
            out.update(status="error", detail="reference evaluation produced no output")
            return out
        data = json.loads(res_path.read_text())
        if data.get("error"):
            out.update(status="error", detail=data["error"][:600])
            return out
        for (vec, expected), got in zip(b.rows, data["results"]):
            checked += 1
            actual = got.get(b.output_port)
            if actual is not None and b.table.output.bit is not None:
                actual = (int(actual) >> b.table.output.bit) & 1
            if actual is None or int(actual) != int(expected):
                if len(mismatches) < MAX_REPORTED:
                    inputs = ", ".join(_describe(v, val) for v, val in zip(b.table.inputs, _row_values(b, vec)))
                    mismatches.append({"kind": b.table.kind, "output": b.table.output.name, "inputs": inputs,
                                       "request_says": int(expected), "reference_says": actual})
    out["rows"] = checked
    out["mismatches"] = mismatches
    out["status"] = "mismatch" if mismatches else "ok"
    if mismatches:
        out["detail"] = "; ".join(f"{m['inputs']} -> the request's {m['kind']} says "
                                  f"{m['output']}={m['request_says']}, the reference computes {m['reference_says']}"
                                  for m in mismatches)
    return out


def _row_values(b: BoundTable, vec: dict[str, int]) -> list[int]:
    return [(vec[v.port] >> (0 if v.bit is None else v.bit)) & 1 for v in b.table.inputs]
