"""Mutation sensitivity check: does the verification harness detect seeded RTL faults?

Usage: python -m openchip.evals.mutate <results-dir> [suite-dir] [--reference model|golden]
For each workspace whose RTL passes its reference, generate simple mutants (operator flips,
constant changes, reset-value changes, dropped else-branches) and re-run the harness with the
model-derived reference (what the product uses) and with the locked golden. A surviving mutant is
one the harness accepts. Equivalent mutants are possible; the score is a sensitivity estimate,
not a completeness proof.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from ..config import Config
from ..contracts.schema import Contract
from ..verification.harness import verify
from .runner import SUITES_ROOT

OPERATORS = [
    ("eq_to_neq", re.compile(r"==(?!=)"), "!="),
    ("lt_to_le", re.compile(r"(?<![<>=!])<(?![<=])"), "<="),
    ("gt_to_ge", re.compile(r"(?<![<>=!])>(?![>=])"), ">="),
    ("plus1_to_plus2", re.compile(r"\+\s*(\d+'d)?1\b"), "+ 2"),
    ("minus_to_plus", re.compile(r"(?<=[\w\]\)])\s-\s(?=[\w\(])"), " + "),
    ("and_to_or", re.compile(r"&&"), "||"),
    ("not_drop", re.compile(r"(?<=\()!(?=\w)"), ""),
    ("rst_val_1", re.compile(r"<=\s*(\{[^}]*1'b0\}|1'b0|8'd0|8'b0|16'b0|0)\s*;", ), "<= 1;"),
    ("shift_dir", re.compile(r"<<\s*1"), ">> 1"),
]


def mutants(src: str, max_per_op: int = 3) -> list[tuple[str, str]]:
    out = []
    for name, rx, repl in OPERATORS:
        hits = list(rx.finditer(src))
        for i, m in enumerate(hits[:max_per_op]):
            mutated = src[: m.start()] + repl + src[m.end():]
            if mutated != src:
                out.append((f"{name}#{i}", mutated))
    return out


def main(argv: list[str]) -> int:
    results = Path(argv[0])
    suite = Path(argv[1]) if len(argv) > 1 and not argv[1].startswith("--") else SUITES_ROOT / "core-v1"
    cfg = Config.load()
    cfg.verification.run_formal = False
    rows = []
    for tdir in sorted(p for p in results.iterdir() if p.is_dir()):
        task_json = suite / tdir.name / "task.json"
        if not task_json.is_file():
            continue
        task = json.loads(task_json.read_text())
        rep = tdir / "rep0"
        spec = sorted((rep / "spec").glob("contract.v*.json"))
        rtl = rep / "rtl" / f"{task['expected']['module']}.v"
        ref = rep / "reference" / "reference.py"
        if not (spec and rtl.is_file() and ref.is_file()):
            continue
        contract = Contract.model_validate_json(spec[-1].read_text())
        golden = suite / task["id"] / "golden.py"
        work = rep / "verification" / "mutation"
        base = verify(contract, rtl, ref, work / "base", cfg, run_synth=False)
        if not base.accepted:
            rows.append({"task": task["id"], "skipped": "baseline RTL does not pass its reference"})
            print(rows[-1], flush=True)
            continue
        src = rtl.read_text()
        for name, msrc in mutants(src):
            mdir = work / name
            mdir.mkdir(parents=True, exist_ok=True)
            mp = mdir / rtl.name
            mp.write_text(msrc)
            r_model = verify(contract, mp, ref, mdir / "vs_model_ref", cfg, run_synth=False)
            r_gold = verify(contract, mp, golden, mdir / "vs_golden", cfg, run_synth=False)
            row = {"task": task["id"], "mutant": name, "killed_by_model_ref": not r_model.accepted, "stage_model": r_model.stage,
                   "killed_by_golden": not r_gold.accepted, "stage_golden": r_gold.stage}
            rows.append(row)
            print(row, flush=True)
    (results / "mutation.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    scored = [r for r in rows if "mutant" in r]
    n = len(scored)
    km = sum(r["killed_by_model_ref"] for r in scored)
    kg = sum(r["killed_by_golden"] for r in scored)
    both_survive = [r for r in scored if not r["killed_by_model_ref"] and not r["killed_by_golden"]]
    md = [f"# Mutation sensitivity — `{results.name}`", "",
          f"mutants: {n}; killed by model-derived reference: {km}/{n}; killed by golden: {kg}/{n}; survived both (possibly equivalent): {len(both_survive)}", "",
          "| task | mutant | model ref | golden |", "|---|---|---|---|"]
    md += [f"| {r['task']} | {r['mutant']} | {'killed' if r['killed_by_model_ref'] else 'SURVIVED'} ({r['stage_model']}) | {'killed' if r['killed_by_golden'] else 'SURVIVED'} ({r['stage_golden']}) |" for r in scored]
    (results / "mutation.md").write_text("\n".join(md) + "\n")
    print(md[2])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
