"""Evaluation runner for project-owned task suites.

Each task directory holds `task.json` (id, request, expected interface) and `golden.py`, an
independent reference written by a human and never shown to the model. A task is scored by:
  1. running the full pipeline (agent's own contract, reference, RTL, verification);
  2. re-simulating the produced RTL against the LOCKED golden reference with fresh seeds.
`accepted` (agent's claim) and `golden_pass` (independent check) are reported separately so
false acceptances are visible. Every attempt and failure is counted; denominators are explicit.
"""
from __future__ import annotations

import json
import shutil
import time
from pathlib import Path
from typing import Optional

from ..config import Config, model_slug
from ..contracts.schema import Contract
from ..runtime.run import Runner
from ..runtime.workspace import Workspace
from ..verification.harness import verify

SUITES_ROOT = Path(__file__).resolve().parents[3] / "evals" / "suite"


def load_tasks(suite: str, only: Optional[list[str]] = None) -> list[dict]:
    root = SUITES_ROOT / suite if not Path(suite).is_dir() else Path(suite)
    tasks = []
    for d in sorted(root.iterdir()):
        tj = d / "task.json"
        if tj.is_file():
            t = json.loads(tj.read_text())
            t["dir"] = str(d)
            if not only or t["id"] in only:
                tasks.append(t)
    return tasks


def interface_matches(contract: Contract, expected: dict) -> list[str]:
    problems = []
    if contract.module_name != expected["module"]:
        problems.append(f"module {contract.module_name} != {expected['module']}")
    ports = {p.name: p for p in contract.ports}
    for name, spec in expected["ports"].items():
        p = ports.get(name)
        if not p:
            problems.append(f"missing port {name}")
            continue
        if p.direction.value != spec["dir"] or p.width != spec["width"]:
            problems.append(f"port {name}: {p.direction.value}[{p.width}] != {spec['dir']}[{spec['width']}]")
    extra = set(ports) - set(expected["ports"])
    if extra:
        problems.append(f"extra ports {sorted(extra)}")
    for name, val in expected.get("params", {}).items():
        d = contract.param_defaults()
        if name not in d:
            problems.append(f"missing parameter {name}")
        elif d[name] != val:
            problems.append(f"parameter {name}={d[name]} != {val}")
    return problems


def run_task(cfg: Config, task: dict, out_root: Path, budget: str, rep: int, log=print) -> dict:
    tdir = out_root / task["id"] / f"rep{rep}"
    if tdir.exists():
        raise FileExistsError(f"Refusing to overwrite retained evaluation artifacts: {tdir}")
    ws = Workspace(tdir)
    ws.init(request=task["request"], name=task["id"])
    from ..cli.main import _parse_duration
    cfg.budget.wall_time_s = _parse_duration(budget)
    runner = Runner(ws, cfg, log=lambda m: log(f"  [{task['id']}#{rep}] {m}"))
    t0 = time.time()
    run_id = runner.start(task["request"], budget_s=cfg.budget.wall_time_s)
    rec = {"task": task["id"], "rep": rep, "run_id": run_id, "workspace": str(tdir)}
    try:
        outcome = runner.execute()
    except Exception as e:  # noqa: BLE001
        outcome = {"state": "failed", "accepted": False, "status_line": f"crash: {e}", "attempts": 0}
    rv = outcome.get("review") or {}
    rec.update({"state": outcome.get("state"), "accepted": bool(outcome.get("accepted")), "attempts": outcome.get("attempts", 0),
                "provisional": bool(outcome.get("provisional")), "review_verdict": rv.get("verdict"), "review_applied": len(rv.get("applied", [])),
                "alt_model": (cfg.model.alt.model if cfg.model.alt else None),
                "formal": (outcome.get("formal") or {}).get("status") if isinstance(outcome.get("formal"), dict) else None,
                "status_line": outcome.get("status_line", ""), "wall_s": round(time.time() - t0, 1),
                "model_calls": runner.adapter.usage.calls, "tokens": runner.adapter.usage.total_tokens,
                "model_latency_s": round(runner.adapter.usage.latency_s, 1), "tool_time_s": round(runner.tool_time_s, 1)})
    # ---- independent golden check -------------------------------------------------------
    rec["golden_pass"] = False
    rec["golden_status"] = "not_run"
    spec = sorted((tdir / "spec").glob("contract.v*.json"))
    rtl = tdir / "rtl" / f"{task['expected']['module']}.v"
    if spec and rtl.is_file():
        contract = Contract.model_validate_json(spec[-1].read_text())
        problems = interface_matches(contract, task["expected"])
        rec["interface_problems"] = problems
        if problems:
            rec["golden_status"] = "interface_mismatch"
        else:
            golden = Path(task["dir"]) / "golden.py"
            gwork = tdir / "verification" / "golden_check"
            golden_cfg = cfg.model_copy(deep=True)
            golden_cfg.verification.require_formal = False
            golden_cfg.verification.run_formal = False
            res = verify(contract, rtl, golden, gwork, golden_cfg, cycles=task.get("golden_cycles", 600), seeds=task.get("golden_seeds", [101, 202, 303]), run_synth=False)
            rec["golden_status"] = res.stage if not res.accepted else "pass"
            rec["golden_pass"] = res.accepted
            rec["golden_summary"] = res.summary
            rec["golden_mismatches"] = [(s["seed"], s["status"], s["mismatches"]) for s in res.sims]
            if res.reference_error:
                rec["golden_status"] = "golden_error"
                rec["golden_summary"] = res.reference_error[:300]
    else:
        rec["golden_status"] = "no_rtl"
    rec["false_acceptance"] = bool(rec["accepted"] and not rec["golden_pass"] and rec["golden_status"] not in ("golden_error",))
    return rec


def run_suite(cfg: Config, suite: str, out: str, tasks: Optional[str] = None, budget: str = "20m", repeats: int = 1, log=print) -> int:
    only = [t.strip() for t in tasks.split(",")] if tasks else None
    tlist = load_tasks(suite, only)
    if not tlist:
        log(f"no tasks found for suite {suite}")
        return 2
    stamp = time.strftime("%Y%m%d-%H%M%S")
    out_root = Path(out) / f"{Path(suite).name}-{model_slug(cfg.model.model)}-{stamp}"
    out_root.mkdir(parents=True, exist_ok=True)
    records = []
    log(f"suite {suite}: {len(tlist)} tasks x {repeats} repeat(s) -> {out_root}")
    for task in tlist:
        for rep in range(repeats):
            rec = run_task(cfg, task, out_root, budget, rep, log)
            records.append(rec)
            (out_root / "records.jsonl").open("a").write(json.dumps(rec) + "\n")
            log(f"  => {task['id']}#{rep}: state={rec['state']} accepted={rec['accepted']} golden={rec['golden_status']} attempts={rec['attempts']} wall={rec['wall_s']}s")
    n = len(records)
    summary = {
        "suite": suite, "n": n, "tasks": len(tlist), "repeats": repeats, "budget": budget,
        "accepted": sum(r["accepted"] for r in records), "golden_pass": sum(r["golden_pass"] for r in records),
        "false_acceptance": sum(r["false_acceptance"] for r in records),
        "interface_mismatch": sum(r["golden_status"] == "interface_mismatch" for r in records),
        "states": {s: sum(r["state"] == s for r in records) for s in set(r["state"] for r in records)},
        "mean_wall_s": round(sum(r["wall_s"] for r in records) / n, 1), "mean_attempts": round(sum(r["attempts"] for r in records) / n, 2),
        "total_tokens": sum(r["tokens"] for r in records), "total_model_calls": sum(r["model_calls"] for r in records),
        "model": cfg.model.model_dump(), "verification": cfg.verification.model_dump(),
    }
    (out_root / "summary.json").write_text(json.dumps(summary, indent=1))
    md = [f"# Eval `{suite}` — {stamp}", "", f"n = {n} ({len(tlist)} tasks x {repeats}); budget {budget}; model `{cfg.model.model}` @ `{cfg.model.revision}` T={cfg.model.temperature} thinking={cfg.model.thinking}", "",
          f"- agent accepted: {summary['accepted']}/{n}", f"- golden pass (independent): {summary['golden_pass']}/{n}",
          f"- false acceptance: {summary['false_acceptance']}/{n}", f"- interface mismatch: {summary['interface_mismatch']}/{n}", "",
          "| task | rep | state | accepted | golden | formal | attempts | wall s | calls | tokens |", "|---|---|---|---|---|---|---|---|---|---|"]
    md += [f"| {r['task']} | {r['rep']} | {r['state']} | {r['accepted']} | {r['golden_status']} | {r.get('formal')} | {r['attempts']} | {r['wall_s']} | {r['model_calls']} | {r['tokens']} |" for r in records]
    (out_root / "summary.md").write_text("\n".join(md) + "\n")
    log("\n".join(md))
    return 0
