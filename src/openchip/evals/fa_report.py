"""Summarise the false-acceptance experiment (configs D/A/B/C) into one table.

Usage: python -m openchip.evals.fa_report <fa-experiment-dir> [out.md]
Each config dir holds a VerilogEval agent run, a core-v1 run and a heldout-v1 run.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

LABELS = {"D": "baseline (no review, no alt)", "A": "independent spec review", "B": "review + cross-family alt refs", "C": "cross-family alt refs only"}


def main(argv: list[str]) -> int:
    root = Path(argv[0])
    out = Path(argv[1]) if len(argv) > 1 else root / "fa-report.md"
    rows = []
    for c in ("D", "A", "B", "C"):
        d = root / c
        if not d.is_dir():
            continue
        agent = next(iter(sorted(d.glob("verilogeval-v2-agent-*"))), None)
        core = next(iter(sorted(d.glob("core-v1-*"))), None)
        held = next(iter(sorted(d.glob("heldout-v1-*"))), None)
        r = {"config": c, "label": LABELS.get(c, c)}
        if agent and (agent / "records.jsonl").is_file():
            recs = [json.loads(l) for l in (agent / "records.jsonl").read_text().splitlines() if l.strip()]
            r.update({"agent_n": len(recs), "agent_pass": sum(x.get("status") == "pass" for x in recs), "agent_accepted": sum(bool(x.get("accepted")) for x in recs),
                      "agent_false": sum(bool(x.get("false_acceptance")) for x in recs), "agent_provisional": sum(bool(x.get("provisional")) for x in recs),
                      "agent_false_nonprov": sum(bool(x.get("false_acceptance")) and not x.get("provisional") for x in recs),
                      "review_applied": sum(1 for x in recs if x.get("review_applied")), "agent_wall": round(sum(x.get("wall_s", 0) for x in recs) / max(1, len(recs)), 1)})
        for name, dd in (("core", core), ("held", held)):
            if dd and (dd / "summary.json").is_file():
                s = json.loads((dd / "summary.json").read_text())
                r.update({f"{name}_golden": s["golden_pass"], f"{name}_n": s["n"], f"{name}_false": s["false_acceptance"]})
        rows.append(r)
    md = ["# False-acceptance experiment (same primary model, four configurations)", "",
          "| config | agent pass (n=39) | accepted | false acc. | of which provisional | review applied | core-v1 golden / false | heldout golden / false | agent wall s |", "|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        md.append(f"| {r['config']} {r['label']} | {r.get('agent_pass','–')}/{r.get('agent_n','–')} | {r.get('agent_accepted','–')} | **{r.get('agent_false','–')}** | {r.get('agent_provisional','–')} | {r.get('review_applied','–')} | {r.get('core_golden','–')}/{r.get('core_n','–')} / {r.get('core_false','–')} | {r.get('held_golden','–')}/{r.get('held_n','–')} / {r.get('held_false','–')} | {r.get('agent_wall','–')} |")
    out.write_text("\n".join(md) + "\n")
    print("\n".join(md))
    (root / "fa-report.json").write_text(json.dumps(rows, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
