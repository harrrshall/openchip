"""Harness matrix: run several pipeline variants against several models, concurrently.

    openchip matrix run --spec configs/matrix/example.toml --dry-run   # cell count + plan
    openchip matrix run --spec configs/matrix/example.toml             # execute
    openchip matrix run --spec configs/matrix/example.toml --resume evals/matrix/20260913-101500
    openchip matrix report evals/matrix/20260913-101500               # scoreboard.md + .json

One cell = (harness, model, problem, repeat). Each cell owns a directory
`<out_root>/<stamp>/<harness>/<model>/rep<k>/<problem>/` and writes `record.json` there; a cell
whose record.json already exists is skipped, which is what makes `--resume` work. Cells run in a
thread pool bounded globally by `concurrency` and per model by that model's `max_concurrency`
(each cell has its own workspace and SQLite file, so parallel cells do not share state). A cell
that raises is recorded with state "error" and the matrix continues. Harness `vote3` is a
documented stub (see openchip.evals.harnesses.run_vote) and errors out per cell.
"""
from __future__ import annotations

import json
import os
import subprocess
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from pydantic import BaseModel, Field

from ..config import Config, model_slug
from .harnesses import Harness, deep_merge, get_harness

try:  # py311+
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib


# ----------------------------------------------------------------------------------- spec
class MatrixModel(BaseModel):
    name: str
    provider: Optional[str] = None
    base_url: Optional[str] = None
    base_url_env: Optional[str] = None     # read the base URL from this environment variable
    model: Optional[str] = None
    revision: Optional[str] = None
    api_key_env: Optional[str] = None
    user_agent: Optional[str] = None       # some gateways allow-list clients by User-Agent
    extra_body: Optional[dict] = None
    max_concurrency: int = 2
    overlay: dict = Field(default_factory=dict)   # free-form extra Config overlay for this model

    def slug(self) -> str:
        return model_slug(self.name)

    def to_overlay(self) -> dict:
        m: dict = {}
        for key in ("provider", "model", "revision", "api_key_env", "user_agent", "extra_body"):
            val = getattr(self, key)
            if val is not None:
                m[key] = val
        if self.base_url_env:
            url = os.environ.get(self.base_url_env)
            if url:
                m["base_url"] = url
        elif self.base_url:
            m["base_url"] = self.base_url
        return deep_merge({"model": m}, self.overlay)


class DatasetSpec(BaseModel):
    """VerilogEval v2 spec-to-rtl dataset selection."""
    path: str
    problems: Optional[list[str]] = None
    every_nth: Optional[int] = None   # keep problems 0, n, 2n, ... of the sorted list (awk 'NR%n==1')
    limit: Optional[int] = None


class SuiteSpec(BaseModel):
    """Project-owned task suite selection (evals/suite/<name>)."""
    name: str
    tasks: Optional[list[str]] = None


class MatrixSpec(BaseModel):
    out_root: str = "evals/matrix"
    repeats: int = 1
    budget: str = "10m"
    concurrency: int = 4
    config: Optional[str] = None          # base config TOML; default resolution when unset
    harnesses: list[str] = Field(default_factory=lambda: ["baseline"])
    models: list[MatrixModel] = Field(default_factory=list)
    dataset: Optional[DatasetSpec] = None
    suite: Optional[SuiteSpec] = None
    alt_model: Optional[dict] = None      # ModelConfig fields for the `alt-ref` harness

    @classmethod
    def load(cls, path: str | Path) -> "MatrixSpec":
        spec = cls.model_validate(tomllib.loads(Path(path).read_text()))
        if not spec.models:
            raise ValueError("matrix spec has no [[models]] block")
        if not spec.harnesses:
            raise ValueError("matrix spec has no harnesses")
        if (spec.dataset is None) == (spec.suite is None):
            raise ValueError("matrix spec needs exactly one of [dataset] or [suite]")
        for name in spec.harnesses:
            get_harness(name)   # fail fast on a typo
        return spec


# ----------------------------------------------------------------------------------- cells
@dataclass
class Cell:
    harness: Harness
    model: MatrixModel
    problem: str
    rep: int

    def dirname(self, root: Path) -> Path:
        return root / self.harness.name / self.model.slug() / f"rep{self.rep}" / self.problem

    def label(self) -> str:
        return f"{self.harness.name}/{self.model.name}/rep{self.rep}/{self.problem}"


def _git_sha(cwd: Path) -> str:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(cwd), capture_output=True,
                              text=True, timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError):  # pragma: no cover
        return ""


def load_problems_for(spec: MatrixSpec) -> list[dict]:
    """Return the work items: VerilogEval problems or suite tasks, each with an `id`."""
    if spec.dataset:
        from .verilogeval import load_problems
        ds = spec.dataset
        probs = load_problems(Path(ds.path), [p.strip() for p in ds.problems] if ds.problems else None)
        if ds.every_nth and ds.every_nth > 1:
            probs = probs[:: ds.every_nth]
        return probs[: ds.limit] if ds.limit else probs
    from .runner import load_tasks
    tasks = load_tasks(spec.suite.name, spec.suite.tasks)
    for t in tasks:
        t.setdefault("id", t.get("name", "task"))
    return tasks


def build_cells(spec: MatrixSpec, problems: list[dict]) -> list[Cell]:
    # Problem-major order so consecutive cells belong to different models: with a per-model concurrency cap,
    # a model-major queue would leave most workers blocked on one model's semaphore.
    cells = []
    for hname in spec.harnesses:
        h = get_harness(hname)
        for rep in range(spec.repeats):
            for p in problems:
                for m in spec.models:
                    cells.append(Cell(h, m, p["id"], rep))
    return cells


def cell_config(spec: MatrixSpec, cell: Cell, base: Config) -> Config:
    """Base config + model overlay + harness overlay + per-repeat seed and budget."""
    from ..cli.main import _parse_duration
    from .harnesses import apply_overlay

    cfg = apply_overlay(base, cell.model.to_overlay())
    cfg = cell.harness.config(cfg, spec.alt_model)
    if cfg.model.seed is not None:
        cfg.model.seed = cfg.model.seed + cell.rep
    cfg.budget.wall_time_s = _parse_duration(spec.budget)
    return cfg


# ----------------------------------------------------------------------------------- execution
def execute_cell(cfg: Config, cell: Cell, problem: dict, work: Path, budget_s: float, log) -> dict:
    """Run one problem under one harness. Returns the raw record from the existing runners."""
    if cell.harness.mode == "vote":
        from .harnesses import run_vote
        return run_vote(cfg, problem, work, budget_s, log)
    if cell.harness.mode == "direct":
        from ..models.adapter import ModelAdapter
        from .verilogeval import run_direct
        return run_direct(cfg, problem, work, ModelAdapter(cfg.model, cfg.api_key()), log)
    if "prompt" in problem:                    # VerilogEval v2 problem
        from .verilogeval import run_agent
        return run_agent(cfg, problem, work, budget_s, log)
    from .runner import run_task               # project-owned suite task (golden re-verification)
    return run_task(cfg, problem, work.parent, spec_budget(budget_s), cell.rep, log, work=work)


def spec_budget(budget_s: float) -> str:
    return f"{budget_s:g}s"


def _normalize(raw: dict, cell: Cell, cfg: Config, wall_s: float) -> dict:
    """One record shape for every harness, so the scoreboard never branches on mode."""
    status = raw.get("status") or raw.get("golden_status")
    if status == "not_run":
        status = None
    passed = status == "pass"
    accepted = raw.get("accepted") if cell.harness.mode != "direct" else None
    rec = {
        "harness": cell.harness.name, "mode": cell.harness.mode, "model": cell.model.name,
        "model_id": cfg.model.model, "rep": cell.rep, "seed": cfg.model.seed, "problem": cell.problem,
        "state": raw.get("state") or status or "unknown", "status": status, "pass": passed,
        "accepted": accepted, "provisional": bool(raw.get("provisional")),
        "false_acceptance": bool(accepted) and not passed,
        "attempts": raw.get("attempts", 0),
        "model_calls": raw.get("calls", raw.get("model_calls", 0)),
        "tokens": raw.get("tokens", 0), "tool_time_s": raw.get("tool_time_s", 0.0),
        "wall_s": raw.get("wall_s", round(wall_s, 1)), "error": raw.get("error", ""),
        "detail": str(raw.get("detail", ""))[:500],
    }
    return rec


def run_cell(spec: MatrixSpec, cell: Cell, problem: dict, base: Config, root: Path, log,
             execute: Callable = execute_cell) -> dict:
    """Own the bookkeeping around one cell: directory, timing, record.json, error capture."""
    from ..cli.main import _parse_duration

    work = cell.dirname(root)
    record_path = work / "record.json"
    if record_path.is_file():
        rec = json.loads(record_path.read_text())
        rec["skipped"] = True
        return rec
    work.parent.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    cfg = base
    try:
        cfg = cell_config(spec, cell, base)
        raw = execute(cfg, cell, problem, work, _parse_duration(spec.budget), log)
        rec = _normalize(raw, cell, cfg, time.time() - t0)
    except Exception as e:  # noqa: BLE001 - a bad cell must never stop the matrix
        rec = _normalize({"state": "error", "status": "error", "accepted": False,
                          "error": f"{type(e).__name__}: {e}", "detail": traceback.format_exc()[-1500:]},
                         cell, cfg, time.time() - t0)
    work.mkdir(parents=True, exist_ok=True)
    record_path.write_text(json.dumps(rec, indent=1))
    return rec


def run_matrix(spec: MatrixSpec, resume: Optional[str] = None, concurrency: Optional[int] = None,
               dry_run: bool = False, log=print, execute: Callable = execute_cell) -> dict:
    problems = load_problems_for(spec)
    if not problems:
        log("no problems/tasks selected")
        return {"root": None, "cells": 0, "error": "no problems"}
    by_id = {p["id"]: p for p in problems}
    cells = build_cells(spec, problems)
    workers = concurrency or spec.concurrency

    plan = (f"matrix: {len(spec.harnesses)} harness(es) x {len(spec.models)} model(s) x "
            f"{len(problems)} problem(s) x {spec.repeats} repeat(s) = {len(cells)} cells; "
            f"concurrency {workers} (per model: "
            + ", ".join(f"{m.name}={m.max_concurrency}" for m in spec.models) + f"); budget {spec.budget}/cell")
    if dry_run:
        log(plan)
        log("harnesses: " + ", ".join(f"{get_harness(h).name} [{get_harness(h).mode}]" for h in spec.harnesses))
        log("problems: " + ", ".join(p["id"] for p in problems[:8]) + (" ..." if len(problems) > 8 else ""))
        for c in cells[:5]:
            log(f"  cell {c.label()} -> <root>/{c.harness.name}/{c.model.slug()}/rep{c.rep}/{c.problem}/")
        if len(cells) > 5:
            log(f"  ... and {len(cells) - 5} more")
        return {"root": None, "cells": len(cells), "plan": plan, "dry_run": True}

    root = Path(resume) if resume else Path(spec.out_root) / time.strftime("%Y%m%d-%H%M%S")
    root.mkdir(parents=True, exist_ok=True)
    base = Config.load(spec.config)
    (root / "manifest.json").write_text(json.dumps({
        "spec": spec.model_dump(mode="json"), "git_sha": _git_sha(Path(__file__).resolve().parents[3]),
        "started": time.strftime("%Y-%m-%dT%H:%M:%S"), "cells": len(cells), "concurrency": workers,
        "problems": [p["id"] for p in problems], "resumed": bool(resume)}, indent=1))
    log(plan + f" -> {root}")

    sems = {m.name: threading.Semaphore(max(1, m.max_concurrency)) for m in spec.models}
    progress = root / "progress.log"
    lock = threading.Lock()
    done = {"n": 0, "errors": 0, "skipped": 0}

    def work(cell: Cell) -> dict:
        with sems[cell.model.name]:
            return run_cell(spec, cell, by_id[cell.problem], base, root, log, execute)

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = {pool.submit(work, c): c for c in cells}
        for fut in as_completed(futures):
            cell = futures[fut]
            try:
                rec = fut.result()
            except Exception as e:  # noqa: BLE001 - defensive; run_cell already catches
                rec = {"state": "error", "error": str(e), "pass": False, "skipped": False}
            with lock:
                done["n"] += 1
                done["errors"] += rec.get("state") == "error"
                done["skipped"] += bool(rec.get("skipped"))
                line = (f"[{done['n']}/{len(cells)}] {cell.label()}: state={rec.get('state')} "
                        f"pass={rec.get('pass')} accepted={rec.get('accepted')} "
                        f"tokens={rec.get('tokens')} wall={rec.get('wall_s')}s"
                        + (" (skipped, already recorded)" if rec.get("skipped") else ""))
                with progress.open("a") as f:
                    f.write(line + "\n")
                log(line)
    summary = {"root": str(root), "cells": len(cells), "done": done["n"], "errors": done["errors"],
               "skipped": done["skipped"], "wall_s": round(time.time() - t0, 1)}
    (root / "run_summary.json").write_text(json.dumps(summary, indent=1))
    log(f"matrix finished: {done['n']} cells, {done['errors']} error(s), {done['skipped']} skipped, "
        f"{summary['wall_s']}s -> {root}")
    return summary
