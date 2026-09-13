"""Natural-language composition using ordinary leaf runs and an isolated top reference.

The assembled RTL is fixed during integration. A mismatch is delivered as a
failure; it cannot be 'repaired' by replacing the system with a monolithic design.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..config import Config
from ..contracts.schema import Contract
from ..contracts.system import Connection, Instance, SystemContract, render_top
from ..models.adapter import ModelAdapter, extract_json
from ..verification.harness import sha256_file
from .run import Budget, BudgetExhausted, Runner, Stalled
from .workspace import Workspace


PLAN_SYSTEM = """Decompose the requested hardware system into 2 to 4 useful leaves.
Return JSON: {"modules":[{"name":"instance_name", "request":"complete leaf build request",
"open_outputs":[]}], "connections":[{"from_module":"TOP", "from_port":"port",
"to_module":"instance_name", "to_port":"port", "width":8}]}.
Each request must name the leaf module and every port, direction, exact width,
signedness, and complete behavior. For combinational leaves explicitly say no
clock/reset/state. For sequential leaves state clock/reset names, reset kind and
polarity, priority, hold behavior and output timing. Use fixed widths, no parameters
in this initial workflow. Existing intake will generate each leaf contract; do not
return contracts, RTL or reference code. Use the supplied top contract's exact
external ports. TOP means top inputs as sources and top outputs as sinks. Every
leaf input needs exactly one driver; every output must be connected or explicitly
open. All sequential leaves share the top clock/reset directly. No combinational
cycles. Each leaf must perform a meaningful part of the requested behavior."""


class LeafPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    request: str = Field(min_length=150)
    open_outputs: list[str] = Field(default_factory=list)


class DecompositionPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    modules: list[LeafPlan] = Field(min_length=2, max_length=4)
    connections: list[Connection]

    @model_validator(mode="after")
    def endpoints(self):
        names = [m.name for m in self.modules]
        if len(names) != len(set(names)) or "TOP" in names:
            raise ValueError("instance names must be unique and not TOP")
        for c in self.connections:
            if c.from_module not in names + ["TOP"] or c.to_module not in names + ["TOP"]:
                raise ValueError("connection names an unknown instance; use uppercase TOP for the boundary")
        return self

    def validate_boundary(self, top: Contract) -> None:
        """Reject impossible external wiring before running expensive leaf builds."""
        ports = {p.name: p for p in top.ports}
        driven = set()
        for connection in self.connections:
            for module, name, direction in (
                (connection.from_module, connection.from_port, "input"),
                (connection.to_module, connection.to_port, "output"),
            ):
                if module != "TOP":
                    continue
                port = ports.get(name)
                if port is None or port.direction != direction:
                    raise ValueError(f"TOP.{name} is not a declared top {direction}; "
                                     "keep internal state inside leaves or mark unused leaf outputs open")
                if connection.width != port.width:
                    raise ValueError(f"TOP.{name} requires width {port.width}")
                if direction == "output":
                    if name in driven:
                        raise ValueError(f"TOP.{name} has multiple drivers")
                    driven.add(name)
        missing = {p.name for p in top.ports if p.direction == "output"} - driven
        if missing:
            raise ValueError(f"top outputs without drivers: {sorted(missing)}")


class AssemblyRunner(Runner):
    """Existing verification/corroboration pipeline with immutable assembled RTL."""

    def __init__(self, *args, assembled: str, **kwargs):
        super().__init__(*args, **kwargs)
        self.assembled = assembled
        self.reference_calls = 0

    def _call(self, role, system, user, *args, **kwargs):
        if role == "reference":
            path = self.ws.dir("reference") / f"prompt-{self.reference_calls}.json"
            path.write_text(json.dumps({"system": system, "user": user}, indent=2))
            self.reference_calls += 1
        return super()._call(role, system, user, *args, **kwargs)

    def _step_rtl(self, ck):
        contract = self._load_contract(ck)
        path = self.ws.dir("rtl") / f"{contract.module_name}.v"
        path.write_text(self.assembled)
        self._save("rtl_assembly", path, "rtl")
        ck.update(rtl_path=str(path), rtl_attempt=0, history=[])
        self.store.checkpoint(self.run_id, "verify", ck)
        return ck

    def _repair(self, *args, **kwargs):
        raise Stalled("integration failed; assembled wiring and leaf RTL are preserved for diagnosis")


def _seed_contract(runner: Runner, contract: Contract, request: str, budget: float, review: bool) -> None:
    runner.start(request, budget_s=budget)
    path = runner.ws.dir("spec") / f"contract.v{contract.version}.json"
    path.write_text(contract.model_dump_json(indent=2))
    runner._save("contract", path, "composition")
    runner.store.checkpoint(runner.run_id, "review" if review else "reference", {
        "request": request, "contract_path": str(path), "contract_version": contract.version,
    })


def shared_control_connections(top: Contract, instances: list[Instance],
                               connections: list[Connection]) -> list[Connection]:
    """Complete mandatory shared controls; never replace an explicit driver."""
    if top.clock_reset is None:
        return []
    occupied = {c.target for c in connections}
    additions = []
    for instance in instances:
        controls = instance.contract.clock_reset
        if controls is None:
            continue
        for source, target in ((top.clock_reset.clock, controls.clock),
                               (top.clock_reset.reset, controls.reset)):
            if source and target and (instance.name, target) not in occupied:
                additions.append(Connection(from_module="TOP", from_port=source,
                                            to_module=instance.name, to_port=target, width=1))
                occupied.add((instance.name, target))
    return additions


def compose(project: Path, request: str, cfg: Config, budget_s: float, log=print) -> dict:
    """Build a fresh system workspace; retain failures and all leaf workspaces."""
    project = project.resolve()
    project.mkdir(parents=True, exist_ok=False)
    (project / "request.md").write_text(request)
    started = time.monotonic()
    adapter = ModelAdapter(cfg.model)
    adapters = [adapter]
    result = {"accepted": False, "state": "planning", "leaves": {}, "integration": None,
              "request": str(project / "request.md"), "model": cfg.model.model,
              "model_revision": cfg.model.revision, "reason": ""}

    def save():
        result["elapsed_s"] = round(time.monotonic() - started, 2)
        result["primary_model_calls"] = sum(a.usage.calls for a in adapters)
        result["primary_model_tokens"] = sum(a.usage.total_tokens for a in adapters)
        (project / "outcome.json").write_text(json.dumps(result, indent=2))

    def remaining():
        seconds = budget_s - (time.monotonic() - started)
        if seconds <= 0:
            raise BudgetExhausted("system wall-time budget exhausted")
        return seconds

    def stage_config():
        stage = cfg.model_copy(deep=True)
        stage.budget.max_model_calls -= sum(a.usage.calls for a in adapters)
        stage.budget.max_total_tokens -= sum(a.usage.total_tokens for a in adapters)
        if stage.budget.max_model_calls <= 0 or stage.budget.max_total_tokens <= 0:
            raise BudgetExhausted("system primary-model call/token budget exhausted")
        return stage

    try:
        plan_ws = Workspace(project / "plan")
        plan_ws.init(request=request)
        planner = Runner(plan_ws, cfg, adapter=adapter, log=log)
        planner.start(request, budget_s=remaining())
        planner.budget = Budget(remaining(), cfg.budget.max_model_calls,
                                cfg.budget.max_total_tokens, cfg.budget.max_repair_iterations)
        top_ck = planner._step_intake({"request": request})
        top_ck = planner._step_review(top_ck)
        top = planner._load_contract(top_ck)
        if top.parameters:
            raise ValueError("composition currently requires fixed top widths and no top parameters")
        (project / "top.json").write_text(top.model_dump_json(indent=2))
        errors = ""
        plan = None
        for attempt in range(3):
            response = planner._call("decomposition", PLAN_SYSTEM,
                                     request + "\nTop contract:\n" + top.model_dump_json(indent=1) + errors,
                                     json_schema=DecompositionPlan.model_json_schema(),
                                     seed=(cfg.model.seed or 0) + attempt)
            (project / f"plan-attempt-{attempt}.txt").write_text(response.text)
            data = extract_json(response.text) if response.ok else None
            try:
                if not isinstance(data, dict):
                    raise ValueError("model did not return a decomposition JSON object")
                instance_names = {m["name"] for m in data.get("modules", [])}
                for connection in data.get("connections", []):
                    for field in ("from_module", "to_module"):
                        if connection.get(field) == "top" and "top" not in instance_names:
                            connection[field] = "TOP"
                plan = DecompositionPlan.model_validate(data)
                plan.validate_boundary(top)
                break
            except (ValueError, KeyError, TypeError) as exc:
                plan = None
                errors = "\nPrevious plan failed structural validation. Fix it:\n" + str(exc)[:3000]
                log(errors)
        if plan is None:
            raise RuntimeError("could not produce a valid decomposition in three attempts")
        planner.store.set_state(planner.run_id, "completed")
        (project / "decomposition.json").write_text(plan.model_dump_json(indent=2))
        result["state"] = "building_leaves"
        save()
        instances = []
        definitions = {}
        for index, leaf_plan in enumerate(plan.modules):
            ws = Workspace(project / "leaves" / leaf_plan.name)
            leaf_request = leaf_plan.request
            ws.init(request=leaf_request)
            stage = stage_config()
            leaf_adapter = ModelAdapter(stage.model)
            adapters.append(leaf_adapter)
            runner = Runner(ws, stage, adapter=leaf_adapter, log=log)
            allocation = remaining() / (len(plan.modules) - index + 1)
            runner.start(leaf_request, budget_s=allocation)
            outcome = runner.execute()
            result["leaves"][leaf_plan.name] = outcome
            save()
            actual = Contract.model_validate_json(Path(outcome["artifacts"]["contract"]).read_text())
            instance = Instance(name=leaf_plan.name, contract=actual, version=actual.version,
                                digest=actual.digest(), open_outputs=leaf_plan.open_outputs)
            instances.append(instance)
            if not outcome.get("accepted") or outcome.get("provisional") or actual.unresolved or actual.unsupported:
                raise Stalled(f"leaf {instance.name} is not unconditionally accepted; system sign-off withheld")
            rtl = Path(outcome["artifacts"]["rtl"])
            if sha256_file(rtl) != outcome["artifacts"]["rtl_sha256"]:
                raise Stalled(f"leaf {instance.name} changed after verification")
            code = rtl.read_text()
            module = actual.module_name
            if module in definitions and definitions[module] != code:
                raise Stalled(f"independently generated instances disagree on shared module {module}")
            definitions[module] = code
        added_controls = shared_control_connections(top, instances, plan.connections)
        (project / "inferred-connections.json").write_text(json.dumps({
            "reason": "mandatory direct clock/reset wiring in the shared-control composition scope",
            "connections": [c.model_dump(mode="json") for c in added_controls],
        }, indent=2))
        system = SystemContract(top=top, modules=instances, connections=plan.connections + added_controls,
                                integration_requirements=[r.id for r in top.requirements])
        (project / "system.json").write_text(system.model_dump_json(indent=2))
        # Preserve authoritative user wording alongside the top contract. Never
        # substitute a derived summary or include generated leaf artifacts.
        top_request = request
        (project / "integration-context.json").write_text(json.dumps({
            "request": top_request, "contract": system.top.model_dump(mode="json"),
            "source": "original user request and top contract; no generated leaf artifacts supplied",
        }, indent=2))
        ws = Workspace(project / "integration")
        ws.init(request=top_request)
        assembled = render_top(system) + "\n".join(definitions.values())
        stage = stage_config()
        top_adapter = ModelAdapter(stage.model)
        adapters.append(top_adapter)
        runner = AssemblyRunner(ws, stage, adapter=top_adapter, log=log, assembled=assembled)
        _seed_contract(runner, system.top, top_request, remaining(), review=False)
        result["state"] = "verifying_integration"
        save()
        outcome = runner.execute()
        result["integration"] = outcome
        result["unresolved"] = system.unresolved_items()
        result["accepted"] = bool(outcome.get("accepted") and not outcome.get("provisional")
                                  and not system.unresolved_items() and not system.top.unsupported
                                  and outcome.get("contract_digest") == system.top.digest())
        result["state"] = "completed"
        result["reason"] = "" if result["accepted"] else "integration not unconditionally accepted"
        result["scope"] = "model-derived integration evidence; independent held-out M4 gate not established"
    except Exception as exc:
        result["state"] = "budget_exhausted" if isinstance(exc, BudgetExhausted) else "failed"
        result["reason"] = f"{type(exc).__name__}: {exc}"
        log(result["reason"])
    finally:
        save()
    return result
