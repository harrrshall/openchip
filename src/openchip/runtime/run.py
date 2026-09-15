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
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from pydantic import ValidationError

from ..config import Config
from ..contracts.coerce import coerce_contract
from ..contracts.schema import Contract, contract_json_schema
from ..contracts.triage import triage_unresolved
from ..models import prompts as P
from ..models.adapter import ModelAdapter, ProviderStatus, extract_code, extract_json
from ..reporting.report import write_report
from ..verification.formal import checker_skeleton, parse_check
from ..verification.harness import VerificationResult, compare_references, lint_reference_timing, run_reference, verify
from ..contracts.tables import expand_printed_tables
from ..contracts.interface import interface_violations, parse_interface, requested_module_name
from ..verification.guards import acceptance_guards, contract_guards
from ..verification.fsmcheck import check_reference_against_fsm, input_blind_message, input_blind_states
from ..verification.tablecheck import check_reference_against_request_tables
from ..verification.normalize import normalize_rtl
from ..verification.testbench import dump_contract_json
from .store import RunStore, lock_owner_id
from .workspace import Workspace

STEPS = ("intake", "review", "reference", "properties", "rtl", "verify", "report", "done")

# Roles whose reply is only usable if a structured payload can be parsed out of it. A call that ends at
# the token cap without one is escalated once instead of being repeated identically (see Runner._call).
PAYLOAD_LANGS = {"python": ("python", "py"), "verilog": ("verilog", "systemverilog", "v", "sv")}


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

    def check(self, adapter: ModelAdapter) -> None:
        if time.time() - self.started > self.wall_time_s:
            raise BudgetExhausted(f"wall time {self.wall_time_s:.0f}s exceeded")
        if adapter.usage.calls >= self.max_model_calls:
            raise BudgetExhausted(f"model call limit {self.max_model_calls} reached")
        if adapter.usage.total_tokens >= self.max_total_tokens:
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
        self._no_think_roles = _PROCESS_NO_THINK_ROLES
        self.escalations: list[dict] = []
        for ad in (self.adapter, self.alt_adapter, self.review_adapter):
            if ad is not None and hasattr(ad, "on_event"):
                ad.on_event = self._provider_event


    # -- provider feed ----------------------------------------------------------------------
    _PROVIDER_PHRASE = {"rate_limited": "rate limited by", "quota": "usage limit reached on",
                        "server_error": "server error from", "unreachable": "cannot reach",
                        "invalid_key": "key rejected by", "no_key": "no API key for"}

    def _provider_event(self, ev: dict) -> None:
        """Called by an adapter on every classified provider answer worth showing (retries, failures)."""
        st = ev.get("status") or {}
        kind = st.get("kind") or "unknown"
        phrase = self._PROVIDER_PHRASE.get(kind, f"{kind} from")
        line = f"[provider] {phrase} {st.get('provider') or 'the provider'}"
        if ev.get("sleep_s"):
            line += f": retrying in {float(ev['sleep_s']):.0f} s (attempt {ev.get('attempt')} of {ev.get('attempts')})"
        elif st.get("message"):
            line += f": {st['message']}"
        try:
            self.log(line)
        except Exception:  # noqa: BLE001
            pass
        if self.run_id:
            self.store.event(self.run_id, "provider", {"status": st, "attempt": ev.get("attempt"),
                                                       "attempts": ev.get("attempts"), "sleep_s": ev.get("sleep_s"), "line": line})

    def provider_status(self) -> Optional[dict]:
        st = getattr(self.adapter, "last_status", None)
        if isinstance(st, ProviderStatus):
            return st.as_dict()
        return st if isinstance(st, dict) else None

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
        b = cfg_dump["budget"]
        self.budget = Budget(b["wall_time_s"], b["max_model_calls"], b["max_total_tokens"], b["max_repair_iterations"])
        (self.ws.root / "request" / f"change.v{base.version + 1}.md").write_text(change.strip() + "\n")
        schema = contract_json_schema()
        errors: list[str] = []
        for attempt in range(3):
            user = P.REVISE_USER.format(request=request, version=base.version, contract_json=base.model_dump_json(indent=1), change=change)
            if errors:
                user += "\n\nYour previous revision was rejected by the validator:\n" + errors[-1] + "\nFix these problems."
            r = self._call("revise", P.REVISE_SYSTEM, user, json_schema=schema, seed=(self.cfg.model.seed or 0) + attempt, payload="json")
            data = extract_json(r.text) if r.ok else None
            if data is None:
                errors.append("reply was not a JSON object" if r.ok else r.error)
                continue
            data, _ = coerce_contract(data, request)
            data["version"] = base.version + 1
            data["parent_version"] = base.version
            data["revision_authority"] = "user"
            data.setdefault("revision_reason", change[:200])
            if not data.get("revision_reason"):
                data["revision_reason"] = change[:200]
            try:
                contract = Contract.model_validate(data)
            except ValidationError as e:
                errors.append(str(e)[:2000])
                continue
            cj = spec / f"contract.v{contract.version}.json"
            cj.write_text(contract.model_dump_json(indent=1))
            (spec / f"contract.v{contract.version}.md").write_text(contract.summary_md())
            self._save("contract", cj, "revise")
            changed = [rq.id for rq in contract.requirements if rq.text not in {q.text for q in base.requirements}]
            self.store.event(self.run_id, "contract_revised", {"from": base.version, "to": contract.version, "changed_or_new": changed})
            self.log(f"[revise] contract v{contract.version} (parent v{base.version}); changed/new requirements: {changed or 'none'}; previous evidence invalidated")
            ck = {"request": request + "\n\nChange request (v" + str(contract.version) + "): " + change.strip(), "contract_path": str(cj), "contract_version": contract.version}
            self.store.checkpoint(self.run_id, "reference", ck)
            self.store.set_state(self.run_id, "planned")
            return self.run_id
        raise RuntimeError("revision failed: " + (errors[-1] if errors else "no valid contract"))

    def resume(self, run_id: str) -> None:
        run = self.store.get_run(run_id)
        if not run:
            raise KeyError(f"unknown run {run_id}")
        self.run_id = run_id

    def execute(self) -> dict:
        run = self.store.get_run(self.run_id)
        assert run
        b = run["config"]["budget"]
        self.budget = Budget(b["wall_time_s"], b["max_model_calls"], b["max_total_tokens"], b["max_repair_iterations"])
        owner = lock_owner_id()
        if not self.store.acquire_lock(self.run_id, owner):
            raise RuntimeError("run is locked by another live process")
        self.store.set_state(self.run_id, "running", resumed_from=run["step"])
        ck = dict(run["checkpoint"])
        step = run["step"]
        outcome: dict = {}
        try:
            if step == "intake":
                ck = self._step_intake(ck)
                step = "review"
            if step == "review":
                ck = self._step_review(ck)
                step = "reference"
            if step == "reference":
                ck = self._step_reference(ck)
                step = "properties"
            if step == "properties":
                ck = self._step_properties(ck)
                step = "rtl"
            if step == "rtl":
                ck = self._step_rtl(ck)
                step = "verify"
            if step == "verify":
                ck = self._step_verify(ck)
                step = "report"
            if step == "report":
                ck["provider_status"] = self.provider_status()
                ck, outcome = self._step_report(ck, final_state="completed")
            self.store.set_state(self.run_id, "completed", accepted=outcome.get("accepted"))
        except BudgetExhausted as e:
            self.log(f"[budget] {e}")
            ck["provider_status"] = self.provider_status()
            ck, outcome = self._step_report(ck, final_state="budget_exhausted", reason=str(e))
            self.store.set_state(self.run_id, "budget_exhausted", reason=str(e))
        except Stalled as e:
            self.log(f"[stalled] {e}")
            ck["provider_status"] = self.provider_status()
            ck, outcome = self._step_report(ck, final_state="stalled", reason=str(e))
            self.store.set_state(self.run_id, "stalled", reason=str(e))
        except KeyboardInterrupt:
            self.store.set_state(self.run_id, "paused", reason="interrupted")
            raise
        except Exception as e:  # noqa: BLE001
            blocked = self.provider_status() or {}
            if blocked.get("kind") in ("rate_limited", "quota", "invalid_key", "no_key", "unreachable"):
                # The model provider, not the design, stopped the run: park it at its checkpoint so it can be
                # resumed once the key, quota or connection is fixed, and say so in the feed.
                ck["provider_status"] = blocked
                self.store.checkpoint(self.run_id, step, ck)
                self.store.event(self.run_id, "provider", {"status": blocked, "paused": True})
                self.log(f"[provider] run paused at {step}: {blocked.get('kind')} ({str(blocked.get('message'))[:160]})")
                self.store.set_state(self.run_id, "paused", reason=f"provider {blocked.get('kind')}: {str(blocked.get('message'))[:200]}")
                return {"state": "paused", "provider_status": blocked}
            self.store.event(self.run_id, "error", {"error": f"{type(e).__name__}: {e}"})
            try:
                ck["provider_status"] = self.provider_status()
                ck, outcome = self._step_report(ck, final_state="failed", reason=f"{type(e).__name__}: {e}")
            finally:
                self.store.set_state(self.run_id, "failed", reason=f"{type(e).__name__}: {e}")
            raise
        finally:
            self.store.release_lock(self.run_id)
        return outcome

    # -- helpers ------------------------------------------------------------------------------
    def _payload_ok(self, r, payload: Optional[str], json_schema: Optional[dict] = None) -> bool:
        """Did this reply carry the structured payload the role needs?

        A reply truncated at the token cap usually still contains a complete `{...}` somewhere — the
        first port object of an unfinished contract, say. Taking that for the payload skips the
        escalation and spends all three intake attempts on the same truncation, so when the role
        declared a schema the object must also carry that schema's required keys.
        """
        if not payload or not r.ok:
            return bool(r.ok)
        if payload == "json":
            data = extract_json(r.text)
            if data is None:
                return False
            required = (json_schema or {}).get("required") or []
            return all(k in data for k in required)
        return extract_code(r.text, PAYLOAD_LANGS.get(payload, ())) is not None

    def _escalated_max_tokens(self, mcfg, prompt_tokens: int) -> int:
        """Deterministic single step up: 4x the configured cap, capped by what the context window leaves."""
        room = mcfg.context_window - max(prompt_tokens, 0) - 256
        return max(mcfg.max_tokens, min(4 * mcfg.max_tokens, room))

    def _call(self, role: str, system: str, user: str, json_schema: Optional[dict] = None, temperature: Optional[float] = None, seed: Optional[int] = None,
              adapter: Optional[ModelAdapter] = None, payload: Optional[str] = None):
        assert self.budget
        self.budget.check(self.adapter)
        self.store.touch_lock(self.run_id)
        adapter = adapter or self.adapter
        mcfg = adapter.cfg
        tr = mcfg.thinking_roles
        think = (mcfg.thinking if tr is None else (role in tr)) and f"{adapter.cfg.model}:{role}" not in self._no_think_roles
        msgs = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        r = adapter.chat(msgs, role=role, json_schema=json_schema, temperature=temperature, seed=seed, thinking=think)
        tag = "" if adapter is self.adapter else f" [{adapter.cfg.model}]"
        self.store.event(self.run_id, "model_call", {"role": role, "ok": r.ok, "finish": r.finish_reason, "prompt_tokens": r.prompt_tokens,
                                                     "completion_tokens": r.completion_tokens, "latency_s": round(r.latency_s, 2), "error": r.error, "thinking": think, "model": adapter.cfg.model})
        self.log(f"[model:{role}]{tag} {r.finish_reason} in {r.latency_s:.1f}s ({r.prompt_tokens}+{r.completion_tokens} tok)" + (f" ERROR {r.error}" if r.error else ""))
        if think and r.finish_reason == "length":
            # Reasoning consumed the token budget (any answer is truncated): retry without thinking, and stop
            # using thinking for this role for the rest of the run — this model cannot finish within the cap.
            self._no_think_roles.add(f"{adapter.cfg.model}:{role}")
            self.budget.check(self.adapter)
            self.log(f"[model:{role}]{tag} thinking hit the token cap; retrying without thinking (and for the rest of this run)")
            r = adapter.chat(msgs, role=role, json_schema=json_schema, temperature=temperature, seed=seed, thinking=False)
            self.store.event(self.run_id, "model_call", {"role": role, "ok": r.ok, "finish": r.finish_reason, "prompt_tokens": r.prompt_tokens,
                                                         "completion_tokens": r.completion_tokens, "latency_s": round(r.latency_s, 2), "error": r.error, "thinking": False, "fallback": True})
            self.log(f"[model:{role}] {r.finish_reason} in {r.latency_s:.1f}s ({r.prompt_tokens}+{r.completion_tokens} tok) [no-thinking fallback]")
        if r.finish_reason == "length" and payload and not self._payload_ok(r, payload, json_schema):
            # The reply hit the token cap with no usable payload: the reasoning ate the budget. Repeating the
            # identical request just burns it again (three intake calls, three truncations, no contract), so
            # escalate once — a larger cap and the provider's reasoning effort turned down — and record it.
            mt = self._escalated_max_tokens(mcfg, r.prompt_tokens)
            self.budget.check(self.adapter)
            self.log(f"[model:{role}]{tag} finished at the {mcfg.max_tokens}-token cap with no {payload} payload; "
                     f"escalating once: max_tokens={mt}, reasoning turned down")
            r2 = adapter.chat(msgs, role=role, json_schema=json_schema, temperature=temperature, seed=seed,
                              thinking=False, max_tokens=mt, reasoning_off=True)
            esc = {"role": role, "model": adapter.cfg.model, "from_max_tokens": mcfg.max_tokens, "to_max_tokens": mt,
                   "reasoning_off": True, "finish": r2.finish_reason, "completion_tokens": r2.completion_tokens,
                   "recovered": self._payload_ok(r2, payload, json_schema)}
            self.escalations.append(esc)
            self.store.event(self.run_id, "model_escalation", esc)
            self.store.event(self.run_id, "model_call", {"role": role, "ok": r2.ok, "finish": r2.finish_reason, "prompt_tokens": r2.prompt_tokens,
                                                         "completion_tokens": r2.completion_tokens, "latency_s": round(r2.latency_s, 2), "error": r2.error,
                                                         "thinking": False, "escalated": True, "model": adapter.cfg.model})
            self.log(f"[model:{role}]{tag} {r2.finish_reason} in {r2.latency_s:.1f}s ({r2.prompt_tokens}+{r2.completion_tokens} tok) [escalated]")
            if self._payload_ok(r2, payload, json_schema) or r2.ok:
                r = r2
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
        tables = self._request_tables_text(request)
        schema = contract_json_schema()
        errors: list[str] = []
        for attempt in range(3):
            user = P.INTAKE_USER.format(request=request, documents=docs) + self._interface_text(request) + tables
            if errors:
                user += "\n\nYour previous contract was rejected by the validator:\n" + errors[-1] + "\nFix these problems."
            r = self._call("intake", P.INTAKE_SYSTEM, user, json_schema=schema, seed=(self.cfg.model.seed or 0) + attempt, payload="json")
            data = extract_json(r.text) if r.ok else None
            if data is None:
                if r.ok and r.finish_reason == "length":
                    errors.append("your previous reply ran out of tokens before the JSON object was complete. "
                                  "Answer with the JSON object FIRST and nothing else \u2014 no reasoning, no commentary, "
                                  "no second attempt \u2014 and keep `behavior` to a few precise sentences")
                else:
                    errors.append("reply was not a JSON object" if r.ok else r.error)
                continue
            data, coerce_notes = coerce_contract(data, request)
            if coerce_notes:
                self.store.event(self.run_id, "contract_coerced", {"attempt": attempt, "notes": coerce_notes})
                ck["coerce_notes"] = coerce_notes
            data.setdefault("version", 1)
            data["version"] = 1
            data["parent_version"] = None
            for note in _drop_invented_reset(data, request) + _lock_module_name(data, request):
                self.store.event(self.run_id, "interface_locked", {"attempt": attempt, "note": note})
                self.log(f"[intake] {note}")
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
            iface = parse_interface(request)
            if iface:
                viol = interface_violations(iface, [(p.name, p.direction.value, p.width) for p in contract.ports])
                if viol:
                    msg = ("the request prints its own interface list and the contract's ports must be exactly that "
                           "list: " + "; ".join(viol) + ". Use the request's port names, directions and widths "
                           "verbatim; never add a reset or a clock the list does not contain, and never drop one it "
                           "does. If the list has no reset port, set clock_reset.reset to null.")
                    errors.append(msg)
                    self.store.event(self.run_id, "contract_rejected", {"attempt": attempt, "error": msg})
                    continue
            if not contract.outputs():
                # A module with no output cannot be built, simulated or delivered. `Prob031_dff`
                # prints "- input q" where its own reference declares `output q`: copying that list
                # literally cost the whole run. Say what is wrong and ask again.
                msg = ("the contract declares no output port, so the module would produce nothing and could not be "
                       "verified. Re-read the request: the signal it describes as the module's result is an OUTPUT, "
                       "even if the request's own interface list mislabels it as an input. Declare it as an output "
                       "and keep every other port as the request lists it.")
                errors.append(msg)
                self.store.event(self.run_id, "contract_rejected", {"attempt": attempt, "error": msg, "code": "no_output_port"})
                self.log("[intake] contract rejected: no output port")
                continue
            why_fsm = request_requires_fsm(request)
            if why_fsm and contract.fsm is None and attempt < 2:
                # Not on the last attempt: a missing table is worth two more asks, but losing the
                # whole run over it would deliver nothing at all. The last attempt continues and the
                # omission is recorded instead.
                msg = ("this request needs the `fsm` section and you left it null: " + why_fsm + ". Fill `fsm` "
                       "with the reset state, one named state per state of the machine, `output_style` for every "
                       "output (moore or mealy), and one `transitions` row per (state, condition) pair so every "
                       "input case of every state is covered. The table is the specification: a row's `outputs` "
                       "are the values driven DURING that cycle, and a Moore output must carry the same value in "
                       "every row of the same state. Read the request's diagram or table row by row and copy it.")
                errors.append(msg)
                self.store.event(self.run_id, "contract_rejected", {"attempt": attempt, "error": msg, "code": "fsm_missing"})
                self.log(f"[intake] contract rejected: {why_fsm} but `fsm` is null; asking again")
                continue
            if why_fsm and contract.fsm is None:
                self.store.event(self.run_id, "fsm_section_missing", {"reason": why_fsm, "attempts": attempt + 1})
                self.log("[intake] no `fsm` section after 3 attempts; continuing without the FSM table check")
            # State completeness: a state that never samples an input the rest of the table samples
            # throws that cycle's bit away. `seq_detect` lost overlapping detection exactly this way
            # (evals/results/final-2026-09-14/.../seq_detect), and because the reference is written
            # from the same table neither the table check nor simulation can see it.
            blind = input_blind_states(contract, contract.fsm) if contract.fsm else []
            if blind and attempt < 2:
                msg = input_blind_message(blind)
                errors.append(msg)
                self.store.event(self.run_id, "contract_rejected",
                                 {"attempt": attempt, "error": msg, "code": "fsm_input_blind", "states": blind})
                self.log("[intake] contract rejected: " + ", ".join(f"state `{b['state']}` ignores `{b['input']}`" for b in blind))
                continue
            if blind:
                self.store.event(self.run_id, "fsm_input_blind_unresolved", {"states": blind, "attempts": attempt + 1})
                self.log("[intake] transition table still ignores an input after 3 attempts; recorded and continuing")
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

    # -- independent spec review ----------------------------------------------------------------
    def _step_review(self, ck: dict) -> dict:
        """A separate context (optionally a different model) compares request and contract and proposes
        corrections; safe corrections are applied as a recorded contract revision before any code is written."""
        if not self.cfg.review.enabled:
            self._apply_contract_guards(ck, self._triage_contract(ck, self._load_contract(ck)))
            self.store.checkpoint(self.run_id, "reference", ck)
            return ck
        contract = self._load_contract(ck)
        request = ck.get("request", "")
        user = (P.REVIEW_USER.format(request=request, contract_json=contract.model_dump_json(indent=1))
                + self._interface_text(request) + self._request_tables_text(request))
        if ck.get("coerce_notes"):
            user += "\n\nNote: these fields were DEFAULTED mechanically because the intake omitted them — verify each: " + "; ".join(ck["coerce_notes"])
        adapter = self.review_adapter or self.adapter
        r = self._call("review", P.REVIEW_SYSTEM, user, json_schema=REVIEW_SCHEMA, adapter=adapter, payload="json")
        data = extract_json(r.text) if r.ok else None
        if not data:
            self.store.event(self.run_id, "review_skipped", {"error": r.error or "no JSON"})
            self.log("[review] no usable review; continuing with the intake contract")
            self._triage_contract(ck, self._load_contract(ck))
            self.store.checkpoint(self.run_id, "reference", ck)
            return ck
        corrections = [c for c in (data.get("corrections") or []) if isinstance(c, dict)][: self.cfg.review.max_corrections]
        unresolved = [u for u in (data.get("unresolved") or []) if isinstance(u, str) and u.strip()]
        applied, rejected = [], []
        if corrections and self.cfg.review.apply_corrections:
            new_data = contract.model_dump(mode="json")
            for c in corrections:
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
        self._apply_contract_guards(ck, self._triage_contract(ck, self._load_contract(ck)))
        uncovered = [u for u in (data.get("uncovered") or []) if isinstance(u, str) and u.strip()][:12]
        ck["review"] = {"verdict": data.get("verdict"), "applied": applied, "rejected": rejected, "unresolved": unresolved,
                        "uncovered": uncovered, "notes": str(data.get("notes", ""))[:300], "reviewer_model": adapter.cfg.model}
        if uncovered:
            self.log(f"[review] {len(uncovered)} request sentence(s) not represented in the contract: " + "; ".join(uncovered)[:300])
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

    def _interface_text(self, request: str) -> str:
        """The request's own interface list, restated as the authoritative port set.

        Measured: an invented `rst`/`reset` is behind 7 of 57 false acceptances, and two recorded runs
        on `Prob117_circuit9` failed at intake outright because the model wrote a reset the request
        does not have (`docs/decisions/0016-live-0014-0015.md` L2).
        """
        ports = parse_interface(request)
        if not ports:
            return ""
        lines = "\n".join(f"  - {p.direction} {p.name}" + (f" ({p.width} bits)" if p.width else " (1 bit)")
                          for p in ports)
        return ("\n\nThe request prints its interface. It is the complete and authoritative port list; the "
                "contract's `ports` must be exactly these, with these directions and widths, and nothing else:\n"
                + lines + "\nThere is no reset port unless it appears above. If none appears, set "
                "`clock_reset.reset` to null and state each register's power-up value in `behavior`.")

    def _request_tables_text(self, request: str) -> str:
        """Any table or clocked dump printed in the request, expanded mechanically, for intake and review.

        Combinational grids go wrong when the model applies MSB-first instead of the printed axis
        labels (ADR 0010). Clocked dumps go unread entirely (ADR 0013 detection-only). Both expansions
        are produced by a parser so the model is not asked to read the grid or the dump itself.
        """
        rendered = expand_printed_tables(request)
        if not rendered:
            return ""
        try:
            (self.ws.dir("spec") / "request_tables.md").write_text(rendered + "\n")
        except Exception:  # noqa: BLE001
            pass
        return ("\n\nThe request contains a table or clocked waveform, expanded below by a parser. "
                "It is authoritative: state the behavior so that it reproduces exactly these "
                "observations, and do not re-derive them from the grid or dump yourself.\n\n" + rendered)

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
                           temperature=(self.cfg.model.temperature if seed_offset == 0 else max(self.cfg.model.temperature, 0.7)), adapter=alt, payload="python")
            code = extract_code(r.text, ("python", "py")) if r.ok else None
            if not code or "class Reference" not in code:
                last_err = "no ```python block defining class Reference was found" if r.ok else r.error
                self.store.event(self.run_id, "reference_rejected", {"attempt": attempt, "error": last_err})
                continue
            out_path.write_text(code)
            vec = run_reference(out_path, cj, seed=1, cycles=50, out=work / "smoke.json")
            if vec.get("error"):
                last_err = vec["error"]
                out_path.with_suffix(f".rejected{attempt}.py").write_text(code)
                self.store.event(self.run_id, "reference_rejected", {"attempt": attempt, "error": last_err[:2000]})
                self.log(f"[reference] attempt {attempt + 1} failed to execute: {last_err.splitlines()[0][:120]}")
                continue
            lint = lint_reference_timing(out_path, cj, work / "timing_lint.json")
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
            tab = check_reference_against_request_tables(
                contract, ck.get("request", ""), out_path, work / f"tables_{attempt}")
            if tab.get("status") == "mismatch":
                last_err = ("TABLE ERROR: the reference contradicts a table printed in the request "
                            f"on {len(tab.get('mismatches') or [])} row(s): {tab.get('detail') or ''}")
                if attempt + 1 < attempts or seed_offset != 0:
                    out_path.with_suffix(f".rejected{attempt}.py").write_text(code)
                    self.store.event(self.run_id, "reference_rejected", {
                        "attempt": attempt, "error": last_err[:2000], "table_check": tab})
                    self.log(f"[reference] attempt {attempt + 1} rejected by request-table check: {last_err[:180]}")
                    continue
                # Last attempt of the primary derivation: an unresolved disagreement with the request's own table is a reason to
                # withhold sign-off, not to end the run with nothing. The reference is kept, the run
                # goes on to the RTL, and the mismatch is recorded as an unresolved item, so the
                # design is delivered as provisional with the disagreement named.
                ck["reference_table_mismatch"] = tab
                self.store.event(self.run_id, "reference_table_mismatch_unresolved", {"attempt": attempt, "table_check": tab})
                self._record_unresolved(
                    ck, "the reference model disagrees with a table printed in the request on "
                    f"{len(tab.get('mismatches') or [])} row(s) and three independent derivations did not "
                    f"resolve it: {(tab.get('detail') or '')[:400]}. Sign-off is withheld until the user says "
                    "which is right.")
                self.log(f"[reference] request-table mismatch unresolved after {attempts} attempt(s); "
                         "keeping the last reference and continuing as provisional")
                return out_path, ""
            return out_path, ""
        return None, last_err

    def _record_unresolved(self, ck: dict, item: str) -> None:
        """Add an unresolved question to the contract on disk, so the sign-off gate sees it."""
        path = ck.get("contract_path")
        if not path:
            return
        contract = Contract.model_validate_json(Path(path).read_text())
        if item not in contract.unresolved:
            contract.unresolved.append(item)
            Path(path).write_text(contract.model_dump_json(indent=1))

    def _step_reference(self, ck: dict) -> dict:
        contract = self._load_contract(ck)
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
        res2 = verify(contract, rp, ref2, cwork / "rtl_vs_r2", self.cfg, run_synth=False)
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
            self.log("[corroborate] could not derive a second reference; accepting on a single reference (low confidence)")
            return ck, ref, True
        ck["consensus"]["references"].append({"path": str(ref2), "role": "alt1"})
        res2 = verify(contract, rp, ref2, cwork / "rtl_vs_alt1", self.cfg, run_synth=False)
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
        res3 = verify(contract, rp, ref3, cwork / "rtl_vs_alt2", self.cfg, run_synth=False)
        self.store.event(self.run_id, "consensus", {"stage": "rtl_vs_alt2", "accepted": res3.accepted, "summary": res3.summary})
        if res3.accepted:
            ck["consensus"]["outcome"] = "rtl_corroborated_2_of_3"
            ck["consensus"]["confidence"] = "medium"
            self.log("[corroborate] RTL matches references 1 and 3 (2 of 3); accepting")
            return ck, ref, True
        cmp23 = compare_references(contract, ref2, ref3, cwork / "r2_vs_r3", self.cfg.verification.seeds, self.cfg.verification.sim_cycles)
        if not cmp23.get("error") and cmp23["mismatches"] == 0:
            ck["consensus"]["outcome"] = "majority_against_rtl"
            self._adopt_reference(ck, ref, ref2)
            self.log("[corroborate] references 2 and 3 agree with each other and disagree with the RTL; adopting reference 2 and repairing the RTL")
            return ck, Path(ck["reference_path"]), False
        ck["consensus"]["outcome"] = "no_majority"
        ck["consensus"]["confidence"] = "low"
        self.log("[corroborate] three references disagree; accepting on the first reference with LOW confidence — contract likely ambiguous")
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

    def _triage_contract(self, ck: dict, contract: Contract) -> Contract:
        """Demote `unresolved` items that answer themselves before the sign-off gate reads the list.

        A question the request already settles, or that does not change the ports, is a default and
        not a question; it moves to `assumptions` with the rule that demoted it, so nothing is lost
        and `reports/outcome.json` records every demotion. See `contracts/triage.py`.
        """
        if not contract.unresolved:
            return contract
        t = triage_unresolved(contract.unresolved)
        if not t.demoted:
            return contract
        contract.unresolved = t.kept
        for v in t.demoted:
            if v.assumption() not in contract.assumptions:
                contract.assumptions.append(v.assumption())
        Path(ck["contract_path"]).write_text(contract.model_dump_json(indent=1))
        ck["unresolved_triage"] = t.records()
        self.store.event(self.run_id, "unresolved_triage",
                         {"demoted": len(t.demoted), "kept": len(t.kept), "rules": sorted({v.rule for v in t.demoted})})
        self.log(f"[triage] {len(t.demoted)} unresolved item(s) answer themselves and became assumptions; "
                 f"{len(t.kept)} left for the user")
        return contract

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

    def _step_properties(self, ck: dict) -> dict:
        """Optional formal layer: a property checker written independently of the RTL. Failure is recorded, not fatal."""
        contract = self._load_contract(ck)
        ck["properties_done"] = True
        if not self.cfg.verification.run_formal or not contract.has_reset:
            # No reset: BMC would start from an unconstrained state, so every reset-value assertion
            # would be a spurious counterexample. The formal layer is optional evidence; skip it.
            if not contract.combinational and not contract.has_reset:
                self.store.event(self.run_id, "properties_skipped", {"reason": "contract has no reset"})
            self.store.checkpoint(self.run_id, "rtl", ck)
            return ck
        ctx = self._ctx(ck, contract)
        vdir = self.ws.dir("verification")
        last_err = ""
        for attempt in range(2):
            user = P.PROPERTIES_USER.format(request=ctx["request"], contract_json=ctx["contract_json"], skeleton=checker_skeleton(contract))
            if last_err:
                user += "\n\nYour previous checker was rejected:\n" + last_err[:1500] + "\nFix it."
            r = self._call("properties", P.PROPERTIES_SYSTEM, user, seed=(self.cfg.model.seed or 0) + attempt, payload="verilog")
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

    def _step_rtl(self, ck: dict) -> dict:
        contract = self._load_contract(ck)
        ctx = self._ctx(ck, contract)
        rtldir = self.ws.dir("rtl")
        for attempt in range(3):
            r = self._call("rtl", P.RTL_SYSTEM, P.RTL_USER.format(**ctx), seed=(self.cfg.model.seed or 0) + attempt, payload="verilog")
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
        rp = Path(ck["rtl_path"])
        ref = Path(ck["reference_path"])
        vdir = self.ws.dir("verification")
        history: list[dict] = ck.get("history", [])
        attempt = int(ck.get("rtl_attempt", 0))
        assert self.budget
        max_iter = self.budget.max_repair_iterations
        signatures: list[str] = [h.get("signature", "") for h in history]
        ref_regenerated = bool(ck.get("reference_regenerated", False))
        while True:
            work = vdir / "attempts" / f"attempt_{attempt}"
            if work.exists():
                shutil.rmtree(work)
            t0 = time.time()
            props = Path(ck["properties_path"]) if ck.get("properties_path") else None
            res = verify(contract, rp, ref, work, self.cfg, props_path=props, request=ck.get("request", ""))
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
                ck = self._check_fsm_table(ck, contract, ref)
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
        r = self._call("repair", P.REPAIR_SYSTEM, user, seed=(self.cfg.model.seed or 0) + attempt, payload="verilog")
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
        if ck.get("request_table_check"):
            return ck
        t0 = time.time()
        res = check_reference_against_request_tables(
            contract, ck.get("request", ""), ref, self.ws.dir("verification") / "request_tables")
        self.tool_time_s += time.time() - t0
        ck["request_table_check"] = res
        if res["status"] == "not_applicable":
            return ck
        self.store.event(self.run_id, "request_table_check", res)
        if res["status"] == "mismatch":
            self.log(f"[tables] the reference contradicts the request's own table on {len(res['mismatches'])} row(s): {res['detail'][:300]}")
        elif res["status"] == "ok":
            self.log(f"[tables] reference agrees with the request's printed table on all {res['rows']} row(s)")
        else:
            self.log(f"[tables] check inconclusive: {res['detail'][:200]}")
        return ck

    def _check_fsm_table(self, ck: dict, contract: Contract, ref: Path) -> dict:
        """Replay the contract's own transition table through the reference. No model call.

        The reference and the RTL are written from the same contract, so they fail the same way and
        simulation cannot tell. This asks one thing simulation cannot: does the reference behave like
        the table the RTL was built from?
        """
        if ck.get("fsm_table_check"):
            return ck
        t0 = time.time()
        res = check_reference_against_fsm(contract, ref, self.ws.dir("verification") / "fsm_table")
        self.tool_time_s += time.time() - t0
        ck["fsm_table_check"] = res
        if res["status"] == "not_applicable":
            return ck
        self.store.event(self.run_id, "fsm_table_check", res)
        if res["status"] == "mismatch":
            self.log(f"[fsm] the reference contradicts the contract's own transition table: {res['detail'][:300]}")
        elif res["status"] == "ok":
            self.log(f"[fsm] reference agrees with the contract's transition table on all {res['checks']} checked output(s) "
                     f"over {res['probes']} directed sequence(s)")
        else:
            self.log(f"[fsm] check inconclusive: {res['detail'][:200]}")
        return ck

    def _step_report(self, ck: dict, final_state: str, reason: str = "") -> tuple[dict, dict]:
        assert self.budget
        if self.escalations:
            ck["model_escalations"] = self.escalations
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
            "kind": {"type": "string", "enum": ["port_timing", "port_width", "parameter", "behavior", "requirement"]},
            "target": {"type": "string"}, "value": {"type": "string"}, "reason": {"type": "string"}},
            "required": ["kind", "target", "value", "reason"]}},
        "unresolved": {"type": "array", "items": {"type": "string"}},
        "uncovered": {"type": "array", "items": {"type": "string"}},
        "notes": {"type": "string"},
    },
    "required": ["verdict", "corrections", "unresolved", "uncovered", "notes"],
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
        data["behavior"] = data["behavior"].rstrip() + "\n\nReviewer clarification: " + value
        return True, "behavior clarified"
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


def _drop_invented_reset(data: dict, request: str) -> list[str]:
    """Remove a reset the request's interface list does not contain, in place. Returns what changed.

    ADR 0016 L2: intake on `Prob117_circuit9` wrote `clock_reset.reset = "null"` and then a reset port
    that is not in the request, the contract failed validation three times, and the run ended with no
    RTL at all. The request's port list settles it deterministically, so the run is not spent on it.
    """
    ports = parse_interface(request)
    if not ports:
        return []
    allowed = {p.name for p in ports}
    cr = data.get("clock_reset")
    if not isinstance(cr, dict):
        return []
    rst = cr.get("reset")
    if not isinstance(rst, str) or not rst.strip() or rst in allowed:
        return []
    cr["reset"] = None
    declared = [p for p in (data.get("ports") or []) if isinstance(p, dict)]
    data["ports"] = [p for p in declared if p.get("name") != rst]
    return [f"the request's interface list has no reset port; dropped the invented reset `{rst}` "
            f"and set clock_reset.reset to null"]


_FSM_WORD_RE = re.compile(
    r"\b(?:state\s+machine|state-machine|finite[\s-]state\s+machine|fsm|moore|mealy"
    r"|state\s+diagram|state[\s-]assigned\s+table|state\s+transition\s+table)\b", re.I)
# a drawn transition: "B (out=1) --in=0--> A"
_FSM_ARROW_RE = re.compile(r"^\s*\S+.*-+\s*\S*\s*-+>\s*\S+", re.M)
# the header of a state-assigned table: "Present state y[2:0] | Next state ..."
_FSM_TABLE_RE = re.compile(r"\bpresent\s+state\b", re.I)
_FSM_NAMED_STATES_RE = re.compile(r"\bstates?\b[^.\n]{0,60}\b(?:called|named|labelled|labeled)\b", re.I)


def request_requires_fsm(request: str) -> str:
    """Why the request needs the contract's `fsm` section, or "" when it does not.

    Deterministic, because the model does not decide it reliably: with the section merely optional
    every one of the 2,412 contracts of `evals/results/final-2026-09-14` left `fsm` null, so the
    FSM table check never ran once. A request only counts as a state machine when it says so (state
    machine / FSM / Moore / Mealy / state diagram), draws transitions, prints a state-assigned
    table, or names its states. The bare words "state"/"states" are deliberately NOT a signal: that
    is the counter and datapath exclusion the intake prompt states, where the state is a number
    (`Prob144_conwaylife` says "the current state of the game" and has no state machine).
    """
    if _FSM_WORD_RE.search(request):
        return "it describes a state machine (state machine / FSM / Moore / Mealy / state diagram)"
    if _FSM_ARROW_RE.search(request):
        return "it draws a state transition diagram"
    if _FSM_TABLE_RE.search(request):
        return "it prints a state-assigned transition table"
    if _FSM_NAMED_STATES_RE.search(request):
        return "it names the states of the machine"
    return ""


def _lock_module_name(data: dict, request: str) -> list[str]:
    """Rename the contract's module to the name the request asks for, in place. Returns what changed.

    A rename is mechanical and never a judgement, so it is coerced rather than rejected: the request
    names the module, everything downstream (the RTL file, the testbench instantiation, the eval's
    `rtl/TopModule.v`) is written from the contract, and a contract that renames `TopModule` to
    `top_module` delivers work nobody can find.
    """
    want = requested_module_name(request)
    if not want:
        return []
    have = data.get("module_name")
    if not isinstance(have, str) or have == want:
        return []
    data["module_name"] = want
    return [f"the request asks for a module named `{want}`; renamed the contract's module from `{have}`"]


def _signature(res: VerificationResult) -> str:
    if res.guard_findings:
        return "guard:" + ",".join(f.get("code", "") for f in res.guard_findings)
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
    if res.waveform and res.waveform.get("status") == "fail":
        return "wave:" + ";".join(f"{m['time']}/{m['port']}" for m in res.waveform.get("mismatches", [])[:3])
    if res.synth and not res.synth.get("ok"):
        return "synth:" + (res.synth.get("tail", "")[-80:])
    return ""
