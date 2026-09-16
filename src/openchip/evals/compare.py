"""Cross-model comparison table from recorded eval directories.

Usage: python -m openchip.evals.compare <results-root> [out.md]
Groups result directories by the model recorded in each summary.json and reports, per model:
core-v1 and heldout-v1 (agent accepted / golden pass / false acceptance / interface mismatch, mean wall),
VerilogEval direct pass@1 (n=156) and agent-mode subset (n=39, false acceptances). Every number carries its
denominator; protocols are never merged.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path


def _fraction(result: dict, field: str) -> str:
    return f"{result[field]}/{result['n']}" if result else "–"


def main(argv: list[str]) -> int:
    root = Path(argv[0]) if argv else Path("evals/results")
    out = Path(argv[1]) if len(argv) > 1 else root / "model-comparison.md"
    per_model: dict[str, dict] = defaultdict(dict)
    for run_dir in sorted(root.iterdir()):
        summary_path = run_dir / "summary.json"
        if not run_dir.is_dir() or not summary_path.is_file():
            continue
        summary = json.loads(summary_path.read_text())
        model = (summary.get("model") or {}).get("model", "?")
        revision = ((summary.get("model") or {}).get("revision") or "")[:10]
        key = f"{model} @ {revision}"
        if "suite" in summary:
            suite = Path(summary["suite"]).name
            # keep the latest run per (model, suite)
            per_model[key][suite] = {
                "dir": run_dir.name, "n": summary["n"], "accepted": summary["accepted"],
                "golden": summary["golden_pass"], "false": summary["false_acceptance"],
                "iface": summary["interface_mismatch"], "wall": summary["mean_wall_s"],
            }
        elif "benchmark" in summary:
            mode = summary["mode"]
            per_model[key][f"veval-{mode}"] = {
                "dir": run_dir.name, "n": summary["n"], "pass": summary["pass"],
                "false": summary.get("false_acceptance"),
            }
    rows = ["# Model comparison (identical protocol; all runs on JarvisLabs)", "",
            "Protocol per model: core-v1 (10 tasks × 1, budget 15 min), heldout-v1 (5 × 2, thresholds pre-registered), VerilogEval v2 spec-to-rtl direct single-shot pass@1 (n=156, T=0.2, no thinking), VerilogEval v2 agent mode (every 4th problem, n=39, budget 6 min). Golden pass = independently correct against human-written references never shown to the model. False acceptance = agent accepted but independent check failed.", "",
            "| Model @ rev | core-v1 golden | core-v1 false acc. | heldout golden | heldout false acc. | VerilogEval direct pass@1 | VerilogEval agent pass | agent false acc. | core-v1 mean wall s |",
            "|---|---|---|---|---|---|---|---|---|"]
    for key, results in sorted(per_model.items()):
        core = results.get("core-v1", {})
        heldout = results.get("heldout-v1", {})
        direct = results.get("veval-direct", {})
        agent = results.get("veval-agent", {})
        rows.append(
            f"| `{key}` | {_fraction(core, 'golden')} | {_fraction(core, 'false')} "
            f"| {_fraction(heldout, 'golden')} | {_fraction(heldout, 'false')} "
            f"| {_fraction(direct, 'pass')} | {_fraction(agent, 'pass')} "
            f"| {_fraction(agent, 'false')} | {core.get('wall', '–')} |"
        )
    rows += ["", "Source directories:", ""]
    for key, results in sorted(per_model.items()):
        rows.append(f"- `{key}`: " + ", ".join(f"{name}=`{result['dir']}`" for name, result in results.items()))
    out.write_text("\n".join(rows) + "\n")
    print("\n".join(rows[:12]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
