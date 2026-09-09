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


def main(argv: list[str]) -> int:
    root = Path(argv[0]) if argv else Path("evals/results")
    out = Path(argv[1]) if len(argv) > 1 else root / "model-comparison.md"
    per_model: dict[str, dict] = defaultdict(dict)
    for d in sorted(root.iterdir()):
        sj = d / "summary.json"
        if not d.is_dir() or not sj.is_file():
            continue
        s = json.loads(sj.read_text())
        model = (s.get("model") or {}).get("model", "?")
        rev = ((s.get("model") or {}).get("revision") or "")[:10]
        key = f"{model} @ {rev}"
        if "suite" in s:  # eval suite
            name = Path(s["suite"]).name
            # keep the latest run per (model, suite)
            per_model[key][name] = {"dir": d.name, "n": s["n"], "accepted": s["accepted"], "golden": s["golden_pass"], "false": s["false_acceptance"],
                                    "iface": s["interface_mismatch"], "wall": s["mean_wall_s"]}
        elif "benchmark" in s:
            mode = s["mode"]
            per_model[key][f"veval-{mode}"] = {"dir": d.name, "n": s["n"], "pass": s["pass"], "false": s.get("false_acceptance")}
    rows = ["# Model comparison (identical protocol; all runs on JarvisLabs)", "",
            "Protocol per model: core-v1 (10 tasks × 1, budget 15 min), heldout-v1 (5 × 2, thresholds pre-registered), VerilogEval v2 spec-to-rtl direct single-shot pass@1 (n=156, T=0.2, no thinking), VerilogEval v2 agent mode (every 4th problem, n=39, budget 6 min). Golden pass = independently correct against human-written references never shown to the model. False acceptance = agent accepted but independent check failed.", "",
            "| Model @ rev | core-v1 golden | core-v1 false acc. | heldout golden | heldout false acc. | VerilogEval direct pass@1 | VerilogEval agent pass | agent false acc. | core-v1 mean wall s |",
            "|---|---|---|---|---|---|---|---|---|"]
    for key, r in sorted(per_model.items()):
        c = r.get("core-v1", {}); h = r.get("heldout-v1", {}); vd = r.get("veval-direct", {}); va = r.get("veval-agent", {})
        f = lambda x, k, n="n": (f"{x[k]}/{x[n]}" if x else "–")
        rows.append(f"| `{key}` | {f(c,'golden')} | {f(c,'false')} | {f(h,'golden')} | {f(h,'false')} | {f(vd,'pass')} | {f(va,'pass')} | {f(va,'false')} | {c.get('wall','–')} |")
    rows += ["", "Source directories:", ""]
    for key, r in sorted(per_model.items()):
        rows.append(f"- `{key}`: " + ", ".join(f"{k}=`{v['dir']}`" for k, v in r.items()))
    out.write_text("\n".join(rows) + "\n")
    print("\n".join(rows[:12]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
