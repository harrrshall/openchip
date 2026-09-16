"""Summarise the false-acceptance experiment (configs D/A/B/C) into one table.

Usage: python -m openchip.evals.fa_report <fa-experiment-dir> [out.md]
Each config dir holds a VerilogEval agent run, a core-v1 run and a heldout-v1 run.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

LABELS = {
    "D": "baseline (no review, no alt)",
    "A": "independent spec review",
    "B": "review + cross-family alt refs",
    "C": "cross-family alt refs only",
}


def main(argv: list[str]) -> int:
    root = Path(argv[0])
    out = Path(argv[1]) if len(argv) > 1 else root / "fa-report.md"
    rows = []
    for config in ("D", "A", "B", "C"):
        config_dir = root / config
        if not config_dir.is_dir():
            continue
        agent = next(iter(sorted(config_dir.glob("verilogeval-v2-agent-*"))), None)
        core = next(iter(sorted(config_dir.glob("core-v1-*"))), None)
        heldout = next(iter(sorted(config_dir.glob("heldout-v1-*"))), None)
        row = {"config": config, "label": LABELS.get(config, config)}
        if agent and (agent / "records.jsonl").is_file():
            records = [json.loads(line) for line in (agent / "records.jsonl").read_text().splitlines() if line.strip()]
            row.update({
                "agent_n": len(records),
                "agent_pass": sum(record.get("status") == "pass" for record in records),
                "agent_accepted": sum(bool(record.get("accepted")) for record in records),
                "agent_false": sum(bool(record.get("false_acceptance")) for record in records),
                "agent_provisional": sum(bool(record.get("provisional")) for record in records),
                "agent_false_nonprov": sum(bool(record.get("false_acceptance")) and not record.get("provisional") for record in records),
                "review_applied": sum(1 for record in records if record.get("review_applied")),
                "agent_wall": round(sum(record.get("wall_s", 0) for record in records) / max(1, len(records)), 1),
            })
        for name, run_dir in (("core", core), ("held", heldout)):
            if run_dir and (run_dir / "summary.json").is_file():
                summary = json.loads((run_dir / "summary.json").read_text())
                row.update({
                    f"{name}_golden": summary["golden_pass"], f"{name}_n": summary["n"],
                    f"{name}_false": summary["false_acceptance"],
                })
        rows.append(row)
    md = ["# False-acceptance experiment (same primary model, four configurations)", "",
          "| config | agent pass (n=39) | accepted | false acc. | of which provisional | review applied | core-v1 golden / false | heldout golden / false | agent wall s |", "|---|---|---|---|---|---|---|---|---|"]
    for row in rows:
        md.append(
            f"| {row['config']} {row['label']} | {row.get('agent_pass', '–')}/{row.get('agent_n', '–')} "
            f"| {row.get('agent_accepted', '–')} | **{row.get('agent_false', '–')}** "
            f"| {row.get('agent_provisional', '–')} | {row.get('review_applied', '–')} "
            f"| {row.get('core_golden', '–')}/{row.get('core_n', '–')} / {row.get('core_false', '–')} "
            f"| {row.get('held_golden', '–')}/{row.get('held_n', '–')} / {row.get('held_false', '–')} "
            f"| {row.get('agent_wall', '–')} |"
        )
    out.write_text("\n".join(md) + "\n")
    print("\n".join(md))
    (root / "fa-report.json").write_text(json.dumps(rows, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
