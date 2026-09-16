"""Run orchestrator: intake -> contract -> reference -> RTL -> verify -> bounded repair -> report.

Every step checkpoints to the run store so a run can be resumed after interruption. Model
output is validated as untrusted input; a malformed reply is a recorded failure and a bounded
retry. Failed candidates are preserved under verification/attempts/.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from pydantic import ValidationError

from ..config import Config
from ..contracts.coerce import coerce_contract
from ..contracts.schema import Contract, contract_json_schema
from ..models import prompts as P
from ..models.adapter import ModelAdapter, extract_code, extract_json
from ..reporting.report import write_report
from ..verification.formal import checker_skeleton, parse_check, run_formal
from ..verification.clockcheck import check_clock
from ..verification.lfsrcheck import check_lfsr, lfsr_properties, lfsr_contract, lfsr_contract_matches, VERSION as LFSR_CHECK_VERSION
from ..verification.harness import VerificationResult, compare_references, lint_reference_timing, run_reference, verify
from ..contracts.tables import parse_request_tables, render_table
from ..verification.guards import acceptance_guards, contract_guards
from ..verification.tablecheck import CHECKER_VERSION, check_reference_against_request_tables
from ..verification.normalize import normalize_rtl
from ..verification.testbench import dump_contract_json
from .store import RunStore, lock_owner_id
from .workspace import Workspace

STEPS = ("intake", "review", "reference", "properties", "rtl", "verify", "report", "done")


# Roles for which thinking hit the token cap in this process: shared across runs (an eval suite runs many
# runs in one process) so a model that cannot finish reasoning within the cap pays for it only once.
_PROCESS_NO_THINK_ROLES: set[str] = set()


class BudgetExhausted(Exception):
    pass


class Stalled(Exception):
    pass


@dataclass
class Budget:
    wall_time_s: float
    max_model_calls: int
    max_total_tokens: int
    max_repair_iterations: int
    started: float = field(default_factory=time.time)

    def remaining_s(self) -> float:
        return max(0.0, self.wall_time_s - (time.time() - self.started))

    def check_time(self) -> None:
        if self.remaining_s() <= 0:
            raise BudgetExhausted(f"wall time {self.wall_time_s:.0f}s exceeded")

    def check(self, adapter: ModelAdapter, recorded_calls: Optional[list[dict]] = None) -> None:
        self.check_time()
        # Persisted events include secondary reviewers and survive resume. Model
        # names alone cannot distinguish two adapters configured with the same model.
        calls = adapter.usage.calls if recorded_calls is None else len(recorded_calls)
        tokens = adapter.usage.total_tokens if recorded_calls is None else sum(
            e.get("prompt_tokens", 0) + e.get("completion_tokens", 0) for e in recorded_calls)
        if calls >= self.max_model_calls:
            raise BudgetExhausted(f"model call limit {self.max_model_calls} reached")
        if tokens >= self.max_total_tokens:
            raise BudgetExhausted(f"token limit {self.max_total_tokens} reached")

    def snapshot(self, adapter: ModelAdapter, extra: tuple = ()) -> dict:
        others = [a for a in extra if a is not None]
        return {"elapsed_s": round(time.time() - self.started, 1), "wall_time_s": self.wall_time_s,
                "model_calls": adapter.usage.calls, "max_model_calls": self.max_model_calls,
                "tokens": adapter.usage.total_tokens, "max_total_tokens": self.max_total_tokens,
                "model_latency_s": round(adapter.usage.latency_s, 1),
                "secondary_models": {a.cfg.model: {"calls": a.usage.calls, "tokens": a.usage.total_tokens, "latency_s": round(a.usage.latency_s, 1)} for a in others}}


class Runner:
    def __init__(self, ws: Workspace, cfg: Config, adapter: Optional[ModelAdapter] = None, log=print,
                 alt_adapter: Optional[ModelAdapter] = None, review_adapter: Optional[ModelAdapter] = None):
        self.ws = ws
        self.cfg = cfg
        self.store = RunStore(ws.db_path)
        self.adapter = adapter or ModelAdapter(cfg.model)
        # cross-family corroboration: alternate references come from a second model when configured
        self.alt_adapter = alt_adapter or (ModelAdapter(cfg.model.alt) if cfg.model.alt else None)
        # independent spec review: a separate context, optionally a separate model
        self.review_adapter = review_adapter or (ModelAdapter(cfg.model.review) if cfg.model.review else None)
        self.log = log
        self.run_id: str = ""
        self.budget: Optional[Budget] = None
        self.tool_time_s = 0.0
        self._resumed_elapsed_s = 0.0
        self._no_think_roles = _PROCESS_NO_THINK_ROLES

    # ---------------------------------------------------------------------------------------
    def start(self, request: str, budget_s: Optional[float] = None) -> str:
        cfg_dump = self.cfg.model_dump(mode="json")
        if budget_s:
            cfg_dump["budget"]["wall_time_s"] = budget_s
        self.run_id = self.store.create_run(str(self.ws.root), request, cfg_dump)
        self.store.checkpoint(self.run_id, "intake", {"request": request})
        self.store.set_state(self.run_id, "planned")
        return self.run_id

    def revise(self, change: str, budget_s: Optional[float] = None) -> str:
        """Start a new run whose contract is a revision of the latest accepted contract.

        The revision keeps requirement provenance (parent_version, reason, authority=user), invalidates all
        previous evidence (a new run, new reference/RTL/verification), and never edits earlier versions.
        """
        spec = self.ws.dir("spec")
        contracts = sorted(spec.glob("contract.v*.json"), key=lambda p: int(p.stem.split(".v")[1]))
        if not contracts:
            raise RuntimeError("no contract to revise; run `openchip build` first")
        base = Contract.model_validate_json(contracts[-1].read_text())
        request = self.ws.request_text().strip()
        cfg_dump = self.cfg.model_dump(mode="json")
        if budget_s:
            cfg_dump["budget"]["wall_time_s"] = budget_s
        self.run_id = self.store.create_run(str(self.ws.root), request, cfg_dump)
        (self.ws.root / "request" / f"change.v{base.version + 1}.md").write_text(change.strip() + "\n")
        self.store.checkpoint(self.run_id, "revise", {
            "request": request, "change": change.strip(), "base_contract_path": str(contracts[-1])})
        self.store.set_state(self.run_id, "planned")
        return self.run_id

    def _step_revise(self, ck: dict) -> dict:
        spec = self.ws.dir("spec")
        base = Contract.model_validate_json(Path(ck["base_contract_path"]).read_text())
        request, change = ck["request"], ck["change"]
        table_repair = ck.get("table_repair")
        schema = contract_json_schema()
        errors: list[str] = []
        for attempt in range(3):
            user = P.REVISE_USER.format(request=request, version=base.version, contract_json=base.model_dump_json(indent=1), change=change)
            if errors:
                user += "\n\nYour previous revision was rejected by the validator:\n" + errors[-1] + "\nFix these problems."
            r = self._call("revise", P.REVISE_SYSTEM, user, json_schema=schema, seed=(self.cfg.model.seed or 0) + attempt)
            data = extract_json(r.text) if r.ok else None
            if data is None:
                errors.append("reply was not a JSON object" if r.ok else r.error)
                continue
            data, _ = coerce_contract(data, request)
            data["version"] = base.version + 1
            data["parent_version"] = base.version
            data["revision_authority"] = "agent_inference" if table_repair else "user"
            data.setdefault("revision_reason", change[:200])
            if not data.get("revision_reason"):
                data["revision_reason"] = change[:200]
            try:
                contract = Contract.model_validate(data)
            except ValidationError as e:
                errors.append(str(e)[:2000])
                continue
            if table_repair and any(contract.model_dump()[k] != base.model_dump()[k]
                                    for k in ("module_name", "ports", "parameters", "clock_reset")):
                errors.append("Table recovery must preserve the exact module, ports, parameters and clock/reset; correct only the request's behavior and requirements.")
                continue
            cj = spec / f"contract.v{contract.version}.json"
            cj.write_text(contract.model_dump_json(indent=1))
            (spec / f"contract.v{contract.version}.md").write_text(contract.summary_md())
            self._save("contract", cj, "revise")
            changed = [rq.id for rq in contract.requirements if rq.text not in {q.text for q in base.requirements}]
            self.store.event(self.run_id, "contract_revised", {"from": base.version, "to": contract.version, "changed_or_new": changed})
            self.log(f"[revise] contract v{contract.version} (parent v{base.version}); changed/new requirements: {changed or 'none'}; previous evidence invalidated")
            ck = {"request": request + "\n\nChange request (v" + str(contract.version) + "): " + change.strip(), "contract_path": str(cj), "contract_version": contract.version}
            if table_repair:
                ck.update(request=request, table_repair=table_repair)
            self.store.checkpoint(self.run_id, "reference", ck)
            return ck
        raise RuntimeError("revision failed: " + (errors[-1] if errors else "no valid contract"))

    def resume(self, run_id: str) -> None:
        run = self.store.get_run(run_id)
        if not run:
            raise KeyError(f"unknown run {run_id}")
        self.run_id = run_id
        events = self.store.events(run_id)
        # Rehydrate recorded usage; a restart must not reset the model-call cap.
        adapters = [a for a in (self.adapter, self.alt_adapter, self.review_adapter) if a]
        for adapter in adapters:
            calls = [e for e in events if e["kind"] == "model_call" and
                     e.get("model", self.adapter.cfg.model) == adapter.cfg.model]
            adapter.usage.calls = len(calls)
            adapter.usage.prompt_tokens = sum(e.get("prompt_tokens", 0) for e in calls)
            adapter.usage.completion_tokens = sum(e.get("completion_tokens", 0) for e in calls)
            adapter.usage.latency_s = sum(e.get("latency_s", 0) for e in calls)
        # Count recorded active intervals, excluding time offline between resumes.
        start = None
        last = run["created"]
        for event in events:
            if event["kind"] == "state" and event.get("state") == "running":
                if start is not None:
                    self._resumed_elapsed_s += max(0, last - start)
                start = event["ts"]
            elif event["kind"] == "state" and event.get("state") in {"paused", "failed", "stalled", "budget_exhausted", "completed"}:
                if start is not None:
                    self._resumed_elapsed_s += max(0, event["ts"] - start)
                    start = None
            last = event["ts"]
        if start is not None:
            self._resumed_elapsed_s += max(0, last - start)

    def execute(self) -> dict:
        run = self.store.get_run(self.run_id)
        assert run
        b = run["config"]["budget"]
        self.budget = Budget(b["wall_time_s"], b["max_model_calls"], b["max_total_tokens"], b["max_repair_iterations"])
        self.budget.started -= self._resumed_elapsed_s
        owner = lock_owner_id()
        if not self.store.acquire_lock(self.run_id, owner):
            raise RuntimeError("run is locked by another live process")
        self.store.set_state(self.run_id, "running", resumed_from=run["step"])
        ck = dict(run["checkpoint"])
        step = run["step"]
        outcome: dict = {}
        try:
            steps = {name: getattr(self, "_step_" + name) for name in
                     ("intake", "review", "revise", "reference", "properties", "rtl", "verify")}
            while step != "done":
                if step == "report":
                    ck, outcome = self._step_report(ck, final_state="completed")
                    break
                ck = steps[step](ck)
                step = self.store.get_run(self.run_id)["step"]
            self.store.set_state(self.run_id, "completed", accepted=outcome.get("accepted"))
        except BudgetExhausted as e:
            self.log(f"[budget] {e}")
            ck, outcome = self._step_report(ck, final_state="budget_exhausted", reason=str(e))
            self.store.set_state(self.run_id, "budget_exhausted", reason=str(e))
        except Stalled as e:
            self.log(f"[stalled] {e}")
            ck, outcome = self._step_report(ck, final_state="stalled", reason=str(e))
            self.store.set_state(self.run_id, "stalled", reason=str(e))
        except KeyboardInterrupt:
            self.store.set_state(self.run_id, "paused", reason="interrupted")
            raise
        except Exception as e:  # noqa: BLE001
            self.store.event(self.run_id, "error", {"error": f"{type(e).__name__}: {e}"})
            try:
                ck, outcome = self._step_report(ck, final_state="failed", reason=f"{type(e).__name__}: {e}")
            finally:
                self.store.set_state(self.run_id, "failed", reason=f"{type(e).__name__}: {e}")
            raise
        finally:
            self.store.release_lock(self.run_id)
        return outcome

    # -- helpers ------------------------------------------------------------------------------
    def _call(self, role: str, system: str, user: str, json_schema: Optional[dict] = None, temperature: Optional[float] = None, seed: Optional[int] = None,
              adapter: Optional[ModelAdapter] = None):
        assert self.budget
        self.budget.check(self.adapter, [e for e in self.store.events(self.run_id) if e["kind"] == "model_call"])
        self.store.touch_lock(self.run_id)
        adapter = adapter or self.adapter
        mcfg = adapter.cfg
        tr = mcfg.thinking_roles
        think = (mcfg.thinking if tr is None else (role in tr)) and f"{adapter.cfg.model}:{role}" not in self._no_think_roles
        msgs = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        r = adapter.chat(msgs, role=role, json_schema=json_schema, temperature=temperature, seed=seed, thinking=think,
                         timeout_s=self.budget.remaining_s())
        tag = "" if adapter is self.adapter else f" [{adapter.cfg.model}]"
        self.store.event(self.run_id, "model_call", {"role": role, "ok": r.ok, "finish": r.finish_reason, "prompt_tokens": r.prompt_tokens,
                                                     "completion_tokens": r.completion_tokens, "latency_s": round(r.latency_s, 2), "error": r.error, "thinking": think, "model": adapter.cfg.model})
        self.log(f"[model:{role}]{tag} {r.finish_reason} in {r.latency_s:.1f}s ({r.prompt_tokens}+{r.completion_tokens} tok)" + (f" ERROR {r.error}" if r.error else ""))
        self.budget.check_time()
        if think and r.finish_reason == "length" and role != "property_review":
            # Reasoning consumed the token budget (any answer is truncated): retry without thinking, and stop
            # using thinking for this role for the rest of the run — this model cannot finish within the cap.
            self._no_think_roles.add(f"{adapter.cfg.model}:{role}")
            self.budget.check(self.adapter, [e for e in self.store.events(self.run_id) if e["kind"] == "model_call"])
            self.log(f"[model:{role}]{tag} thinking hit the token cap; retrying without thinking (and for the rest of this run)")
            r = adapter.chat(msgs, role=role, json_schema=json_schema, temperature=temperature, seed=seed, thinking=False,
                             timeout_s=self.budget.remaining_s())
            self.store.event(self.run_id, "model_call", {"role": role, "ok": r.ok, "finish": r.finish_reason, "prompt_tokens": r.prompt_tokens,
                                                         "completion_tokens": r.completion_tokens, "latency_s": round(r.latency_s, 2), "error": r.error, "thinking": False, "fallback": True})
            self.log(f"[model:{role}] {r.finish_reason} in {r.latency_s:.1f}s ({r.prompt_tokens}+{r.completion_tokens} tok) [no-thinking fallback]")
            self.budget.check_time()
        return r

    def _normalize(self, code: str, step: str) -> str:
        """Deterministic declaration fixes (e.g. `output reg`); every change is logged, none alters behavior."""
        fixed, changes = normalize_rtl(code)
        if changes:
            self.store.event(self.run_id, "rtl_normalized", {"step": step, "changes": changes})
            self.log(f"[normalize] {len(changes)} declaration fix(es): " + "; ".join(changes)[:200])
        return fixed

    def _save(self, name: str, path: Path, step: str) -> str:
        return self.store.artifact(self.run_id, name, path, step)

    # -- steps ----------------------------------------------------------------------------------
    def _step_intake(self, ck: dict) -> dict:
        request = ck["request"]
        docs = self._documents_text()
        compiled = lfsr_contract(request) if not docs.strip() else None
        if compiled is not None:
            self._save_lfsr_contract(ck, compiled, "intake")
            self.store.checkpoint(self.run_id, "reference", ck)
            return ck
        tables = self._request_tables_text(request)
        schema = contract_json_schema()
        errors: list[str] = []
        for attempt in range(3):
            user = P.INTAKE_USER.format(request=request, documents=docs) + tables
            if errors:
                user += "\n\nYour previous contract was rejected by the validator:\n" + errors[-1] + "\nFix these problems."
            r = self._call("intake", P.INTAKE_SYSTEM, user, json_schema=schema, seed=(self.cfg.model.seed or 0) + attempt)
            data = extract_json(r.text) if r.ok else None
            if data is None:
                errors.append("reply was not a JSON object" if r.ok else r.error)
                continue
            data, coerce_notes = coerce_contract(data, request, enforce_module_name=True)
            if coerce_notes:
                self.store.event(self.run_id, "contract_coerced", {"attempt": attempt, "notes": coerce_notes})
                ck["coerce_notes"] = coerce_notes
            data.setdefault("version", 1)
            data["version"] = 1
            data["parent_version"] = None
            # Deterministic fill-in: parameters the request names with a default but the model omitted.
            wanted = _request_parameters(request)
            declared = {p.get("name") for p in data.get("parameters", []) or []}
            for name, default in wanted.items():
                if name not in declared and default is not None:
                    data.setdefault("parameters", []).append({"name": name, "default": default, "description": "declared in the request"})
                    self.store.event(self.run_id, "parameter_autofilled", {"name": name, "default": default})
            try:
                contract = Contract.model_validate(data)
            except ValidationError as e:
                errors.append(str(e)[:2000])
                self.store.event(self.run_id, "contract_rejected", {"attempt": attempt, "error": str(e)[:2000]})
                continue
            missing = set(_request_parameters(request)) - {p.name for p in contract.parameters}
            if missing:
                msg = f"the request names parameter(s) {sorted(missing)} but the contract does not declare them; declare each with the requested default and use width_expr for ports that depend on them"
                errors.append(msg)
                self.store.event(self.run_id, "contract_rejected", {"attempt": attempt, "error": msg})
                continue
            spec = self.ws.dir("spec")
            cj = spec / f"contract.v{contract.version}.json"
            cj.write_text(contract.model_dump_json(indent=1))
            (spec / f"contract.v{contract.version}.md").write_text(contract.summary_md())
            h = self._save("contract", cj, "intake")
            self.log(f"[intake] contract v{contract.version} for `{contract.module_name}` with {len(contract.requirements)} requirements (sha {h[:12]})"
                     + (f"; {len(contract.unresolved)} unresolved question(s) recorded" if contract.unresolved else ""))
            ck.update({"contract_path": str(cj), "contract_version": contract.version, "intake_attempts": attempt + 1})
            self.store.checkpoint(self.run_id, "review", ck)
            return ck
        raise RuntimeError("intake failed: could not obtain a valid contract in 3 attempts: " + (errors[-1] if errors else ""))

    def _save_lfsr_contract(self, ck: dict, contract: Contract, stage: str) -> None:
        spec = self.ws.dir("spec")
        path = spec / f"contract.v{contract.version}.json"
        path.write_text(contract.model_dump_json(indent=1))
        path.with_suffix(".md").write_text(contract.summary_md())
        self._save("contract", path, stage)
        ck.update(contract_path=str(path), contract_version=contract.version,
                  contract_origin="request-derived Galois contract")
        self.store.event(self.run_id, "request_contract", {"version": contract.version, "parent_version": contract.parent_version})
        self.log(f"[contract] v{contract.version} derived from the complete explicit LFSR request")

    # -- independent spec review ----------------------------------------------------------------
    def _step_review(self, ck: dict) -> dict:
        """A separate context (optionally a different model) compares request and contract and proposes
        corrections; safe corrections are applied as a recorded contract revision before any code is written."""
        if not self.cfg.review.enabled:
            self._apply_contract_guards(ck, self._load_contract(ck))
            self.store.checkpoint(self.run_id, "reference", ck)
            return ck
        contract = self._load_contract(ck)
        request = ck.get("request", "")
        user = P.REVIEW_USER.format(request=request, contract_json=contract.model_dump_json(indent=1)) + self._request_tables_text(request)
        if ck.get("coerce_notes"):
            user += "\n\nNote: these fields were DEFAULTED mechanically because the intake omitted them — verify each: " + "; ".join(ck["coerce_notes"])
        adapter = self.review_adapter or self.adapter
        r = self._call("review", P.REVIEW_SYSTEM, user, json_schema=REVIEW_SCHEMA, adapter=adapter)
        data = extract_json(r.text) if r.ok else None
        if not data:
            self.store.event(self.run_id, "review_skipped", {"error": r.error or "no JSON"})
            self.log("[review] no usable review; continuing with the intake contract")
            self.store.checkpoint(self.run_id, "reference", ck)
            return ck
        corrections = [c for c in (data.get("corrections") or []) if isinstance(c, dict)][: self.cfg.review.max_corrections]
        unresolved = [u for u in (data.get("unresolved") or []) if isinstance(u, str) and u.strip()]
        applied, rejected = [], []
        if corrections and self.cfg.review.apply_corrections:
            new_data = contract.model_dump(mode="json")
            for c in corrections:
                if c.get("kind") == "behavior" and any(a.get("kind") == "behavior" for a in applied):
                    rejected.append({**c, "result": "Only one complete behavior replacement is allowed per review."})
                    continue
                ok, why = _apply_correction(new_data, c)
                (applied if ok else rejected).append({**c, "result": why})
            for u in unresolved:
                if u not in new_data["unresolved"]:
                    new_data["unresolved"].append(u)
            if applied:
                new_data["version"] = contract.version + 1
                new_data["parent_version"] = contract.version
                new_data["revision_authority"] = "agent_inference"
                new_data["revision_reason"] = "independent spec review: " + "; ".join(f"{a['kind']}:{a['target']}" for a in applied)[:300]
                try:
                    revised = Contract.model_validate(new_data)
                    spec = self.ws.dir("spec")
                    cj = spec / f"contract.v{revised.version}.json"
                    cj.write_text(revised.model_dump_json(indent=1))
                    (spec / f"contract.v{revised.version}.md").write_text(revised.summary_md())
                    self._save("contract", cj, "review")
                    ck["contract_path"] = str(cj)
                    ck["contract_version"] = revised.version
                except ValidationError as e:
                    rejected += [{"kind": "revision", "target": "contract", "result": str(e)[:300]}]
                    applied = []
        elif unresolved:
            contract.unresolved.extend(u for u in unresolved if u not in contract.unresolved)
            Path(ck["contract_path"]).write_text(contract.model_dump_json(indent=1))
        self._apply_contract_guards(ck, self._load_contract(ck))
        ck["review"] = {"verdict": data.get("verdict"), "applied": applied, "rejected": rejected, "unresolved": unresolved,
                        "notes": str(data.get("notes", ""))[:300], "reviewer_model": adapter.cfg.model}
        self.store.event(self.run_id, "review", {"verdict": data.get("verdict"), "applied": len(applied), "rejected": len(rejected), "unresolved": len(unresolved)})
        self.log(f"[review] {data.get('verdict')}: {len(applied)} correction(s) applied, {len(rejected)} rejected, {len(unresolved)} unresolved" + (f" -> contract v{ck['contract_version']}" if applied else ""))
        self.store.checkpoint(self.run_id, "reference", ck)
        return ck

    def _documents_text(self) -> str:
        docs = []
        rd = self.ws.root / "request"
        for p in sorted(rd.glob("*")):
            if p.name == "request.md" or not p.is_file() or p.suffix.lower() not in (".md", ".txt"):
                continue
            docs.append(f"--- Supporting document: {p.name} ---\n{p.read_text()[:12000]}\n")
        return ("\nSupporting documents:\n" + "\n".join(docs)) if docs else ""

    def _request_tables_text(self, request: str) -> str:
        """Any table printed in the request, expanded mechanically, for the intake and review prompts.

        Reading a printed grid is where intake most often goes wrong: models apply the textbook
        MSB-first convention instead of the axis labels actually printed. The expansion below is
        produced by a parser, so the model is never asked to read the grid at all.
        """
        try:
            tables = parse_request_tables(request)
            from ..contracts.cellular import render_cellular
            cellular = render_cellular(request)
        except Exception as e:  # noqa: BLE001 — a parser fault must never block a build
            self.store.event(self.run_id, "request_table_parse_error", {"error": f"{type(e).__name__}: {e}"})
            return ""
        if not tables and not cellular:
            return ""
        rendered = "\n\n".join([render_table(t) for t in tables] + ([cellular] if cellular else []))
        try:
            (self.ws.dir("spec") / "request_tables.md").write_text(rendered + "\n")
        except Exception:  # noqa: BLE001
            pass
        return ("\n\nThe request contains a table, expanded below by a parser that read the printed axis "
                "labels literally and in the printed order. Respect each table's scope: a child-module table is not the composed top-level output. Within that scope it is authoritative: state the behavior so that "
                "it reproduces exactly these rows, and do not re-derive them from the grid yourself.\n\n" + rendered)

    def _load_contract(self, ck: dict) -> Contract:
        return Contract.model_validate_json(Path(ck["contract_path"]).read_text())

    def _ctx(self, ck: dict, contract: Contract) -> dict:
        return P.contract_context(contract, ck.get("request", ""))

    def _generate_reference(self, ck: dict, contract: Contract, out_path: Path, feedback: str = "", seed_offset: int = 0, attempts: int = 3) -> tuple[Optional[Path], str]:
        """Ask the reference role for an executable model and smoke-run it. Returns (path or None, last error)."""
        ctx = self._ctx(ck, contract)
        work = self.ws.dir("verification") / "reference_check"
        work.mkdir(parents=True, exist_ok=True)
        cj = work / "contract.json"
        dump_contract_json(contract, cj)
        last_err = ""
        prev_flagged: frozenset = frozenset()
        for attempt in range(attempts):
            user = P.REFERENCE_USER.format(**ctx)
            if feedback:
                user += "\n\nAdditional note from review:\n" + feedback
            if last_err:
                user += ("\n\nYour previous reference model failed when executed:\n" + last_err + "\nFix it. Reminder: `inputs` is a dict of non-negative ints keyed by the exact port name "
                         "(e.g. inputs['in']); bit k of a port is (inputs['name'] >> k) & 1; every output must be returned as a non-negative int (never a list or bool).")
            system = P.REFERENCE_SYSTEM if seed_offset == 0 else P.REFERENCE_ALT_SYSTEM  # alternates use a different structure to decorrelate errors
            alt = self.alt_adapter if (seed_offset != 0 and self.alt_adapter is not None) else None  # cross-family second voice
            r = self._call("reference", system, user, seed=(self.cfg.model.seed or 0) + seed_offset + attempt,
                           temperature=(self.cfg.model.temperature if seed_offset == 0 else max(self.cfg.model.temperature, 0.7)), adapter=alt)
            code = extract_code(r.text, ("python", "py")) if r.ok else None
            if not code or "class Reference" not in code:
                last_err = "no ```python block defining class Reference was found" if r.ok else r.error
                self.store.event(self.run_id, "reference_rejected", {"attempt": attempt, "error": last_err})
                continue
            # Review each derivation in its own context, without RTL, another
            # reference, or simulator verdicts. The tools still decide validity.
            draft = out_path.with_suffix(".draft-" + uuid.uuid4().hex[:12] + ".py")
            draft.write_text(code)
            review_user = ("User request:\n" + ck.get("request", "") +
                           "\nContract:\n" + contract.model_dump_json(indent=1) +
                           "\nSupporting user documents:\n" + self._documents_text() +
                           "\nPython reference to review:\n```python\n" + code + "\n```")
            reviewed = self._call("reference_review", P.REFERENCE_REVIEW_SYSTEM, review_user,
                                  seed=(self.cfg.model.seed or 0) + seed_offset + attempt + 67, adapter=alt)
            reviewed_code = extract_code(reviewed.text, ("python", "py")) if reviewed.ok else None
            self.store.event(self.run_id, "reference_review", {
                "draft": str(draft), "draft_sha256": hashlib.sha256(code.encode()).hexdigest(),
                "reviewed_sha256": hashlib.sha256(reviewed_code.encode()).hexdigest() if reviewed_code else "",
                "changed": bool(reviewed_code and reviewed_code != code),
                "ok": bool(reviewed_code and "class Reference" in reviewed_code)})
            if not reviewed_code or "class Reference" not in reviewed_code:
                last_err = "reference review did not return complete Python defining class Reference" if reviewed.ok else reviewed.error
                self.store.event(self.run_id, "reference_rejected", {"attempt": attempt, "error": last_err,
                                 "retained": str(draft)})
                continue
            code = reviewed_code
            out_path.write_text(code)
            from ..verification.cellularcheck import check_cellular
            assert self.budget
            t0 = time.time()
            cellular = check_cellular(contract, ck.get("request", ""), out_path, work / "cellular",
                                      min(60, self.budget.remaining_s()), sys.executable)
            self.tool_time_s += time.time() - t0
            if cellular is not None:
                self.store.event(self.run_id, "reference_request_check", {"path": str(out_path), **cellular})
                if cellular["status"] != "ok":
                    last_err = cellular["detail"] + "\n" + self._request_tables_text(ck.get("request", ""))
                    saved = out_path.with_suffix(".request-rejected-" + uuid.uuid4().hex[:12] + ".py")
                    shutil.copyfile(out_path, saved)
                    self.store.event(self.run_id, "reference_rejected", {"attempt": attempt,
                                     "request_check": cellular, "retained": str(saved)})
                    self.log(f"[reference] failed explicit cell-transition check: {cellular['status']}")
                    if cellular["status"] == "error":
                        return None, last_err
                    continue
            vec = run_reference(out_path, cj, seed=1, cycles=50, out=work / "smoke.json")
            if vec.get("error"):
                last_err = vec["error"]
                out_path.with_suffix(f".rejected{attempt}.py").write_text(code)
                self.store.event(self.run_id, "reference_rejected", {"attempt": attempt, "error": last_err[:2000]})
                self.log(f"[reference] attempt {attempt + 1} failed to execute: {last_err.splitlines()[0][:120]}")
                continue
            lint = lint_reference_timing(out_path, cj, work / "timing_lint.json")
            if seed_offset != 0:
                assert self.budget
                semantic = check_lfsr(contract, ck.get("request", ""), out_path, work / "alternate_lfsr",
                                      min(60, self.budget.wall_time_s - (time.time() - self.budget.started) - 2))
                if semantic["status"] in {"mismatch", "error"}:
                    last_err = semantic["detail"]
                    saved = out_path.with_suffix(".request-rejected-" + uuid.uuid4().hex[:12] + ".py")
                    shutil.copyfile(out_path, saved)
                    self.store.event(self.run_id, "reference_rejected", {"attempt": attempt,
                                     "request_check": semantic, "retained": str(saved)})
                    self.log(f"[reference] alternate failed request-derived check: {semantic['status']}")
                    if semantic["status"] == "error":
                        return None, last_err
                    continue
            if lint.get("violations"):
                v = lint["violations"]
                names = ", ".join(x["output"] for x in v)
                flagged = frozenset(x["output"] for x in v)
                if flagged and flagged == prev_flagged:
                    # Two independent derivations compute the same outputs combinationally: the contract's
                    # timing label, not the reference, is the likely error. Correct it as a recorded revision.
                    contract = self._correct_timing_labels(ck, contract, sorted(flagged))
                    dump_contract_json(contract, cj)
                    self.log(f"[reference] two derivations agree that {names} are combinational; contract timing labels corrected (v{contract.version})")
                    lint2 = lint_reference_timing(out_path, cj, work / "timing_lint2.json")
                    if not lint2.get("violations"):
                        return out_path, ""
                    v = lint2["violations"]
                    names = ", ".join(x["output"] for x in v)
                prev_flagged = flagged
                last_err = ("TIMING ERROR: the contract declares these outputs as REGISTERED, but your step() returns values for them that depend on the "
                            f"inputs of the SAME call: {names}. Example: at step {v[0]['step']}, changing inputs {v[0]['inputs_differ']} changed "
                            f"{v[0]['output']} from {v[0]['value_a']} to {v[0]['value_b']}. A registered output must be returned from a state variable "
                            "that was computed in the PREVIOUS step's update phase (see the worked example).")
                out_path.with_suffix(f".rejected{attempt}.py").write_text(code)
                self.store.event(self.run_id, "reference_rejected", {"attempt": attempt, "error": last_err[:2000], "timing_violations": v})
                self.log(f"[reference] attempt {attempt + 1} rejected by timing lint: registered output(s) {names} depend on same-cycle inputs")
                continue
            return out_path, ""
        return None, last_err

    def _plan_resetless_conditioning(self, ck: dict, contract: Contract) -> Contract:
        cr = contract.clock_reset
        if cr is None or cr.reset is not None or cr.conditioning:
            return contract
        inputs = {p.name: {"type": "integer", "minimum": 0, "maximum": (1 << p.width) - 1}
                  for p in contract.data_inputs()}
        schema = {"type": "object", "properties": {
            "conditioning": {"type": "array", "minItems": 0, "maxItems": 256,
                             "items": {"type": "object", "properties": inputs,
                                       "required": list(inputs), "additionalProperties": False}},
            "reason": {"type": "string"}}, "required": ["conditioning", "reason"]}
        response = self._call("conditioning", P.CONDITIONING_SYSTEM,
                              "Original request:\n" + ck.get("request", "") +
                              "\nContract:\n" + contract.model_dump_json(indent=1), json_schema=schema)
        plan = extract_json(response.text) if response.ok else None
        if not isinstance(plan, dict) or not plan.get("conditioning"):
            raise Stalled("No executable resetless startup sequence was provided; power-up state cannot be assumed.")
        data = contract.model_dump(mode="json")
        data["clock_reset"]["conditioning"] = plan["conditioning"]
        versions = [int(p.stem.split(".v")[-1]) for p in self.ws.dir("spec").glob("contract.v*.json")]
        data.update(version=max(versions + [contract.version]) + 1, parent_version=contract.version,
                    revision_reason="Executable resetless simulation conditioning; hardware interface and behavior unchanged.",
                    revision_authority="agent_inference")
        try:
            revised = Contract.model_validate(data)
        except ValidationError as exc:
            self.store.event(self.run_id, "conditioning_rejected", {"error": str(exc)[:1200]})
            raise Stalled("Resetless startup vectors failed contract validation; no hardware initialization was substituted.") from exc
        path = self.ws.dir("spec") / f"contract.v{revised.version}.json"
        path.write_text(revised.model_dump_json(indent=1))
        path.with_suffix(".md").write_text(revised.summary_md())
        self._save("contract", path, "conditioning")
        ck.update(contract_path=str(path), contract_version=revised.version)
        for key in ("final_evidence", "last_evidence", "properties_done", "consensus_done", "consensus"):
            ck.pop(key, None)
        self.store.event(self.run_id, "conditioning", {"version": revised.version,
                         "edges": len(revised.clock_reset.conditioning), "reason": str(plan.get("reason", ""))[:600]})
        self.log(f"[conditioning] {len(revised.clock_reset.conditioning)} physical input edges recorded in contract v{revised.version}; power-up state remains unverified")
        self.store.checkpoint(self.run_id, "reference", ck)
        return revised

    def _step_reference(self, ck: dict) -> dict:
        contract = self._plan_resetless_conditioning(ck, self._load_contract(ck))
        refdir = self.ws.dir("reference")
        rp, err = self._generate_reference(ck, contract, refdir / "reference.py", feedback=ck.get("reference_feedback", ""))
        if rp is None:
            raise RuntimeError("reference generation failed after 3 attempts: " + err[:500])
        h = self._save("reference", rp, "reference")
        self.log(f"[reference] executable reference model accepted (sha {h[:12]})")
        ck.update({"reference_path": str(rp)})
        self.store.checkpoint(self.run_id, "properties" if not ck.get("properties_done") else "rtl", ck)
        return ck

    def _reference_consensus(self, ck: dict, contract: Contract, rp: Path, ref: Path, res: VerificationResult) -> tuple[dict, Path, bool]:
        """On the first RTL-vs-reference disagreement, derive a second independent reference and arbitrate.

        Returns (ck, adopted_reference_path, rtl_corroborated). Three outcomes:
          - ref2 agrees with ref1 on identical stimulus  -> reference corroborated, repair the RTL;
          - ref2 disagrees and the RTL passes ref2       -> RTL corroborated by an independent derivation, adopt ref2;
          - ref2 disagrees and the RTL fails ref2 too    -> derive ref3 and adopt the majority (or keep ref1).
        Everything is recorded so the report can show which reference was disputed and why.
        """
        refdir = self.ws.dir("reference")
        vcfg = self.cfg.verification
        cwork = self.ws.dir("verification") / "consensus"
        ck["consensus_done"] = True
        ck["consensus"] = {"references": [{"path": str(ref), "role": "initial"}], "outcome": ""}
        self.log("[consensus] RTL disagrees with the reference; deriving a second independent reference to arbitrate")
        ref2, err = self._generate_reference(ck, contract, refdir / "reference.alt1.py", seed_offset=17, attempts=2)
        if ref2 is None:
            ck["consensus"]["outcome"] = "alt1_failed: " + err[:200]
            ck["consensus"]["confidence"] = "low"
            return ck, ref, False
        cmp12 = compare_references(contract, ref, ref2, cwork / "r1_vs_r2", vcfg.seeds, vcfg.sim_cycles)
        ck["consensus"]["references"].append({"path": str(ref2), "role": "alt1", "vs_initial": {k: v for k, v in cmp12.items() if k != "first"}})
        self.store.event(self.run_id, "consensus", {"stage": "r1_vs_r2", **{k: v for k, v in cmp12.items() if k != "first"}})
        if cmp12.get("error"):
            ck["consensus"]["outcome"] = "compare_error"
            ck["consensus"]["confidence"] = "low"
            return ck, ref, False
        if cmp12["mismatches"] == 0:
            ck["consensus"]["outcome"] = "reference_corroborated"
            ck["consensus"]["confidence"] = "high"
            self.log(f"[consensus] second reference agrees with the first on {cmp12['cycles']} cycles; the RTL is the likely culprit")
            return ck, ref, False
        self.log(f"[consensus] the two references disagree on {cmp12['mismatches']}/{cmp12['cycles']} cycles; checking RTL against the second")
        res2 = verify(contract, rp, ref2, cwork / "rtl_vs_r2", self._reference_comparison_config(), run_synth=False)
        if res2.accepted:
            ck["consensus"]["outcome"] = "rtl_corroborated_by_alt1"
            ck["consensus"]["confidence"] = "low"
            self._adopt_reference(ck, ref, ref2)
            self.log("[consensus] RTL matches the second reference; adopting it and marking the first as disputed")
            return ck, Path(ck["reference_path"]), True
        ref3, err = self._generate_reference(ck, contract, refdir / "reference.alt2.py", seed_offset=41, attempts=2)
        if ref3 is None:
            ck["consensus"]["outcome"] = "alt2_failed"
            ck["consensus"]["confidence"] = "low"
            return ck, ref, False
        cmp13 = compare_references(contract, ref, ref3, cwork / "r1_vs_r3", vcfg.seeds, vcfg.sim_cycles)
        cmp23 = compare_references(contract, ref2, ref3, cwork / "r2_vs_r3", vcfg.seeds, vcfg.sim_cycles)
        ck["consensus"]["references"].append({"path": str(ref3), "role": "alt2", "vs_initial": {k: v for k, v in cmp13.items() if k != "first"}, "vs_alt1": {k: v for k, v in cmp23.items() if k != "first"}})
        self.store.event(self.run_id, "consensus", {"stage": "r3", "r1_vs_r3": cmp13.get("mismatches", cmp13.get("error")), "r2_vs_r3": cmp23.get("mismatches", cmp23.get("error"))})
        m13 = cmp13.get("mismatches", 10**9)
        m23 = cmp23.get("mismatches", 10**9)
        if m23 == 0 and m13 > 0:
            ck["consensus"]["outcome"] = "majority_alt1"
            ck["consensus"]["confidence"] = "low"
            self._adopt_reference(ck, ref, ref2)
            self.log("[consensus] references 2 and 3 agree; adopting reference 2 (majority) and re-verifying")
            return ck, Path(ck["reference_path"]), False
        if m13 == 0 and m23 > 0:
            ck["consensus"]["outcome"] = "majority_initial"
            ck["consensus"]["confidence"] = "low"
            self.log("[consensus] references 1 and 3 agree; keeping the initial reference")
            return ck, ref, False
        ck["consensus"]["outcome"] = "no_majority"
        ck["consensus"]["confidence"] = "low"
        self.log("[consensus] no two references agree; keeping the initial reference and flagging the contract as ambiguous")
        return ck, ref, False

    def _reference_comparison_config(self) -> Config:
        # These calls compare a reference against RTL. Required formal is checked
        # once by the main verifier with the actual property checker attached.
        cfg = self.cfg.model_copy(deep=True)
        cfg.verification.require_formal = False
        cfg.verification.run_formal = False
        return cfg

    def _corroborate_acceptance(self, ck: dict, contract: Contract, rp: Path, ref: Path) -> tuple[dict, Path, bool]:
        """RTL passed the first reference. Check it against a second independent reference before accepting.
        Returns (ck, reference, accept_now). When the second disagrees, a third breaks the tie."""
        refdir = self.ws.dir("reference")
        cwork = self.ws.dir("verification") / "consensus"
        ck["consensus_done"] = True
        ck["consensus"] = {"references": [{"path": str(ref), "role": "initial"}], "outcome": "", "mode": "corroboration"}
        ref2, err = self._generate_reference(ck, contract, refdir / "reference.alt1.py", seed_offset=17, attempts=2)
        if ref2 is None:
            ck["consensus"]["outcome"] = "alt1_failed"
            ck["consensus"]["confidence"] = "low"
            self.log("[corroborate] could not derive a second reference; single-reference evidence is low confidence and sign-off will be withheld")
            return ck, ref, True
        ck["consensus"]["references"].append({"path": str(ref2), "role": "alt1"})
        res2 = verify(contract, rp, ref2, cwork / "rtl_vs_alt1", self._reference_comparison_config(), run_synth=False)
        self.store.event(self.run_id, "consensus", {"stage": "rtl_vs_alt1", "accepted": res2.accepted, "summary": res2.summary})
        if res2.accepted:
            ck["consensus"]["outcome"] = "rtl_corroborated_by_two_references"
            ck["consensus"]["confidence"] = "high"
            self.log("[corroborate] RTL also matches a second independently derived reference")
            return ck, ref, True
        self.log("[corroborate] second reference disagrees with the RTL; deriving a third to break the tie")
        ref3, err = self._generate_reference(ck, contract, refdir / "reference.alt2.py", seed_offset=41, attempts=2)
        if ref3 is None:
            ck["consensus"]["outcome"] = "split_1_1_alt2_failed"
            ck["consensus"]["confidence"] = "low"
            return ck, ref, True
        ck["consensus"]["references"].append({"path": str(ref3), "role": "alt2"})
        res3 = verify(contract, rp, ref3, cwork / "rtl_vs_alt2", self._reference_comparison_config(), run_synth=False)
        self.store.event(self.run_id, "consensus", {"stage": "rtl_vs_alt2", "accepted": res3.accepted, "summary": res3.summary})
        if res3.accepted:
            ck["consensus"]["outcome"] = "rtl_corroborated_2_of_3"
            ck["consensus"]["confidence"] = "medium"
            self.log("[corroborate] RTL matches references 1 and 3 (2 of 3); disagreement remains and sign-off will be withheld")
            return ck, ref, True
        cmp23 = compare_references(contract, ref2, ref3, cwork / "r2_vs_r3", self.cfg.verification.seeds, self.cfg.verification.sim_cycles)
        if not cmp23.get("error") and cmp23["mismatches"] == 0:
            ck["consensus"]["outcome"] = "majority_against_rtl"
            self._adopt_reference(ck, ref, ref2)
            self.log("[corroborate] references 2 and 3 agree with each other and disagree with the RTL; adopting reference 2 and repairing the RTL")
            return ck, Path(ck["reference_path"]), False
        ck["consensus"]["outcome"] = "no_majority"
        ck["consensus"]["confidence"] = "low"
        self.log("[corroborate] three references disagree; first-reference evidence is low confidence and sign-off will be withheld — contract likely ambiguous")
        return ck, ref, True

    def _correct_timing_labels(self, ck: dict, contract: Contract, outputs: list[str]) -> Contract:
        """Record an agent_inference contract revision that relabels the given outputs as combinational."""
        data = contract.model_dump(mode="json")
        for port in data["ports"]:
            if port["name"] in outputs:
                port["timing"] = "combinational"
        data["version"] = contract.version + 1
        data["parent_version"] = contract.version
        data["revision_authority"] = "agent_inference"
        data["revision_reason"] = f"timing labels corrected to combinational for {', '.join(outputs)}: two independently derived reference models compute them from same-cycle inputs"
        new = Contract.model_validate(data)
        spec = self.ws.dir("spec")
        cj = spec / f"contract.v{new.version}.json"
        cj.write_text(new.model_dump_json(indent=1))
        (spec / f"contract.v{new.version}.md").write_text(new.summary_md())
        self._save("contract", cj, "timing_correction")
        self.store.event(self.run_id, "contract_revised", {"from": contract.version, "to": new.version, "reason": new.revision_reason, "authority": "agent_inference"})
        ck["contract_path"] = str(cj)
        ck["contract_version"] = new.version
        return new

    def _adopt_reference(self, ck: dict, old: Path, new: Path) -> None:
        refdir = self.ws.dir("reference")
        disputed = refdir / "reference.disputed.py"
        disputed.write_text(old.read_text())
        canonical = refdir / "reference.py"
        canonical.write_text(new.read_text())
        self._save("reference", canonical, "consensus")
        ck["reference_path"] = str(canonical)
        ck["reference_disputed"] = str(disputed)

    def _apply_contract_guards(self, ck: dict, contract: Contract) -> Contract:
        finds = contract_guards(contract)
        if finds:
            for f in finds:
                if f.message not in contract.unresolved:
                    contract.unresolved.append(f.message)
            Path(ck["contract_path"]).write_text(contract.model_dump_json(indent=1))
            self.store.event(self.run_id, "contract_guard", {"findings": [f.code for f in finds]})
            self.log("[guard] contract: " + "; ".join(f.code for f in finds) + " -> provisional")
        return contract

    def _request_properties(self, ck: dict, contract: Contract) -> Optional[Path]:
        """Use a full transition checker when the request specifies its semantics."""
        if not self.cfg.verification.run_formal:
            return None
        code = lfsr_properties(contract, ck.get("request", ""))
        if code is None:
            return None
        vdir = self.ws.dir("verification")
        pp = vdir / f"{contract.module_name}_props.v"
        same = pp.is_file() and pp.read_text() == code
        if same and ck.get("properties_origin") == "request-derived Galois transitions":
            return pp
        retained = None
        if pp.is_file() and not same:
            retained = pp.with_name(pp.stem + ".retained-" + uuid.uuid4().hex[:12] + ".v")
            shutil.copyfile(pp, retained)
        pp.write_text(code)
        chk = parse_check(pp, contract, vdir, self.cfg.tools.yosys, self.cfg.tools.timeout_s)
        if not chk.ok:
            raise Stalled("Request-derived formal checker failed to parse: " + chk.tail(8))
        self._save("properties", pp, "properties")
        ck.update(properties_path=str(pp), properties_origin="request-derived Galois transitions")
        self.store.event(self.run_id, "request_properties", {"path": str(pp), "retained": str(retained) if retained else None})
        return pp

    def _step_properties(self, ck: dict) -> dict:
        """Optional formal layer: a property checker written independently of the RTL. Failure is recorded, not fatal."""
        contract = self._load_contract(ck)
        ck["properties_done"] = True
        if not self.cfg.verification.run_formal or contract.combinational:
            self.store.checkpoint(self.run_id, "rtl", ck)
            return ck
        if self._request_properties(ck, contract) is not None:
            self.store.checkpoint(self.run_id, "rtl", ck)
            return ck
        ctx = self._ctx(ck, contract)
        vdir = self.ws.dir("verification")
        last_err = ""
        for attempt in range(2):
            user = P.PROPERTIES_USER.format(request=ctx["request"], contract_json=ctx["contract_json"], skeleton=checker_skeleton(contract))
            if last_err:
                user += "\n\nYour previous checker was rejected:\n" + last_err[:1500] + "\nFix it."
            system = P.PROPERTIES_SYSTEM.replace("posedge", contract.clock_reset.clock_edge)
            r = self._call("properties", system, user, seed=(self.cfg.model.seed or 0) + attempt)
            code = extract_code(r.text, ("verilog", "systemverilog", "v", "sv")) if r.ok else None
            if not code:
                last_err = "no verilog block" if r.ok else r.error
                continue
            pp = vdir / f"{contract.module_name}_props.v"
            pp.write_text(code)
            chk = parse_check(pp, contract, vdir, self.cfg.tools.yosys, self.cfg.tools.timeout_s)
            if not chk.ok:
                last_err = (chk.error + "\n" if chk.error else "") + chk.tail(15)
                pp.rename(vdir / f"{contract.module_name}_props.rejected{attempt}.v")
                self.store.event(self.run_id, "properties_rejected", {"attempt": attempt, "error": last_err[:1500]})
                self.log(f"[properties] attempt {attempt + 1} rejected by the formal front end")
                continue
            h = self._save("properties", pp, "properties")
            n = code.count("assert(") + code.count("assert (")
            self.log(f"[properties] checker accepted with {n} assertion(s) (sha {h[:12]})")
            ck["properties_path"] = str(pp)
            break
        else:
            self.store.event(self.run_id, "properties_skipped", {"error": last_err[:500]})
            self.log("[properties] no usable checker; formal layer skipped for this run")
        self.store.checkpoint(self.run_id, "rtl", ck)
        return ck

    def _review_counterexample_properties(self, ck: dict, contract: Contract, rtl: Path,
                                         props: Path, work: Path, original):
        """One independent checker review; only a successful recheck can replace a counterexample."""
        if (not self.cfg.verification.review_counterexamples
                or original.extra.get("status") != "counterexample"
                or ck.get("properties_origin", "model-generated") != "model-generated"
                or ck.get("property_review")
                or any(e["kind"] == "property_review_started" for e in self.store.events(self.run_id))):
            return original
        assert self.budget
        if self.budget.remaining_s() <= 5:
            return original
        review_dir = work / "property_review"
        review_dir.mkdir(parents=True, exist_ok=True)
        before = review_dir / "original.v"
        before.write_bytes(props.read_bytes())
        evidence = review_dir / "original_formal.json"
        evidence.write_text(json.dumps(original.to_dict(), indent=1))
        reviewer = self.review_adapter or self.adapter
        state = {"status": "started", "reviewer_model": reviewer.cfg.model, "original_checker": str(before),
                 "original_sha256": hashlib.sha256(before.read_bytes()).hexdigest(),
                 "original_formal": str(evidence), "rtl_sha256": hashlib.sha256(rtl.read_bytes()).hexdigest()}
        ck["property_review"] = state
        self.store.event(self.run_id, "property_review_started", state)
        self.store.checkpoint(self.run_id, "verify", ck)

        def finish(status, **details):
            state.update(status=status, **details)
            self.store.event(self.run_id, "property_review", dict(state))
            self.store.checkpoint(self.run_id, "verify", ck)

        user = ("Request:\n" + ck.get("request", "") + "\nContract:\n" + contract.model_dump_json(indent=1)
                + "\nSupporting user documents:\n" + self._documents_text()
                + "\nChecker:\n```verilog\n" + before.read_text() + "\n```")
        # The context deliberately contains no RTL, other reference or solver verdict.
        response = self._call("property_review", P.PROPERTIES_REVIEW_SYSTEM, user,
                              seed=(reviewer.cfg.seed or 0) + 89, adapter=reviewer)
        (review_dir / "response.txt").write_text(response.text)
        code = extract_code(response.text, ("verilog", "systemverilog", "v", "sv")) if response.ok else None
        if not code:
            finish("unusable_response")
            return original
        candidate = review_dir / "reviewed.v"
        candidate.write_text(code)
        state.update(reviewed_checker=str(candidate), reviewed_sha256=hashlib.sha256(candidate.read_bytes()).hexdigest())
        plain = re.sub(r"/\*.*?\*/|//[^\n]*", " ", code, flags=re.S)
        if re.search(r"\bassume\b|`", plain):
            finish("rejected_constraints", detail="Reviewed checkers may not introduce assumptions or preprocessor directives.")
            return original
        if code.strip() == before.read_text().strip():
            finish("unchanged")
            return original
        check = parse_check(candidate, contract, review_dir, self.cfg.tools.yosys,
                            min(self.cfg.tools.timeout_s, self.budget.remaining_s()))
        (review_dir / "parse.json").write_text(json.dumps(check.to_dict(), indent=1))
        if not check.ok:
            finish("parse_failed")
            return original
        remaining = self.budget.remaining_s() - 2
        if remaining <= 0:
            finish("no_recheck_budget")
            return original
        t0 = time.time()
        checked = run_formal(contract, rtl, candidate, review_dir / "formal", self.cfg.tools.sby,
                             self.cfg.verification.formal_depth,
                             min(self.cfg.verification.formal_timeout_s, remaining), yosys=self.cfg.tools.yosys)
        self.tool_time_s += time.time() - t0
        result_path = review_dir / "reviewed_formal.json"
        result_path.write_text(json.dumps(checked.to_dict(), indent=1))
        if not checked.ok or checked.extra.get("status") != "bounded_pass":
            finish("recheck_failed", reviewed_status=checked.extra.get("status"), reviewed_formal=str(result_path))
            return original
        # Keep both checkers and both tool records. Promote only after an actual
        # bounded pass; errors/timeouts must never erase the original counterexample.
        staging = props.with_suffix(".promote-" + uuid.uuid4().hex[:12] + ".v")
        staging.write_bytes(candidate.read_bytes())
        os.replace(staging, props)
        self._save("properties", props, "counterexample_review")
        finish("bounded_pass", reviewed_sha256=hashlib.sha256(candidate.read_bytes()).hexdigest(),
               reviewed_formal=str(result_path))
        self.log("[formal] independently reviewed checker passed the bounded recheck; original counterexample retained")
        return checked

    def _step_rtl(self, ck: dict) -> dict:
        contract = self._load_contract(ck)
        ctx = self._ctx(ck, contract)
        rtldir = self.ws.dir("rtl")
        for attempt in range(3):
            r = self._call("rtl", P.RTL_SYSTEM, P.RTL_USER.format(**ctx), seed=(self.cfg.model.seed or 0) + attempt)
            code = extract_code(r.text, ("verilog", "systemverilog", "v", "sv")) if r.ok else None
            if not code or f"module {contract.module_name}" not in code:
                self.store.event(self.run_id, "rtl_rejected", {"attempt": attempt, "reason": "no verilog block with the contract module"})
                continue
            rp = rtldir / f"{contract.module_name}.v"
            code = self._normalize(code, "rtl")
            rp.write_text(code)
            h = self._save("rtl_candidate", rp, "rtl")
            self.log(f"[rtl] candidate 1 written ({len(code.splitlines())} lines, sha {h[:12]})")
            ck.update({"rtl_path": str(rp), "rtl_attempt": 0, "history": []})
            self.store.checkpoint(self.run_id, "verify", ck)
            return ck
        raise RuntimeError("RTL generation failed: no usable Verilog in 3 attempts")

    def _step_verify(self, ck: dict) -> dict:
        contract = self._load_contract(ck)
        if not self._documents_text().strip() and lfsr_contract_matches(contract, ck.get("request", "")) is False:
            canonical = lfsr_contract(ck["request"])
            assert canonical is not None
            canonical.version = max(int(p.stem.split(".v")[1]) for p in self.ws.dir("spec").glob("contract.v*.json")) + 1
            canonical.parent_version = contract.version
            canonical.revision_reason = "Reconcile generated descriptions with the complete request-derived LFSR specification."
            self._save_lfsr_contract(ck, canonical, "request_reconciliation")
            contract = canonical
            for key in ("last_evidence", "final_evidence", "consensus", "consensus_done", "lfsr_check"):
                ck.pop(key, None)
            self.store.checkpoint(self.run_id, "verify", ck)
        rp = Path(ck["rtl_path"])
        ref = Path(ck["reference_path"])
        vdir = self.ws.dir("verification")
        history: list[dict] = ck.get("history", [])
        attempt = int(ck.get("rtl_attempt", 0))
        assert self.budget
        max_iter = max(0, self.budget.max_repair_iterations - (ck.get("table_repair") or {}).get("repairs_used", 0))
        signatures: list[str] = [h.get("signature", "") for h in history]
        ref_regenerated = bool(ck.get("reference_regenerated", False))
        while True:
            # Check explicit request semantics before repairing RTL against a
            # correlated, erroneous reference. Recheck only when inputs change.
            fingerprint = hashlib.sha256((LFSR_CHECK_VERSION + contract.digest() + ck.get("request", "")).encode()
                                         + ref.read_bytes()).hexdigest()
            lfsr = ck.get("lfsr_check") or {}
            if lfsr.get("input_digest") != fingerprint or lfsr.get("status") == "error":
                t0 = time.time()
                lfsr = check_lfsr(contract, ck.get("request", ""), ref, vdir / "lfsr_check",
                                  min(60, self.budget.wall_time_s - (time.time() - self.budget.started) - 2))
                self.tool_time_s += time.time() - t0
                lfsr["input_digest"] = fingerprint
                ck["lfsr_check"] = lfsr
                if lfsr["status"] != "not_applicable":
                    self.store.event(self.run_id, "lfsr_check", lfsr)
                    self.log(f"[lfsr] {lfsr['status']}: {lfsr['detail']}")
                self.store.checkpoint(self.run_id, "verify", ck)
            if lfsr["status"] == "mismatch" and not ck.get("table_repair") and attempt < max_iter:
                return self._queue_table_repair(ck, attempt + 1, check_key="lfsr_check")
            if lfsr["status"] in {"mismatch", "error"}:
                raise Stalled("Independent LFSR request check did not pass: " + lfsr["detail"])
            work = vdir / "attempts" / f"attempt_{attempt}"
            if work.exists():
                archived = work.with_name(work.name + "-previous-" + uuid.uuid4().hex[:10])
                work.rename(archived)
                for item in history:
                    if item.get("evidence") == str(work / "evidence.json"):
                        item["evidence"] = str(archived / "evidence.json")
                for key in ("last_evidence", "final_evidence"):
                    if ck.get(key) == str(work / "evidence.json"):
                        ck[key] = str(archived / "evidence.json")
                review = ck.get("property_review") or {}
                for key in ("original_checker", "original_formal", "reviewed_checker", "reviewed_formal"):
                    if review.get(key):
                        try:
                            relative = Path(review[key]).relative_to(work)
                        except ValueError:
                            continue
                        review[key] = str(archived / relative)
                self.store.event(self.run_id, "verification_archived", {"from": str(work), "to": str(archived)})
            t0 = time.time()
            props = self._request_properties(ck, contract)
            if props is None:
                props = Path(ck["properties_path"]) if ck.get("properties_path") else None
            # Optional proof work must not consume the budget needed for the
            # mandatory independent-reference agreement and request checks.
            required_props = props if self.cfg.verification.require_formal else None
            res = verify(contract, rp, ref, work, self.cfg, props_path=required_props)
            self.tool_time_s += time.time() - t0
            (work / "evidence.json").write_text(json.dumps(res.to_dict(), indent=1))
            shutil.copy(rp, work / rp.name)
            sig = _signature(res)
            entry = {"attempt": attempt, "stage": res.stage, "accepted": res.accepted, "summary": res.summary, "signature": sig,
                     "rtl_sha256": res.artifacts.get("rtl_sha256"), "evidence": str(work / "evidence.json")}
            history.append(entry)
            self.store.event(self.run_id, "verification", entry)
            self.log(f"[verify] attempt {attempt}: stage={res.stage} accepted={res.accepted} — {res.summary}")
            ck.update({"history": history, "rtl_attempt": attempt, "last_evidence": str(work / "evidence.json")})
            self.store.checkpoint(self.run_id, "verify", ck)
            if res.accepted:
                # deterministic acceptance guards (zero-false-alarm contradictions between contract and RTL)
                findings = acceptance_guards(contract, rp.read_text())
                if findings:
                    res.accepted = False
                    res.summary = "acceptance guard: " + "; ".join(f.code for f in findings)
                    res.guard_findings = [f.__dict__ for f in findings]
                    (work / "evidence.json").write_text(json.dumps(res.to_dict(), indent=1))
                    history[-1].update({"accepted": False, "summary": res.summary, "signature": "guard:" + ",".join(f.code for f in findings)})
                    self.store.event(self.run_id, "acceptance_guard", {"findings": [f.code for f in findings]})
                    self.log(f"[guard] {res.summary}")
                    ck.update({"history": history})
                    self.store.checkpoint(self.run_id, "verify", ck)
                    if attempt >= max_iter:
                        raise BudgetExhausted(f"repair iteration limit {max_iter} reached without acceptance")
                    attempt += 1
                    new_rtl, verdict = self._repair(contract, rp, res, attempt, ck.get("request", ""))
                    if new_rtl is None or hashlib.sha256(new_rtl.encode()).hexdigest() == res.artifacts.get("rtl_sha256"):
                        raise Stalled("repair did not address an acceptance-guard finding")
                    rp.write_text(self._normalize(new_rtl, f"repair_{attempt}"))
                    self._save("rtl_candidate", rp, f"repair_{attempt}")
                    ck.update({"rtl_attempt": attempt, "history": history})
                    self.store.checkpoint(self.run_id, "verify", ck)
                    continue
                if not ck.get("consensus_done") and self.cfg.verification.corroborate:
                    # Acceptance requires agreement with TWO independently derived references (or a majority of three).
                    ck, ref, ok = self._corroborate_acceptance(ck, contract, rp, ref)
                    self.store.checkpoint(self.run_id, "verify", ck)
                    if not ok:
                        continue  # a majority of references disagrees with the RTL: re-verify against the adopted one, then repair
                ck = self._check_request_tables(ck, contract, ref)
                if (ck.get("request_table_check", {}).get("status") == "mismatch"
                        and not ck.get("table_repair") and attempt < max_iter):
                    return self._queue_table_repair(ck, attempt + 1)
                t0 = time.time()
                clock = check_clock(contract, ck.get("request", ""), rp, vdir / "clock_check", self.cfg,
                                    min(60, self.budget.wall_time_s - (time.time() - self.budget.started) - 2))
                self.tool_time_s += time.time() - t0
                ck["clock_check"] = clock
                if clock["status"] != "not_applicable":
                    self.store.event(self.run_id, "clock_check", clock)
                    self.log(f"[clock] {clock['status']}: {clock['detail']}")
                if clock["status"] == "mismatch" and not ck.get("table_repair") and attempt < max_iter:
                    return self._queue_table_repair(ck, attempt + 1, check_key="clock_check")
                if (not self.cfg.verification.require_formal and self.cfg.verification.run_formal
                        and props is not None and props.is_file() and not contract.combinational
                        and clock["status"] in {"ok", "not_applicable"}
                        and ck.get("request_table_check", {}).get("status") not in {"mismatch", "error"}):
                    remaining = self.budget.wall_time_s - (time.time() - self.budget.started) - 2
                    if remaining > 0:
                        t0 = time.time()
                        formal = run_formal(contract, rp, props, work / "formal", self.cfg.tools.sby,
                                            self.cfg.verification.formal_depth,
                                            min(self.cfg.verification.formal_timeout_s, remaining), yosys=self.cfg.tools.yosys)
                        self.tool_time_s += time.time() - t0
                        res.formal = {"ok": formal.ok, **formal.to_dict(), **formal.extra,
                                      "tail": formal.tail(40)}
                        # Persist the counterexample before spending remaining time on review.
                        summary_before_formal = res.summary.replace("; formal not run", "")
                        res.summary = summary_before_formal + f"; optional formal BMC depth {self.cfg.verification.formal_depth}: {formal.extra.get('status')}"
                        res.artifacts.update(properties=str(props), properties_sha256=hashlib.sha256(props.read_bytes()).hexdigest())
                        history[-1]["summary"] = res.summary
                        (work / "evidence.json").write_text(json.dumps(res.to_dict(), indent=1))
                        formal = self._review_counterexample_properties(ck, contract, rp, props, work, formal)
                        res.formal = {"ok": formal.ok, **formal.to_dict(), **formal.extra, "tail": formal.tail(40)}
                        res.artifacts.update(properties=str(props), properties_sha256=hashlib.sha256(props.read_bytes()).hexdigest())
                        res.summary = summary_before_formal + f"; optional formal BMC depth {self.cfg.verification.formal_depth}: {formal.extra.get('status')}"
                        self.log(f"[formal] optional check: {formal.extra.get('status')}")
                    else:
                        res.formal = {"ok": False, "status": "not_run", "error": "No remaining time for optional formal verification"}
                    (work / "evidence.json").write_text(json.dumps(res.to_dict(), indent=1))
                    history[-1]["summary"] = res.summary
                    ck["history"] = history
                    self.store.event(self.run_id, "optional_formal", res.formal)
                ck["final_evidence"] = str(work / "evidence.json")
                self.store.checkpoint(self.run_id, "report", ck)
                return ck
            # --- decide next move ---------------------------------------------------------
            if res.reference_error:
                if ref_regenerated:
                    raise Stalled("reference model failed twice; cannot verify")
                self.log("[verify] reference model failed at full length; regenerating reference once")
                ck["reference_feedback"] = "The previous reference model crashed during simulation: " + res.reference_error[:800]
                ck["reference_regenerated"] = True
                ref_regenerated = True
                ck = self._step_reference(ck)
                ref = Path(ck["reference_path"])
                self.store.checkpoint(self.run_id, "verify", ck)
                continue
            sim_failed = res.stage == "simulate" and any(s_["status"] == "fail" for s_ in res.sims)
            if sim_failed and not ck.get("consensus_done"):
                ck, ref, corroborated = self._reference_consensus(ck, contract, rp, ref, res)
                ref_regenerated = True
                self.store.checkpoint(self.run_id, "verify", ck)
                if corroborated or ck.get("consensus", {}).get("outcome") == "majority_alt1":
                    continue  # re-verify against the adopted reference (attempt number unchanged)
            if attempt >= max_iter:
                raise BudgetExhausted(f"repair iteration limit {max_iter} reached without acceptance")
            if signatures.count(sig) >= 2 and sig:
                raise Stalled("identical failure signature observed three times; no progress")
            signatures.append(sig)
            # --- repair -----------------------------------------------------------------------
            attempt += 1
            new_rtl, verdict = self._repair(contract, rp, res, attempt, ck.get("request", ""))
            if verdict == "reference" and not ref_regenerated:
                self.log("[repair] RTL role disputes the reference model; regenerating reference once (independently)")
                ck["reference_feedback"] = ("A reviewer believes an earlier reference model misread the contract. Re-derive the behavior strictly from the contract text; "
                                            "pay special attention to reset values, registered vs combinational outputs, and boundary conditions.")
                ck["reference_regenerated"] = True
                ref_regenerated = True
                ck = self._step_reference(ck)
                ref = Path(ck["reference_path"])
            if new_rtl is None:
                self.store.event(self.run_id, "repair_failed", {"attempt": attempt})
                if verdict != "reference":
                    raise Stalled("repair role produced no usable Verilog")
            else:
                identical = hashlib.sha256(new_rtl.encode()).hexdigest() == res.artifacts.get("rtl_sha256")
                if identical and verdict != "reference":
                    if ref_regenerated:
                        raise Stalled("repair returned identical RTL")
                    # The RTL role stands by its design: treat this as a dispute of the reference and re-derive it once.
                    self.log("[repair] RTL unchanged after repair; re-deriving the reference model independently before continuing")
                    ck["reference_feedback"] = ("An earlier reference model for this contract was disputed. Re-derive the behavior strictly from the request and contract. "
                                                "Check especially: registered outputs must be returned BEFORE the state update; registered pulses appear one step after their cause; reset values; priorities.")
                    ck["reference_regenerated"] = True
                    ref_regenerated = True
                    ck = self._step_reference(ck)
                    ref = Path(ck["reference_path"])
                else:
                    rp.write_text(self._normalize(new_rtl, f"repair_{attempt}"))
                    self._save("rtl_candidate", rp, f"repair_{attempt}")
            ck.update({"rtl_attempt": attempt, "history": history})
            self.store.checkpoint(self.run_id, "verify", ck)

    def _repair(self, contract: Contract, rp: Path, res: VerificationResult, attempt: int, request: str = ""):
        ctx = P.contract_context(contract, request)
        user = P.REPAIR_USER.format(request=ctx["request"], contract_json=ctx["contract_json"], rtl=rp.read_text(), evidence=res.evidence_for_model())
        r = self._call("repair", P.REPAIR_SYSTEM, user, seed=(self.cfg.model.seed or 0) + attempt)
        if not r.ok:
            return None, "rtl"
        verdict = "reference" if "VERDICT: reference" in r.text else "rtl"
        code = extract_code(r.text, ("verilog", "systemverilog", "v", "sv"))
        if code and f"module {contract.module_name}" not in code:
            code = None
        self.store.event(self.run_id, "repair", {"attempt": attempt, "verdict": verdict, "has_code": bool(code)})
        return code, verdict

    def _check_request_tables(self, ck: dict, contract: Contract, ref: Path) -> dict:
        """Compare the reference against any table printed in the request. No model call."""
        cached = ck.get("request_table_check") or {}
        fingerprint = hashlib.sha256(json.dumps({"request": ck.get("request", ""),
                                                "contract": contract.model_dump(mode="json"),
                                                "reference_sha256": hashlib.sha256(ref.read_bytes()).hexdigest()},
                                               sort_keys=True).encode()).hexdigest()
        if (cached.get("input_fingerprint") == fingerprint and cached.get("checker_version") == CHECKER_VERSION
                and cached.get("status") in {"ok", "mismatch", "not_applicable"}):
            return ck
        t0 = time.time()
        remaining = min(120, self.budget.wall_time_s - (t0 - self.budget.started) - 2) if self.budget else 120
        res = check_reference_against_request_tables(
            contract, ck.get("request", ""), ref, self.ws.dir("verification") / "request_tables", timeout_s=remaining)
        self.tool_time_s += time.time() - t0
        res["input_fingerprint"] = fingerprint
        ck["request_table_check"] = res
        if res["status"] == "not_applicable":
            return ck
        self.store.event(self.run_id, "request_table_check", res)
        if res["status"] == "mismatch":
            self.log(f"[tables] the reference contradicts the request's own table: {res['detail'][:300]}")
        elif res["status"] == "ok":
            unit = "observed cycles" if "checked_cycles" in res else "rows"
            self.log(f"[tables] reference agrees with the request's printed table on all {res['rows']} {unit}")
        else:
            self.log(f"[tables] check inconclusive: {res['detail'][:200]}")
        return ck

    def _queue_table_repair(self, ck: dict, repairs_used: int, check_key: str = "request_table_check") -> dict:
        """One bounded restart from independent evidence tied to the user's request.

        No RTL, reference code or hidden benchmark evidence enters the revision
        prompt. Preserve all prior deliverables before regeneration overwrites them.
        """
        saved = self.ws.root / "retained" / ("table-repair-" + uuid.uuid4().hex[:12])
        saved.mkdir(parents=True)
        for name in ("spec", "reference", "rtl", "verification", "reports"):
            shutil.copytree(self.ws.dir(name), saved / name)
        (saved / "checkpoint.json").write_text(json.dumps(ck, indent=2))
        evidence = ck[check_key]
        clock = check_key == "clock_check"
        correction = ("The RTL contradicts the independently checked conventional 12-hour clock semantics specified by the request. "
                      "Correct the contract's behavior and requirements to agree with the observed counterexample. " if clock else
                      "The generated reference contradicts rows printed in the original request. "
                      "Correct the contract's erroneous behavior/requirements to match every printed row. ")
        if check_key == "lfsr_check":
            correction = ("The generated reference contradicts the request's explicit right-shifting Galois LFSR transitions. "
                          "Correct the contract's transition equation to match the observed request-derived sequence and tap numbering. ")
        feedback = ({k: evidence[k] for k in ("kind", "status", "binding", "detail", "checked_cycles") if k in evidence}
                    if clock else evidence)
        change = ("Automatic correction from tool evidence, not a new user requirement. "
                  + correction +
                  "Remove contradictory simplifications. Preserve exactly the module, ports, parameters "
                  "and clock/reset. Do not invent requirements or change the original request.\n"
                  + json.dumps(feedback) + self._request_tables_text(ck["request"]))
        repair = {"retained": str(saved), "evidence": evidence, "repairs_used": repairs_used, "kind": check_key}
        next_ck = {"request": ck["request"], "base_contract_path": ck["contract_path"],
                   "contract_path": ck["contract_path"], "contract_version": ck["contract_version"],
                   "change": change, "table_repair": repair, check_key: evidence}
        self.store.checkpoint(self.run_id, "revise", next_ck)
        self.store.event(self.run_id, "table_repair", repair)
        self.log(f"[spec] retained failed artifacts; correcting the contract once from {check_key} evidence")
        return next_ck

    def _step_report(self, ck: dict, final_state: str, reason: str = "") -> tuple[dict, dict]:
        assert self.budget
        outcome = write_report(self.ws, self.store, self.run_id, ck, self.cfg, final_state=final_state, reason=reason,
                               budget=self.budget.snapshot(self.adapter, (self.alt_adapter, self.review_adapter)), tool_time_s=self.tool_time_s)
        self.store.set_outcome(self.run_id, outcome)
        if final_state == "completed":
            self.store.checkpoint(self.run_id, "done", ck)
        self.log(f"[report] {outcome['status_line']}")
        return ck, outcome


REVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["consistent", "needs_correction"]},
        "corrections": {"type": "array", "items": {"type": "object", "properties": {
            "kind": {"type": "string", "enum": ["port_timing", "port_width", "parameter", "behavior", "requirement", "conditioning"]},
            "target": {"type": "string"}, "value": {"type": "string"}, "reason": {"type": "string"}},
            "required": ["kind", "target", "value", "reason"]}},
        "unresolved": {"type": "array", "items": {"type": "string"}},
        "notes": {"type": "string"},
    },
    "required": ["verdict", "corrections", "unresolved", "notes"],
}


def _apply_correction(data: dict, c: dict) -> tuple[bool, str]:
    """Apply one reviewer correction to a contract dict in place. Only bounded, checkable edits are allowed."""
    kind, target, value = c.get("kind"), str(c.get("target", "")).strip("` "), str(c.get("value", "")).strip()
    ports = {p["name"]: p for p in data["ports"]}
    if kind == "port_timing":
        if target in ports and ports[target]["direction"] == "output" and value in ("registered", "combinational"):
            if ports[target]["timing"] == value:
                return False, "already so"
            ports[target]["timing"] = value
            return True, f"{target}.timing -> {value}"
        return False, "unknown output or bad value"
    if kind == "port_width":
        if target not in ports:
            return False, "unknown port"
        w, _, expr = value.partition(":")
        try:
            ports[target]["width"] = int(w)
        except ValueError:
            return False, "bad width"
        ports[target]["width_expr"] = expr.strip() or ports[target].get("width_expr")
        return True, f"{target}.width -> {value}"
    if kind == "parameter":
        name, _, default = value.partition("=")
        name = name.strip()
        if not re.match(r"^[A-Za-z_]\w*$", name):
            return False, "bad parameter name"
        try:
            d = int(default.strip())
        except ValueError:
            return False, "bad default"
        for prm in data["parameters"]:
            if prm["name"] == name:
                if prm["default"] == d:
                    return False, "already so"
                prm["default"] = d
                return True, f"{name} default -> {d}"
        data["parameters"].append({"name": name, "default": d, "description": "added by spec review"})
        return True, f"parameter {name}={d} added"
    if kind == "behavior":
        if len(value) < 15:
            return False, "too short"
        data["behavior"] = value
        return True, "behavior replaced; previous version retained"
    if kind == "conditioning":
        cr = data.get("clock_reset")
        if not cr or cr.get("reset") is not None:
            return False, "conditioning requires a resetless contract"
        try:
            sequence = json.loads(value)
            candidate = Contract.model_validate({**data, "clock_reset": {**cr, "conditioning": sequence}})
        except (ValueError, TypeError):
            return False, "conditioning must contain bounded complete input vectors with valid port values"
        if cr.get("conditioning", []) == candidate.clock_reset.conditioning:
            return False, "already so"
        cr["conditioning"] = candidate.clock_reset.conditioning
        return True, "resetless simulation conditioning replaced"
    if kind == "requirement":
        if len(value) < 12:
            return False, "too short"
        for rq in data["requirements"]:
            if rq["id"] == target:
                rq["text"] = value
                return True, f"{target} text replaced"
        ids = [int(rq["id"][1:]) for rq in data["requirements"]]
        new_id = f"R{(max(ids) + 1 if ids else 1):03d}"
        data["requirements"].append({"id": new_id, "text": value, "source": "inference", "source_detail": "added by independent spec review: " + str(c.get("reason", ""))[:200]})
        return True, f"{new_id} added"
    return False, "unknown kind"


_PARAM_RE = re.compile(r"\bparameters?\s+`?([A-Z][A-Z0-9_]*)`?(?:\s*\(\s*default\s+(\d+))?", re.I)
_PARAM_DEFAULT_RE = re.compile(r"`?([A-Z][A-Z0-9_]*)`?\s*\(\s*default\s+(\d+)")


def _request_parameters(request: str) -> dict[str, Optional[int]]:
    """Parameter names (and defaults when stated) the request explicitly introduces:
    'parameter `WIDTH` (default 16)', '`DEPTH` (default 16, a power of two)'."""
    names: dict[str, Optional[int]] = {}
    for rx in (_PARAM_RE, _PARAM_DEFAULT_RE):
        for m in rx.finditer(request):
            name = m.group(1)
            if name.isupper() or (name[0].isupper() and len(name) <= 2):
                default = int(m.group(2)) if m.lastindex and m.lastindex >= 2 and m.group(2) else None
                if name not in names or names[name] is None:
                    names[name] = default
    return names


def _signature(res: VerificationResult) -> str:
    if res.reference_error:
        return "ref:" + res.reference_error.splitlines()[0][:80]
    if res.lint and not res.lint.get("ok"):
        return "lint:" + ";".join(d["message"][:40] for d in res.lint.get("diagnostics", [])[:3])
    if res.compile and not res.compile.get("ok"):
        return "compile:" + ";".join(d["message"][:40] for d in res.compile.get("diagnostics", [])[:3])
    for s in res.sims:
        if s["status"] != "pass":
            fm = s["first_mismatches"][:3]
            return f"sim:{s['status']}:" + ";".join(f"{m['cycle']}/{m['port']}" for m in fm)
    if res.synth and not res.synth.get("ok"):
        return "synth:" + (res.synth.get("tail", "")[-80:])
    return ""
