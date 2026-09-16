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
    clock_edge: Literal["posedge", "negedge"] = "posedge"
    reset: str = "rst"
    reset_active: Literal["high", "low"] = "high"
    reset_kind: Literal["synchronous", "asynchronous"] = "synchronous"
    reset_description: str = "All state returns to its documented initial value."


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
            if cr.clock == cr.reset:
                raise ValueError("clock and reset must be distinct input ports; a missing reset must not be replaced with the clock")
            if cr.clock not in names:
                raise ValueError(f"clock port {cr.clock!r} is not declared")
            if cr.reset not in names:
                raise ValueError(f"reset port {cr.reset!r} is not declared")
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


def contract_json_schema() -> dict:
    return Contract.model_json_schema()
