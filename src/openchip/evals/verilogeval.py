"""VerilogEval v2 (NVlabs, MIT) spec-to-rtl adapter.

Two protocols, reported separately and never mixed:
  direct : one model call per problem (prompt -> Verilog), pass@1 at the configured temperature.
           This is the like-for-like baseline comparable to published single-generation numbers.
  agent  : the full OpenChip pipeline (contract, reference, RTL, tool-driven repair, corroboration).
           Multi-call with tool feedback; NOT comparable to single-generation pass@1.
Scoring uses the benchmark's own `<prob>_test.sv` + `<prob>_ref.sv` with Icarus (as upstream does):
the generated module must be named `TopModule`; the testbench prints "Mismatches: N in M samples".

Usage: openchip veval --dataset /path/to/verilog-eval/dataset_spec-to-rtl --mode direct|agent [--limit N] [--problems a,b]
Contamination of the public benchmark in the model's training data is unknowable; disclose it.
"""
from __future__ import annotations

import json
import re
import shutil
import time
from pathlib import Path
from typing import Optional

from ..config import Config, model_slug
from ..models.adapter import ModelAdapter, extract_code
from ..tools import iverilog
from ..runtime.run import Runner
from ..runtime.workspace import Workspace

DIRECT_SYSTEM = """You are a Verilog RTL engineer. Implement exactly the module requested, named TopModule, with the exact ports given. Synthesizable Verilog-2001 (SystemVerilog `logic`/`always_ff` are acceptable only if the prompt uses them). Reply with the complete module in a single ```verilog fenced block and nothing else."""

MISMATCH_RE = re.compile(r"Mismatches:\s*(\d+)\s+in\s+(\d+)\s+samples")


def load_problems(dataset: Path, only: Optional[list[str]] = None, limit: Optional[int] = None) -> list[dict]:
    probs = []
    for prompt in sorted(dataset.glob("*_prompt.txt")):
        pid = prompt.name[: -len("_prompt.txt")]
        if only and pid not in only:
            continue
        probs.append({"id": pid, "prompt": prompt.read_text(), "ref": dataset / f"{pid}_ref.sv", "test": dataset / f"{pid}_test.sv"})
    return probs[:limit] if limit else probs


def score(rtl: Path, prob: dict, work: Path, cfg: Config) -> dict:
    """Compile TopModule + RefModule + upstream testbench and parse the mismatch line."""
    work.mkdir(parents=True, exist_ok=True)
    shutil.copy(prob["ref"], work / "ref.sv")
    # Upstream testbenches reference `tb_mismatch` in $dumpvars before its declaration; Icarus 14 rejects
    # that. Waveform dumping is irrelevant to scoring, so those lines are dropped (nothing else changes).
    test_src = "\n".join(ln for ln in prob["test"].read_text().splitlines() if "$dumpvars" not in ln and "$dumpfile" not in ln)
    (work / "test.sv").write_text(test_src + "\n")
    shutil.copy(rtl, work / "top.sv")
    comp = iverilog.compile_verilog(["top.sv", "ref.sv", "test.sv"], "tb", "sim.vvp", work, cfg.tools.iverilog, cfg.tools.timeout_s, generation="2012", defines=None)
    if not comp.ok:
        return {"status": "compile_error", "detail": comp.tail(8)}
    sim = iverilog.simulate("sim.vvp", work, cfg.tools.vvp, cfg.tools.timeout_s)
    m = MISMATCH_RE.search(sim.stdout)
    if not m:
        return {"status": "sim_error", "detail": sim.tail(8)}
    n, total = int(m.group(1)), int(m.group(2))
    return {"status": "pass" if n == 0 else "fail", "mismatches": n, "samples": total}


def run_direct(cfg: Config, prob: dict, work: Path, adapter: ModelAdapter, log) -> dict:
    t0 = time.time()
    r = adapter.chat([{"role": "system", "content": DIRECT_SYSTEM}, {"role": "user", "content": prob["prompt"]}], role="direct", thinking=(cfg.model.thinking_roles is None and cfg.model.thinking) or (cfg.model.thinking_roles is not None and "rtl" in cfg.model.thinking_roles))
    code = extract_code(r.text, ("verilog", "systemverilog", "v", "sv")) if r.ok else None
    rec = {"id": prob["id"], "mode": "direct", "calls": 1, "tokens": r.prompt_tokens + r.completion_tokens, "latency_s": round(r.latency_s, 1), "finish": r.finish_reason}
    if not code:
        rec.update({"status": "no_code", "detail": r.error or r.finish_reason})
        return rec
    work.mkdir(parents=True, exist_ok=True)
    rtl = work / "TopModule.sv"
    rtl.write_text(code)
    rec.update(score(rtl, prob, work / "score", cfg))
    rec["wall_s"] = round(time.time() - t0, 1)
    return rec


def run_agent(cfg: Config, prob: dict, work: Path, budget_s: float, log) -> dict:
    t0 = time.time()
    ws = Workspace(work)
    if work.exists():
        shutil.rmtree(work)
    ws.init(request=prob["prompt"], name=prob["id"])
    runner = Runner(ws, cfg, log=lambda m: log(f"  [{prob['id']}] {m}"))
    runner.start(prob["prompt"], budget_s=budget_s)
    try:
        outcome = runner.execute()
    except Exception as e:  # noqa: BLE001
        outcome = {"state": "failed", "accepted": False, "status_line": f"crash: {e}", "attempts": 0}
    rv = outcome.get("review") or {}
    rec = {"id": prob["id"], "mode": "agent", "state": outcome.get("state"), "accepted": bool(outcome.get("accepted")), "attempts": outcome.get("attempts", 0),
           "provisional": bool(outcome.get("provisional")), "review_verdict": rv.get("verdict"), "review_applied": len(rv.get("applied", [])),
           "calls": runner.adapter.usage.calls, "tokens": runner.adapter.usage.total_tokens, "wall_s": round(time.time() - t0, 1),
           "intake_escalations": sum(1 for e in runner.escalations if e.get("role") == "intake"),
           "escalations": runner.escalations}
    rtl = work / "rtl" / "TopModule.v"
    if rtl.is_file():
        rec.update(score(rtl, prob, work / "verification" / "veval_score", cfg))
    else:
        rec["status"] = "no_rtl"
    rec["false_acceptance"] = bool(rec["accepted"] and rec.get("status") != "pass")
    return rec


def run_benchmark(cfg: Config, dataset: str, mode: str, out: str, problems: Optional[str] = None, limit: Optional[int] = None, budget: str = "10m", log=print) -> int:
    from ..cli.main import _parse_duration
    ds = Path(dataset)
    probs = load_problems(ds, [p.strip() for p in problems.split(",")] if problems else None, limit)
    if not probs:
        log("no problems found")
        return 2
    stamp = time.strftime("%Y%m%d-%H%M%S")
    out_root = Path(out) / f"verilogeval-v2-{mode}-{model_slug(cfg.model.model)}-{stamp}"
    out_root.mkdir(parents=True, exist_ok=True)
    adapter = ModelAdapter(cfg.model, cfg.api_key())
    log(f"VerilogEval v2 spec-to-rtl, mode={mode}, n={len(probs)}, model={cfg.model.model}@{cfg.model.revision} T={cfg.model.temperature} -> {out_root}")
    recs = []
    for i, prob in enumerate(probs):
        work = out_root / prob["id"]
        rec = run_direct(cfg, prob, work, adapter, log) if mode == "direct" else run_agent(cfg, prob, work, _parse_duration(budget), log)
        recs.append(rec)
        (out_root / "records.jsonl").open("a").write(json.dumps(rec) + "\n")
        log(f"  [{i + 1}/{len(probs)}] {prob['id']}: {rec.get('status')} " + (f"(accepted={rec.get('accepted')})" if mode == "agent" else "") + f" {rec.get('wall_s', rec.get('latency_s'))}s")
    n = len(recs)
    npass = sum(r.get("status") == "pass" for r in recs)
    summary = {"benchmark": "VerilogEval v2 spec-to-rtl (NVlabs verilog-eval, MIT)", "mode": mode, "n": n, "pass": npass, "pass_rate": round(npass / n, 4),
               "provisional_acceptances": sum(bool(r.get("provisional")) for r in recs) if mode == "agent" else None,
               "false_acceptance_excluding_provisional": sum(bool(r.get("false_acceptance")) and not r.get("provisional") for r in recs) if mode == "agent" else None,
               "review": {"enabled": cfg.review.enabled, "alt_model": cfg.model.alt.model if cfg.model.alt else None, "review_model": cfg.model.review.model if cfg.model.review else None},
               "statuses": {s: sum(r.get("status") == s for r in recs) for s in set(r.get("status") for r in recs)},
               "false_acceptance": sum(bool(r.get("false_acceptance")) for r in recs) if mode == "agent" else None,
               "total_calls": sum(r.get("calls", 0) for r in recs), "total_tokens": sum(r.get("tokens", 0) for r in recs),
               "model": cfg.model.model_dump(), "protocol": ("single generation, pass@1" if mode == "direct" else f"full OpenChip pipeline with tool feedback, budget {budget}/problem; not comparable to single-generation pass@1"),
               "contamination": "unknown (public benchmark)"}
    (out_root / "summary.json").write_text(json.dumps(summary, indent=1))
    md = [f"# VerilogEval v2 spec-to-rtl — mode `{mode}` — {stamp}", "", f"n = {n}; pass = {npass} ({summary['pass_rate'] * 100:.1f}%); protocol: {summary['protocol']}",
          f"model `{cfg.model.model}` @ `{cfg.model.revision}` T={cfg.model.temperature} thinking_roles={cfg.model.thinking_roles}", "",
          "| problem | status | " + ("accepted | attempts | " if mode == "agent" else "") + "calls | tokens | wall s |", "|---|---|" + ("---|---|" if mode == "agent" else "") + "---|---|---|"]
    for r in recs:
        md.append(f"| {r['id']} | {r.get('status')} | " + (f"{r.get('accepted')} | {r.get('attempts')} | " if mode == "agent" else "") + f"{r.get('calls')} | {r.get('tokens')} | {r.get('wall_s', r.get('latency_s'))} |")
    (out_root / "summary.md").write_text("\n".join(md) + "\n")
    log("\n".join(md[:4]))
    return 0
