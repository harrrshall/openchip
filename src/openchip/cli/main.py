"""OpenChip command-line interface."""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from .. import __version__
from ..config import Config


def _cfg(args) -> Config:
    return Config.load(getattr(args, "config", None))


def _read_request(arg: str | None) -> str | None:
    """A request argument may be a path to a file or literal text."""
    if not arg:
        return None
    try:
        p = Path(arg)
        if len(arg) < 4096 and p.is_file():
            return p.read_text()
    except OSError:
        pass
    return arg


def cmd_doctor(args) -> int:
    from ..models.adapter import ModelAdapter
    from ..tools.base import tool_version, which
    from ..verification.sandbox import sandbox_status

    cfg = _cfg(args)
    print(f"openchip {__version__}  python {sys.version.split()[0]}")
    ok = True
    for name in ("iverilog", "vvp", "verilator", "yosys", "sby"):
        exe = getattr(cfg.tools, name)
        path = which(exe)
        ver = tool_version(exe, ("-V",) if name in ("iverilog", "vvp", "yosys") else ("--version",)) if path else ""
        print(f"  {name:10} {'ok     ' if path else 'MISSING'} {path or ''}  {ver}")
        if not path and name != "sby":
            ok = False
    sandbox = sandbox_status()
    print(f"  sandbox    {'ok' if sandbox['ok'] else 'UNAVAILABLE'} {sandbox.get('error') or sandbox['version']}")
    ok = ok and sandbox["ok"]
    h = ModelAdapter(cfg.model, cfg.api_key()).health()
    print(f"  model      {'ok     ' if h.get('ok') else 'UNREACH'} {cfg.model.base_url} -> {cfg.model.model}"
          + (f"  served={h.get('served_models')}" if h.get("ok") else f"  ({h.get('error')})"))
    if h.get("ok") and not h.get("configured_is_served"):
        print("  WARNING: configured model is not in the served list")
    print("  features   contract validation, reference-vs-RTL simulation (iverilog), verilator lint, yosys generic synth; formal (sby) optional; no timing/power")
    return 0 if ok else 1


def cmd_init(args) -> int:
    from ..runtime.workspace import Workspace

    ws = Workspace(args.project)
    request = _read_request(args.request)
    ws.init(request=request, name=args.name)
    print(f"initialized workspace {ws.root}" + (" with request" if request else ""))
    return 0


def _parse_duration(s: str) -> float:
    units = {"s": 1, "m": 60, "h": 3600}
    if s[-1] in units:
        return float(s[:-1]) * units[s[-1]]
    return float(s)


def cmd_build(args) -> int:
    from ..runtime.run import Runner
    from ..runtime.workspace import Workspace

    cfg = _cfg(args)
    ws = Workspace(args.project)
    request = _read_request(args.request)
    if not ws.exists():
        ws.init(request=request)
    elif request:
        (ws.root / "request" / "request.md").write_text(request.strip() + "\n")
    request = ws.request_text().strip()
    if not request:
        print("error: no request. Pass --request <file-or-text> or write request/request.md", file=sys.stderr)
        return 2
    runner = Runner(ws, cfg, log=_logger())
    budget = _parse_duration(args.budget) if args.budget else None
    if budget:
        cfg.budget.wall_time_s = budget
    run_id = runner.start(request, budget_s=budget)
    print(f"run {run_id} started in {ws.root}")
    outcome = runner.execute()
    print(json.dumps({k: outcome.get(k) for k in ("run_id", "state", "accepted", "status_line", "attempts")}, indent=1))
    return 0 if outcome.get("accepted") else 3


def cmd_resume(args) -> int:
    from ..runtime.run import Runner
    from ..runtime.store import RunStore
    from ..runtime.workspace import Workspace

    ws = Workspace(args.project)
    if not ws.db_path.is_file():
        print("error: no run to resume", file=sys.stderr)
        return 2
    store = RunStore(ws.db_path)
    try:
        run_id = args.run or store.latest_run_id()
        run = store.get_run(run_id) if run_id else None
    finally:
        store.close()
    if not run:
        print("error: no matching run to resume", file=sys.stderr)
        return 2
    if run["state"] == "completed":
        print(f"run {run_id} already completed")
        return 0 if run["outcome"].get("accepted") else 3
    # Resume the recorded model/tool/verification configuration, just as the UI
    # does. Current directory defaults must not silently change a saved run.
    cfg = Config.model_validate(run["config"])
    runner = Runner(ws, cfg, log=_logger())
    try:
        runner.resume(run_id)
        print(f"resuming run {run_id} from step {run['step']}")
        outcome = runner.execute()
    finally:
        runner.store.close()
    print(json.dumps({k: outcome.get(k) for k in ("run_id", "state", "accepted", "status_line", "attempts")}, indent=1))
    return 0 if outcome.get("accepted") else 3


def cmd_revise(args) -> int:
    """Apply a change request: new contract version, invalidated evidence, targeted re-run."""
    from ..runtime.run import Runner
    from ..runtime.workspace import Workspace

    cfg = _cfg(args)
    ws = Workspace(args.project)
    change = _read_request(args.change)
    if not change:
        print("error: --change is required", file=sys.stderr)
        return 2
    runner = Runner(ws, cfg, log=_logger())
    budget = _parse_duration(args.budget) if args.budget else None
    run_id = runner.revise(change, budget_s=budget)
    print(f"revision run {run_id} started in {ws.root}")
    outcome = runner.execute()
    print(json.dumps({k: outcome.get(k) for k in ("run_id", "state", "accepted", "status_line", "attempts", "contract_version")}, indent=1))
    return 0 if outcome.get("accepted") else 3


def cmd_status(args) -> int:
    from ..runtime.store import RunStore
    from ..runtime.workspace import Workspace

    ws = Workspace(args.project)
    if not ws.db_path.is_file():
        print("no runs")
        return 0
    store = RunStore(ws.db_path)
    runs = store.list_runs()
    if args.run:
        runs = [r for r in runs if r["run_id"] == args.run]
    for r in runs:
        full = store.get_run(r["run_id"])
        ck = full["checkpoint"] if full else {}
        hist = ck.get("history", [])
        last = hist[-1]["summary"] if hist else "-"
        print(f"{r['run_id']}  state={r['state']:16} step={r['step']:10} attempts={len(hist)}  last: {last}")
        if args.verbose and full:
            for e in store.events(r["run_id"]):
                print("   ", time.strftime("%H:%M:%S", time.localtime(e["ts"])), e["kind"], {k: v for k, v in e.items() if k not in ("ts", "kind")})
    return 0


def cmd_report(args) -> int:
    from ..runtime.workspace import Workspace

    ws = Workspace(args.project)
    composition_outcome = ws.root / "outcome.json"
    if composition_outcome.is_file():
        outcome = json.loads(composition_outcome.read_text())
        if isinstance(outcome, dict) and "leaves" in outcome and "integration" in outcome:
            from ..reporting.composition import render_composition_report
            print(composition_outcome.read_text() if args.json else render_composition_report(outcome))
            return 0
    p = ws.root / "reports" / ("outcome.json" if args.json else "report.md")
    if not p.is_file():
        print("no report yet", file=sys.stderr)
        return 1
    from ..reporting.integrity import workspace_outcome, integrity_warning
    recorded = ws.root / "reports" / "outcome.json"
    outcome = json.loads(recorded.read_text()) if recorded.is_file() else {}
    current = workspace_outcome(ws.root, outcome)
    print(json.dumps(current, indent=2) if args.json else integrity_warning(current) + p.read_text())
    return 0


def positive_cycles(value: str) -> int:
    try:
        cycles = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("cycles must be a positive integer") from None
    if cycles < 1:
        raise argparse.ArgumentTypeError("cycles must be a positive integer")
    return cycles


def cmd_verify(args) -> int:
    """Re-run verification of delivered artifacts (no model calls)."""
    import sqlite3
    import tempfile
    from ..contracts.schema import Contract
    from ..runtime.workspace import Workspace
    from ..verification.harness import verify
    from ..verification.tablecheck import check_reference_against_request_tables
    from ..verification.clockcheck import check_clock
    from ..verification.lfsrcheck import check_lfsr, lfsr_properties
    from ..verification.history import prior_simulation_failures, prior_formal_failures
    from ..reporting.report import sign_off_withheld

    cfg = _cfg(args)
    ws = Workspace(args.project)
    spec = ws.dir("spec")
    contracts = sorted(spec.glob("contract.v*.json"), key=lambda p: int(p.stem.split(".v")[1]))
    if not contracts:
        print("no contract found", file=sys.stderr)
        return 1
    contract = Contract.model_validate_json(contracts[-1].read_text())
    rtl = ws.dir("rtl") / f"{contract.module_name}.v"
    ref = ws.dir("reference") / "reference.py"
    work = Path(tempfile.mkdtemp(prefix="reverify-", dir=ws.dir("verification")))
    seeds = [int(s) for s in args.seeds.split(",")] if args.seeds else None
    ck = {"request": ws.request_text()}
    # Keep the request's revision history and any unresolved reference disagreement.
    # Read-only access leaves the original run and its outcome untouched.
    if ws.db_path.is_file():
        db = sqlite3.connect(ws.db_path.as_uri() + "?mode=ro", uri=True)
        try:
            row = db.execute("SELECT checkpoint_json FROM runs ORDER BY created DESC LIMIT 1").fetchone()
            prior = json.loads(row[0]) if row else {}
            if prior.get("contract_version") == contract.version:
                ck.update({k: prior[k] for k in ("request", "consensus") if k in prior})
        finally:
            db.close()
    props = ws.dir("verification") / f"{contract.module_name}_props.v"
    from ..verification.cellularformal import cellular_properties
    trusted_props = lfsr_properties(contract, ck["request"]) if cfg.verification.run_formal else None
    properties_origin = "request-derived Galois transitions" if trusted_props else "existing checker"
    if trusted_props is None and cfg.verification.run_formal:
        trusted_props = cellular_properties(contract, ck["request"])
        if trusted_props:
            properties_origin = "request-derived cell-transition table"
    if trusted_props is None and cfg.verification.run_formal:
        from ..verification.directionalformal import directional_properties
        trusted_props = directional_properties(contract, ck["request"])
        if trusted_props:
            properties_origin = "request-derived directional transitions"
    if trusted_props is None and cfg.verification.run_formal:
        from ..verification.packetformal import packet_properties
        trusted_props = packet_properties(contract, ck["request"])
        if trusted_props:
            properties_origin = "request-derived packet framing"
    if trusted_props is None and cfg.verification.run_formal:
        from ..verification.mooreformal import moore_properties
        trusted_props = moore_properties(contract, ck["request"])
        if trusted_props:
            properties_origin = "request-derived Moore transition table"
    if trusted_props is None and cfg.verification.run_formal:
        from ..verification.hdlcformal import hdlc_properties
        trusted_props = hdlc_properties(contract, ck["request"])
        if trusted_props:
            properties_origin = "request-derived HDLC framing"
    if trusted_props is not None:
        props = work / f"{contract.module_name}_props.v"
        props.write_text(trusted_props)
    res = verify(contract, rtl, ref, work, cfg, cycles=args.cycles, seeds=seeds,
                 props_path=props if props.is_file() else None)
    evidence = res.to_dict()
    ck["request_table_check"] = check_reference_against_request_tables(
        contract, ck["request"], ref, work / "request_tables")
    ck["clock_check"] = check_clock(contract, ck["request"], rtl, work / "clock_check", cfg)
    ck["lfsr_check"] = check_lfsr(contract, ck["request"], ref, work / "lfsr_check")
    from ..verification.consensus import recheck_consensus
    consensus_recheck = recheck_consensus(
        ck.get("consensus"), contract, rtl, ref, res, work / "consensus", cfg,
        cfg.verification.sim_cycles if args.cycles is None else args.cycles,
        cfg.verification.seeds if seeds is None else seeds)
    withheld = sign_off_withheld(ck, evidence, contract)
    if consensus_recheck["status"] not in {"pass", "not_applicable"}:
        reason = "retained reference consensus was not re-established: " + consensus_recheck["detail"]
        withheld = "; ".join(filter(None, (withheld, reason)))
    prior_failures = prior_simulation_failures(ws.root, res.artifacts)
    if prior_failures:
        reason = ("recorded simulation mismatches remain unresolved for this unchanged RTL, "
                  "reference and contract; a passing recheck does not clear those failing traces")
        withheld = "; ".join(filter(None, (withheld, reason)))
    formal_failures = prior_formal_failures(ws.root, res.artifacts, res.formal)
    if formal_failures:
        reason = ("recorded formal counterexamples remain unresolved for this unchanged RTL "
                  "and contract; skipping or shortening formal checking does not clear them. "
                  "Review the RTL/checker; a corrected checker must pass at least the recorded depth")
        withheld = "; ".join(filter(None, (withheld, reason)))
    accepted = res.accepted and not withheld
    evidence.update(accepted=accepted, sign_off_withheld=withheld,
                    consensus_recheck=consensus_recheck,
                    historical_consensus=ck.get("consensus"),
                    prior_simulation_failures=prior_failures,
                    prior_formal_failures=formal_failures,
                    request_table_check=ck["request_table_check"], clock_check=ck["clock_check"],
                    lfsr_check=ck["lfsr_check"],
                    properties_origin=properties_origin,
                    contract_path=str(contracts[-1]), contract_version=contract.version)
    (work / "evidence.json").write_text(json.dumps(evidence, indent=2))
    print(json.dumps({"accepted": accepted, "stage": res.stage,
                      "summary": withheld or res.summary, "sign_off_withheld": withheld,
                      "contract_version": contract.version, "evidence_path": str(work / "evidence.json"),
                      "sims": [(s["seed"], s["status"], s["mismatches"]) for s in res.sims]}, indent=1))
    return 0 if accepted else 3


def cmd_compose(args) -> int:
    from ..runtime.composition import compose

    request = _read_request(args.request)
    if not request:
        print("error: --request must contain a hardware request", file=sys.stderr)
        return 2
    outcome = compose(Path(args.project), request, _cfg(args), _parse_duration(args.budget), log=_logger())
    print(json.dumps({k: outcome.get(k) for k in ("state", "accepted", "reason", "elapsed_s")}, indent=2))
    return 0 if outcome.get("accepted") else 3


def cmd_assemble(args) -> int:
    from ..contracts.system import SystemContract, render_top

    system = SystemContract.model_validate_json(Path(args.system).read_text())
    text = render_top(system)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("x") as f:
        f.write(text)
    print(f"Wrote {out}: {len(system.modules)} instances, {len(system.connections)} connections.")
    print("Structural assembly only. Leaf acceptance and behavioral integration remain unverified.")
    for item in system.unresolved_items():
        print(f"Unresolved: {item}")
    return 0


def cmd_eval(args) -> int:
    from ..evals.runner import run_suite

    cfg = _cfg(args)
    return run_suite(cfg, args.suite, args.out, tasks=args.tasks, budget=args.budget, repeats=args.repeats, log=_logger())


def cmd_veval(args) -> int:
    from ..evals.verilogeval import run_benchmark

    cfg = _cfg(args)
    return run_benchmark(cfg, args.dataset, args.mode, args.out, problems=args.problems, limit=args.limit, budget=args.budget, log=_logger())


def cmd_ui(args) -> int:
    from ..ui.server import serve

    serve(args.host, args.port, open_browser=args.open)
    return 0


def _logger():
    t0 = time.time()

    def log(msg: str) -> None:
        print(f"[{time.time() - t0:7.1f}s] {msg}", flush=True)

    return log


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="openchip", description="Natural-language request -> RTL project with verification evidence.")
    p.add_argument("--config", help="config TOML (default: ./openchip.toml or configs/default.toml)")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("doctor", help="report prerequisites, tool versions, model connectivity")
    s.set_defaults(fn=cmd_doctor)
    s = sub.add_parser("init", help="create a design workspace")
    s.add_argument("project")
    s.add_argument("--request", help="request text or path to a file")
    s.add_argument("--name")
    s.set_defaults(fn=cmd_init)
    s = sub.add_parser("build", help="run the full request -> RTL -> verification pipeline")
    s.add_argument("--project", required=True)
    s.add_argument("--request", help="request text or path; overrides request/request.md")
    s.add_argument("--budget", help="wall-time budget, e.g. 20m, 2h")
    s.set_defaults(fn=cmd_build)
    s = sub.add_parser("revise", help="apply a change request: new contract version, re-verify")
    s.add_argument("--project", required=True)
    s.add_argument("--change", required=True, help="change request text or path")
    s.add_argument("--budget")
    s.set_defaults(fn=cmd_revise)
    s = sub.add_parser("resume", help="resume an interrupted run")
    s.add_argument("--project", required=True)
    s.add_argument("--run")
    s.set_defaults(fn=cmd_resume)
    s = sub.add_parser("status", help="show runs in a workspace")
    s.add_argument("--project", required=True)
    s.add_argument("--run")
    s.add_argument("-v", "--verbose", action="store_true")
    s.set_defaults(fn=cmd_status)
    s = sub.add_parser("report", help="print the latest delivery report")
    s.add_argument("--project", required=True)
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_report)
    s = sub.add_parser("verify", help="re-run verification on delivered artifacts")
    s.add_argument("--project", required=True)
    s.add_argument("--cycles", type=positive_cycles)
    s.add_argument("--seeds", help="comma-separated seeds")
    s.set_defaults(fn=cmd_verify)
    s = sub.add_parser("compose", help="build and verify a small multi-module system from a request")
    s.add_argument("--project", required=True, help="new system workspace (must not exist)")
    s.add_argument("--request", required=True)
    s.add_argument("--budget", default="20m")
    s.set_defaults(fn=cmd_compose)
    s = sub.add_parser("assemble", help="validate pinned module connections and generate top-level RTL")
    s.add_argument("--system", required=True, help="system contract JSON")
    s.add_argument("--out", required=True, help="new top-level Verilog file (must not exist)")
    s.set_defaults(fn=cmd_assemble)
    s = sub.add_parser("eval", help="run an evaluation suite")
    s.add_argument("--suite", required=True)
    s.add_argument("--out", default="evals/results")
    s.add_argument("--tasks", help="comma-separated task ids (default: all)")
    s.add_argument("--budget", default="20m")
    s.add_argument("--repeats", type=int, default=1)
    s.set_defaults(fn=cmd_eval)
    s = sub.add_parser("ui", help="start the local web UI")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8765)
    s.add_argument("--open", action="store_true", help="open a browser tab")
    s.set_defaults(fn=cmd_ui)
    s = sub.add_parser("veval", help="run VerilogEval v2 spec-to-rtl (direct single-shot or full agent)")
    s.add_argument("--dataset", required=True, help="path to verilog-eval/dataset_spec-to-rtl")
    s.add_argument("--mode", choices=["direct", "agent"], default="direct")
    s.add_argument("--out", default="evals/results")
    s.add_argument("--problems", help="comma-separated problem ids")
    s.add_argument("--limit", type=int)
    s.add_argument("--budget", default="10m")
    s.set_defaults(fn=cmd_veval)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
