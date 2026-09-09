"""Re-score existing eval workspaces against the locked goldens with the CURRENT harness.

Usage: python -m openchip.evals.rescore <results-dir> [suite-dir]
Useful when the harness itself changes: it separates harness artifacts from model failures
without re-running the model. Produces <results-dir>/rescore.md and rescore.jsonl.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from ..config import Config
from ..contracts.schema import Contract
from ..verification.harness import verify
from .runner import SUITES_ROOT, interface_matches


def main(argv: list[str]) -> int:
    results = Path(argv[0])
    suite = Path(argv[1]) if len(argv) > 1 else SUITES_ROOT / "core-v1"
    cfg = Config.load()
    rows = []
    for tdir in sorted(p for p in results.iterdir() if p.is_dir()):
        task_json = suite / tdir.name / "task.json"
        if not task_json.is_file():
            continue
        task = json.loads(task_json.read_text())
        for rep in sorted(tdir.glob("rep*")):
            spec = sorted((rep / "spec").glob("contract.v*.json"))
            rtl = rep / "rtl" / f"{task['expected']['module']}.v"
            row = {"task": task["id"], "rep": rep.name, "status": "no_rtl"}
            if spec and rtl.is_file():
                contract = Contract.model_validate_json(spec[-1].read_text())
                problems = interface_matches(contract, task["expected"])
                if problems:
                    row["status"] = "interface_mismatch"
                else:
                    res = verify(contract, rtl, suite / task["id"] / "golden.py", rep / "verification" / "golden_rescore", cfg,
                                 cycles=task.get("golden_cycles", 600), seeds=task.get("golden_seeds", [101, 202, 303]), run_synth=False)
                    row["status"] = "pass" if res.accepted else res.stage
                    row["mismatches"] = [(s["seed"], s["status"], s["mismatches"]) for s in res.sims]
            rows.append(row)
            print(row, flush=True)
    (results / "rescore.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    n = len(rows)
    npass = sum(r["status"] == "pass" for r in rows)
    md = [f"# Rescore of `{results.name}` with current harness", "", f"golden pass: {npass}/{n}", "", "| task | rep | status |", "|---|---|---|"]
    md += [f"| {r['task']} | {r['rep']} | {r['status']} |" for r in rows]
    (results / "rescore.md").write_text("\n".join(md) + "\n")
    print(f"golden pass: {npass}/{n}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
