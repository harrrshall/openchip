"""Design contract: the versioned, machine-readable statement of what must be built.

The contract is produced from the user's request by the model (intake role), validated here
as untrusted input, and then treated as the authority for reference behavior, RTL, and
verification. The RTL generator may not change it; a revision is an explicit new version.
"""
from __future__ import annotations

import hashlib
import json
import re
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class Direction(str, Enum):
    input = "input"
    output = "output"


class Port(BaseModel):
    name: str
    direction: Direction
    width: int = Field(ge=1, le=4096, description="Numeric bit width at the DEFAULT parameter values, e.g. 4 for a `[WIDTH-1:0]` port with WIDTH=4. Never 1 for a multi-bit bus.")
    width_expr: Optional[str] = Field(
        default=None,
        description="REQUIRED for any port whose width depends on a parameter: Verilog width expression such as 'WIDTH' or 'clog2(DEPTH)+1'. "
        "`width` must equal this expression evaluated at default parameters.",
    )
    signed: bool = False
    description: str = ""
    role: Literal["clock", "reset", "data", "control", "status", "handshake"] = "data"
    timing: Literal["registered", "combinational", "n/a"] = Field(
        description="REQUIRED. For OUTPUT ports: 'registered' = driven by a flip-flop, changes only at the clock edge, never depends on same-cycle inputs; "
        "'combinational' = a function of the current inputs (and state) with no clock delay. For INPUT ports use 'n/a'.")

    @field_validator("name")
    @classmethod
    def _ident(cls, v: str) -> str:
        if not IDENT.match(v):
            raise ValueError(f"port name {v!r} is not a valid identifier")
        return v


class Parameter(BaseModel):
    name: str
    default: int
    description: str = ""
    min: Optional[int] = None
    max: Optional[int] = None

    @field_validator("name")
    @classmethod
    def _ident(cls, v: str) -> str:
        if not IDENT.match(v):
            raise ValueError(f"parameter name {v!r} is not a valid identifier")
        return v


class ClockReset(BaseModel):
    clock: str = "clk"
    clock_edge: Literal["posedge"] = "posedge"
    reset: Optional[str] = Field(
        default="rst",
        description="Reset port name, or null when the design has NO reset. A null reset means the state powers up at its "
        "documented initial values and is never forced back to them; never invent a reset the request does not describe.",
    )
    reset_active: Literal["high", "low"] = "high"
    reset_kind: Literal["synchronous", "asynchronous"] = "synchronous"
    reset_description: str = "All state returns to its documented initial value."

    @model_validator(mode="before")
    @classmethod
    def _drop_nulls(cls, data):
        """A model that writes `"reset": null` writes null for the rest of the group too. Only `reset`
        carries meaning as null (no reset); the others fall back to their documented defaults."""
        if isinstance(data, dict):
            return {k: v for k, v in data.items() if v is not None or k == "reset"}
        return data

    @field_validator("reset", mode="before")
    @classmethod
    def _optional_reset(cls, v):
        """`null`, and the strings models write in place of it, all mean "no reset"."""
        if v is None:
            return None
        if isinstance(v, str) and v.strip().lower() in ("", "null", "none", "n/a", "na", "nil", "no reset"):
            return None
        return v

    @property
    def has_reset(self) -> bool:
        return bool(self.reset)


class Source(str, Enum):
    user_text = "user_text"
    document = "document"
    inference = "inference"
    default = "default"
    protocol = "protocol"


class Disposition(str, Enum):
    tested = "tested"
    formal = "formal"
    reviewed = "reviewed"
    unsupported = "unsupported"
    unresolved = "unresolved"


class Requirement(BaseModel):
    id: str = Field(pattern=r"^R\d{3}$")
    text: str = Field(min_length=12, description="One testable statement of externally visible behavior.")
    source: Source
    source_detail: str = Field(default="", description="Quote or location supporting the requirement.")
    disposition: Disposition = Disposition.unresolved
    verification_plan: str = Field(default="", description="How this requirement will be checked.")


# -- explicit, checkable sections --------------------------------------------------------------
# Prose is read the same wrong way twice: the reference model and the RTL are both written from the
# contract, so a misread sentence produces a reference and an RTL that agree and are both wrong
# (docs/research/false-acceptance-analysis.md §5). These sections state the same facts as data that
# a machine can replay against the reference, so a disagreement becomes visible.


class FsmState(BaseModel):
    name: str = Field(description="State name as used in the transition table.")
    meaning: str = Field(default="", description="ONE SHORT LINE: what has been seen, or what the machine is doing, in this state.")

    @field_validator("name")
    @classmethod
    def _ident(cls, v: str) -> str:
        if not IDENT.match(v):
            raise ValueError(f"state name {v!r} is not a valid identifier")
        return v


class OutputStyle(BaseModel):
    """Moore or Mealy, per output, stated rather than implied."""

    output: str = Field(description="Output port name.")
    style: Literal["moore", "mealy"] = Field(
        description="'moore': the value depends only on the current state (the same in every row for that state). "
        "'mealy': it also depends on the current inputs, so it may differ per transition row.")
    note: str = Field(default="", description="Optional: the request wording that decides it.")


class FsmTransition(BaseModel):
    """One row of the transition table: the specification, in preference to the prose."""

    state: str = Field(description="State the machine is IN during this cycle.")
    condition: str = Field(
        description="Boolean expression over the data input ports that selects this row, e.g. \"x == 1\", "
        "\"start && !busy\", \"in == 0\". Use \"default\" for 'any input not matched by the other rows of this state'. "
        "Verilog operators only (==, !=, <, >, &&, ||, !, bit selects); no prose.")
    next_state: str = Field(description="State entered at the NEXT clock edge.")
    outputs: dict[str, str] = Field(
        default_factory=dict,
        description="Value of each output DURING this cycle, i.e. while the machine is in `state` and `condition` holds "
        "(NOT the value after the edge). Constants ('0', '1') or, for a Mealy output, an expression over the inputs. "
        "A Moore output must carry the same value in every row with the same `state`.")
    note: str = Field(
        default="",
        description="Optional. Use it ONLY to record that the request really does specify that an input is ignored in "
        "this state, e.g. 'the request says the machine waits one cycle here regardless of w'. A state that never "
        "tests an input the rest of the table tests is rejected unless it carries such a note.")


class FsmErrorRecovery(BaseModel):
    """What a protocol violation does. Left to prose, this is where references and RTL diverge."""

    violation: str = Field(description="The violation, e.g. 'stop bit is 0 when the stop bit is expected'.")
    state: str = Field(description="State entered on the violation.")
    outputs: str = Field(default="", description="What the outputs do while recovering, and explicitly which ones do NOT assert.")
    resumes: str = Field(default="", description="What ends the recovery and which state is entered then.")


class Fsm(BaseModel):
    """Explicit state machine. Filled whenever the request describes states, sequences or framing."""

    reset_state: str = Field(description="State entered by reset (or the power-up state when there is no reset).")
    states: list[FsmState]
    output_style: list[OutputStyle] = Field(default_factory=list, description="One entry per output of the machine.")
    transitions: list[FsmTransition] = Field(description="Every (state, condition) pair, covering every input case of every state.")
    error_recovery: list[FsmErrorRecovery] = Field(default_factory=list)

    @model_validator(mode="after")
    def _consistent(self) -> "Fsm":
        names = [s.name for s in self.states]
        if len(names) != len(set(names)):
            raise ValueError("duplicate FSM state names")
        known = set(names)
        if not known:
            raise ValueError("fsm.states is empty")
        if self.reset_state not in known:
            raise ValueError(f"fsm.reset_state {self.reset_state!r} is not one of the declared states")
        for t in self.transitions:
            if t.state not in known:
                raise ValueError(f"transition from undeclared state {t.state!r}")
            if t.next_state not in known:
                raise ValueError(f"transition to undeclared state {t.next_state!r}")
        for e in self.error_recovery:
            if e.state not in known:
                raise ValueError(f"error_recovery names undeclared state {e.state!r}")
        return self

    def transitions_from(self, state: str) -> list[FsmTransition]:
        return [t for t in self.transitions if t.state == state]

    def style_of(self, output: str) -> str:
        for o in self.output_style:
            if o.output == output:
                return o.style
        return ""

    def table_md(self) -> str:
        rows = ["| State | Condition | Next state | Outputs this cycle |", "|---|---|---|---|"]
        for t in self.transitions:
            outs = ", ".join(f"{k}={v}" for k, v in t.outputs.items()) or "-"
            note = f" ({t.note})" if t.note else ""
            rows.append(f"| `{t.state}` | `{t.condition}` | `{t.next_state}` | {outs}{note} |")
        return "\n".join(rows)


class UpdateRule(BaseModel):
    """Ordered priority for one piece of state: which event wins when two apply in the same cycle."""

    state_element: str = Field(description="The register or memory updated, e.g. 'count', 'bhr', 'pht[index]'.")
    priority: list[str] = Field(
        description="Ordered, highest priority FIRST. Each entry names the event and what it does, e.g. "
        "'load: q <= d', 'enable: q <= q + 1', 'otherwise: q holds'. Events not listed do not change this state.")
    note: str = Field(default="", description="Optional: which request sentence decides the order.")


class OutputTiming(BaseModel):
    output: str
    timing: Literal["registered", "combinational"]
    when: str = Field(default="", description="One short line: when the value changes, e.g. 'at the edge that leaves DONE', 'immediately with the inputs'.")


class TimingConventions(BaseModel):
    """The conventions that a reference and an RTL otherwise assume differently."""

    default_output_style: str = Field(
        default="",
        description="State the default explicitly, e.g. 'outputs are Moore and registered unless the request says otherwise'. "
        "The reference model and the RTL must both follow exactly this sentence.")
    outputs: list[OutputTiming] = Field(default_factory=list, description="One entry per output: registered or combinational.")
    cascaded_carries: Literal["combinational", "registered", "not_applicable"] = Field(
        default="not_applicable",
        description="For cascaded counters (seconds->minutes->hours, digit chains): 'combinational' means the carry into the "
        "next stage is a function of the current stage value in the SAME cycle (no lag); 'registered' adds one cycle of lag per stage.")
    window_start: str = Field(
        default="",
        description="For windowed / framed / fixed-length sequence designs: which cycle starts a window and which cycle is counted first. One short line; empty when there is no window.")
    notes: str = Field(default="")


class Contract(BaseModel):
    """Versioned design contract. `version` starts at 1; revisions must preserve `parent_version`."""

    schema_version: Literal[1] = 1
    version: int = 1
    parent_version: Optional[int] = None
    revision_reason: str = ""
    revision_authority: Literal["user", "agent_default", "agent_inference"] = "agent_inference"

    module_name: str
    purpose: str
    language: Literal["verilog-2001", "systemverilog-2012"] = "verilog-2001"
    parameters: list[Parameter] = Field(default_factory=list)
    ports: list[Port]
    clock_reset: Optional[ClockReset] = Field(default_factory=ClockReset, description="null for a purely combinational design (no clock, no reset, no state).")
    behavior: str = Field(min_length=150, description="Cycle-level description of the behavior, precise enough to implement: what happens at each clock edge, which outputs are registered vs combinational, reset values, boundary/overflow behavior. Several sentences.")
    timing: str = Field(default="", description="Latency, throughput, and handshake semantics.")
    arithmetic: str = Field(default="", description="Width, signedness, overflow, rounding, saturation policy.")
    fsm: Optional[Fsm] = Field(
        default=None,
        description="REQUIRED when the design has states (a state machine, a framing/protocol receiver, a sequence or "
        "pattern detector, a multi-cycle window). The transition table is the specification; null only for a design with no states.")
    update_rules: list[UpdateRule] = Field(
        default_factory=list,
        description="REQUIRED when two control inputs or events can apply to the same state in the same cycle "
        "(load vs enable, clear vs everything, predict vs train). One entry per piece of state, priorities ordered.")
    timing_conventions: Optional[TimingConventions] = Field(
        default=None,
        description="REQUIRED for any clocked design: registered vs combinational per output, the default output style "
        "stated in words, carry style for cascaded counters, and which cycle starts a window.")
    requirements: list[Requirement]
    assumptions: list[str] = Field(default_factory=list)
    defaults: list[str] = Field(default_factory=list, description="Routine implementation choices taken by default that the request did not state (e.g. 'reset is synchronous active-high'). Not a list of ports.")
    unresolved: list[str] = Field(default_factory=list, description="Questions the user should answer.")
    unsupported: list[str] = Field(default_factory=list)
    target: str = Field(default="generic", description="Target technology or FPGA family, if any.")

    @field_validator("module_name")
    @classmethod
    def _ident(cls, v: str) -> str:
        if not IDENT.match(v):
            raise ValueError(f"module_name {v!r} is not a valid identifier")
        return v

    @model_validator(mode="after")
    def _consistency(self) -> "Contract":
        names = [p.name for p in self.ports]
        if len(names) != len(set(names)):
            raise ValueError("duplicate port names")
        pnames = {p.name for p in self.parameters}
        if pnames & set(names):
            raise ValueError("a parameter and a port share a name")
        cr = self.clock_reset
        if cr is not None:
            if cr.clock not in names:
                raise ValueError(f"clock port {cr.clock!r} is not declared")
            if cr.reset is not None and cr.reset not in names:
                raise ValueError(f"reset port {cr.reset!r} is not declared (set clock_reset.reset to null if the design has no reset)")
            for p in self.ports:
                if p.name == cr.clock and (p.direction != Direction.input or p.width != 1):
                    raise ValueError("clock must be a 1-bit input")
                if p.name == cr.reset and (p.direction != Direction.input or p.width != 1):
                    raise ValueError("reset must be a 1-bit input")
        if not self.requirements:
            raise ValueError("at least one requirement is required")
        ids = [r.id for r in self.requirements]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate requirement ids")
        if self.version > 1 and self.parent_version is None:
            raise ValueError("revisions must record parent_version")
        for p in self.ports:
            if p.direction == Direction.output and p.timing == "n/a":
                raise ValueError(f"output {p.name}: timing must be 'registered' or 'combinational'")
            if self.clock_reset is None and p.direction == Direction.output and p.timing == "registered":
                raise ValueError(f"output {p.name}: a combinational contract (no clock) cannot have registered outputs")
        for p in self.ports:
            if p.width_expr:
                try:
                    val = eval_width(p.width_expr, {q.name: q.default for q in self.parameters})
                except Exception as e:  # noqa: BLE001
                    raise ValueError(f"port {p.name}: cannot evaluate width_expr {p.width_expr!r}: {e}")
                if val != p.width:
                    raise ValueError(
                        f"port {p.name}: width {p.width} != width_expr {p.width_expr!r} = {val} at defaults"
                    )
        return self

    # -- helpers -------------------------------------------------------------------------
    def inputs(self) -> list[Port]:
        return [p for p in self.ports if p.direction == Direction.input]

    def outputs(self) -> list[Port]:
        return [p for p in self.ports if p.direction == Direction.output]

    def data_inputs(self) -> list[Port]:
        cr = self.clock_reset
        if cr is None:
            return self.inputs()
        return [p for p in self.inputs() if p.name not in (cr.clock, cr.reset)]

    @property
    def combinational(self) -> bool:
        return self.clock_reset is None

    @property
    def has_reset(self) -> bool:
        """False for a combinational contract and for a clocked design with no reset port."""
        return self.clock_reset is not None and bool(self.clock_reset.reset)

    def registered_outputs(self) -> list[Port]:
        if self.combinational:
            return []
        return [p for p in self.outputs() if p.timing == "registered"]

    def param_defaults(self) -> dict[str, int]:
        return {p.name: p.default for p in self.parameters}

    def digest(self) -> str:
        payload = self.model_dump(mode="json")
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]

    def port_table_md(self) -> str:
        rows = ["| Port | Dir | Width | Role | Timing | Description |", "|---|---|---|---|---|---|"]
        for p in self.ports:
            w = p.width_expr or str(p.width)
            timing = (p.timing if p.direction == Direction.output else "-") if not self.combinational else ("combinational" if p.direction == Direction.output else "-")
            rows.append(f"| `{p.name}` | {p.direction.value} | {w}{' (signed)' if p.signed else ''} | {p.role} | {timing} | {p.description} |")
        return "\n".join(rows)

    def summary_md(self) -> str:
        """Human-readable contract summary for review."""
        out = [f"# Design contract v{self.version}: `{self.module_name}`", "", self.purpose, ""]
        if self.parent_version:
            out += [f"_Revision of v{self.parent_version} ({self.revision_authority}): {self.revision_reason}_", ""]
        out += ["## Interface", "", self.port_table_md(), ""]
        if self.parameters:
            out += ["### Parameters", ""] + [f"- `{p.name}` = {p.default}: {p.description}" for p in self.parameters] + [""]
        cr = self.clock_reset
        out += ["## Clock and reset", ""]
        if cr is None:
            out += ["- Purely combinational: no clock, no reset, no internal state.", ""]
        elif cr.reset is None:
            out += [f"- Clock `{cr.clock}`, {cr.clock_edge}. **No reset port**: the module has no reset input.",
                    "- State powers up at its documented initial values and is never forced back to them; do not add a reset port.", ""]
        else:
            out += [f"- Clock `{cr.clock}`, {cr.clock_edge}. Reset `{cr.reset}`, active-{cr.reset_active}, {cr.reset_kind}.", f"- {cr.reset_description}", ""]
        out += [
            "## Behavior",
            "",
            self.behavior,
            "",
        ]
        if self.timing:
            out += ["## Timing", "", self.timing, ""]
        if self.timing_conventions:
            tc = self.timing_conventions
            out += ["## Timing conventions (binding on both the reference model and the RTL)", ""]
            if tc.default_output_style:
                out += [f"- Default: {tc.default_output_style}"]
            out += [f"- `{o.output}`: {o.timing}" + (f" ({o.when})" if o.when else "") for o in tc.outputs]
            if tc.cascaded_carries != "not_applicable":
                out += [f"- Cascaded counter carries: {tc.cascaded_carries}"]
            if tc.window_start:
                out += [f"- Window/frame start: {tc.window_start}"]
            if tc.notes:
                out += [f"- {tc.notes}"]
            out += [""]
        if self.fsm:
            f = self.fsm
            out += ["## State machine (the table is the specification; the prose above is secondary)", "",
                    f"Reset state: `{f.reset_state}`.", ""]
            out += [f"- `{s.name}`: {s.meaning}" for s in f.states] + [""]
            if f.output_style:
                out += ["Output style: " + ", ".join(f"`{o.output}` is {o.style}" for o in f.output_style), ""]
            out += [f.table_md(), ""]
            if f.error_recovery:
                out += ["### Error recovery", ""]
                out += [f"- {e.violation}: enter `{e.state}`; outputs: {e.outputs or 'unchanged'}"
                        + (f"; resumes: {e.resumes}" if e.resumes else "") for e in f.error_recovery] + [""]
        if self.update_rules:
            out += ["## State update rules (priority order, highest first)", ""]
            for u in self.update_rules:
                out += [f"- `{u.state_element}`: " + " > ".join(u.priority) + (f" ({u.note})" if u.note else "")]
            out += [""]
        if self.arithmetic:
            out += ["## Arithmetic policy", "", self.arithmetic, ""]
        out += ["## Requirements", "", "| ID | Requirement | Source | Disposition |", "|---|---|---|---|"]
        out += [f"| {r.id} | {r.text} | {r.source.value} | {r.disposition.value} |" for r in self.requirements]
        out.append("")
        for title, items in (
            ("Explicit assumptions", self.assumptions),
            ("Defaults taken", self.defaults),
            ("Unresolved questions (need the user)", self.unresolved),
            ("Unsupported", self.unsupported),
        ):
            if items:
                out += [f"## {title}", ""] + [f"- {i}" for i in items] + [""]
        return "\n".join(out)


def eval_width(expr: str, params: dict[str, int]) -> int:
    """Evaluate a restricted integer expression over parameters (no builtins)."""
    import ast

    tree = ast.parse(expr, mode="eval")
    allowed = (ast.Expression, ast.BinOp, ast.UnaryOp, ast.Constant, ast.Name, ast.Add, ast.Sub,
               ast.Mult, ast.FloorDiv, ast.Div, ast.Mod, ast.Pow, ast.LShift, ast.RShift, ast.USub, ast.UAdd,
               ast.Call, ast.Load)
    for node in ast.walk(tree):
        if not isinstance(node, allowed):
            raise ValueError(f"disallowed syntax in width expression: {type(node).__name__}")
        if isinstance(node, ast.Call):
            if not (isinstance(node.func, ast.Name) and node.func.id in ("clog2", "max", "min")):
                raise ValueError("only clog2/max/min calls are allowed")
        if isinstance(node, ast.Name) and node.id not in params and node.id not in ("clog2", "max", "min"):
            raise ValueError(f"unknown parameter {node.id!r}")

    def clog2(n: int) -> int:
        return max(0, (int(n) - 1).bit_length())

    val = eval(compile(tree, "<width>", "eval"), {"__builtins__": {}}, {**params, "clog2": clog2, "max": max, "min": min})
    return int(val)


#: Sections the model must decide explicitly instead of silently leaving at their default.
#: Under guided decoding (`response_format: json_schema`) a key that is not in `required` is simply
#: never emitted: every one of the 2,412 contracts of `evals/results/final-2026-09-14` left `fsm`,
#: `update_rules` and `timing_conventions` null, so the FSM table check never had a table to check.
#: They stay nullable (`anyOf` with null), so "this design has no state machine" is still sayable --
#: but it has to be said.
DECISION_REQUIRED_SECTIONS = ("fsm", "update_rules", "timing_conventions", "timing")


def contract_json_schema() -> dict:
    """The Contract schema for guided decoding, with the structured sections forced to be emitted."""
    schema = Contract.model_json_schema()
    required = list(schema.get("required") or [])
    props = schema.get("properties") or {}
    for key in DECISION_REQUIRED_SECTIONS:
        if key in props and key not in required:
            required.append(key)
    schema["required"] = required
    return schema
