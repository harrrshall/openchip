"""Pinned module instances and deterministic structural integration.

This validates topology, not the behavior or trustworthiness of leaf RTL.
System-level simulation and leaf acceptance remain separate requirements.
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .schema import Contract, Port, eval_width


class Instance(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    contract: Contract
    version: int = Field(ge=1)
    digest: str
    parameters: dict[str, int] = Field(default_factory=dict)
    open_outputs: list[str] = Field(default_factory=list)

    def ports(self) -> dict[str, Port]:
        c = self.contract
        if self.version != c.version or self.digest != c.digest():
            raise ValueError(f"{self.name}: leaf contract version/digest does not match its pin")
        defaults = c.param_defaults()
        if len(defaults) != len(c.parameters):
            raise ValueError(f"{self.name}: duplicate parameters")
        if set(self.parameters) - defaults.keys():
            raise ValueError(f"{self.name}: unknown parameter binding")
        values = defaults | self.parameters
        for p in c.parameters:
            if (p.min is not None and values[p.name] < p.min) or (p.max is not None and values[p.name] > p.max):
                raise ValueError(f"{self.name}: parameter {p.name} outside its bounds")
        ports = {}
        for p in c.ports:
            width = eval_width(p.width_expr, values) if p.width_expr else p.width
            ports[p.name] = Port.model_validate(p.model_dump() | {"width": width})
        if len(self.open_outputs) != len(set(self.open_outputs)):
            raise ValueError(f"{self.name}: duplicate open outputs")
        for name in self.open_outputs:
            if name not in ports or ports[name].direction != "output":
                raise ValueError(f"{self.name}: only declared outputs may be left open")
        return ports


class Connection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    from_module: str
    from_port: str
    to_module: str
    to_port: str
    width: int = Field(ge=1, le=4096)

    @property
    def source(self) -> tuple[str, str]:
        return self.from_module, self.from_port

    @property
    def target(self) -> tuple[str, str]:
        return self.to_module, self.to_port


class SystemContract(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: int = Field(default=1, ge=1, le=1)
    top: Contract
    modules: list[Instance] = Field(min_length=2, max_length=4)
    connections: list[Connection]
    integration_requirements: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_topology(self) -> "SystemContract":
        names = [m.name for m in self.modules]
        if "TOP" in names or len(names) != len(set(names)):
            raise ValueError("instance names must be unique; TOP is reserved")
        if set(names) & {p.name for p in self.top.ports}:
            raise ValueError("instance names must not collide with top ports")
        requirements = {r.id for r in self.top.requirements}
        if set(self.integration_requirements) - requirements:
            raise ValueError("integration requirements must name top-level requirement IDs")
        if len(self.integration_requirements) != len(set(self.integration_requirements)):
            raise ValueError("duplicate integration requirement IDs")
        ports = {"TOP": {p.name: p for p in self.top.ports}}
        definitions = {}
        for m in self.modules:
            ports[m.name] = m.ports()
            name = m.contract.module_name
            if name == self.top.module_name:
                raise ValueError("leaf module name collides with top module")
            if name in definitions and definitions[name] != m.digest:
                raise ValueError(f"conflicting contracts for module definition {name}")
            definitions[name] = m.digest
            cr, top_cr = m.contract.clock_reset, self.top.clock_reset
            if cr and (not top_cr or cr.clock_edge != top_cr.clock_edge
                       or (cr.reset is None) != (top_cr.reset is None)
                       or cr.reset_active != top_cr.reset_active or cr.reset_kind != top_cr.reset_kind):
                raise ValueError(f"{m.name}: clock/reset semantics do not match the top")
        drivers = {}
        used = set()
        for c in self.connections:
            try:
                src, dst = ports[c.from_module][c.from_port], ports[c.to_module][c.to_port]
            except KeyError as exc:
                raise ValueError(f"connection endpoint is undeclared: {exc}") from exc
            if src.direction != ("input" if c.from_module == "TOP" else "output"):
                raise ValueError(f"{c.source}: connection source is not a driver")
            if dst.direction != ("output" if c.to_module == "TOP" else "input"):
                raise ValueError(f"{c.target}: connection target is not a sink")
            if src.width != dst.width or src.width != c.width or src.signed != dst.signed:
                raise ValueError(f"{c.source} -> {c.target}: width/signedness mismatch after binding")
            if c.target in drivers:
                raise ValueError(f"{c.target}: multiple drivers")
            drivers[c.target] = c.source
            used.add(c.source)
        for p in self.top.outputs():
            if ("TOP", p.name) not in drivers:
                raise ValueError(f"top output {p.name} has no driver")
        for m in self.modules:
            for p in m.contract.inputs():
                if (m.name, p.name) not in drivers:
                    raise ValueError(f"{m.name}.{p.name}: floating input")
            for p in m.contract.outputs():
                connected = (m.name, p.name) in used
                if connected == (p.name in m.open_outputs):
                    raise ValueError(f"{m.name}.{p.name}: output must be connected or explicitly open")
            cr = m.contract.clock_reset
            if cr:
                for leaf_port, top_port in ((cr.clock, self.top.clock_reset.clock), (cr.reset, self.top.clock_reset.reset)):
                    if leaf_port is None:
                        continue
                    if drivers[(m.name, leaf_port)] != ("TOP", top_port):
                        raise ValueError(f"{m.name}.{leaf_port}: must connect directly to shared top clock/reset")
        # Conservatively assume every combinational leaf output depends on every
        # data input. Registered outputs break paths; no guessed independence.
        graph = {}
        for m in self.modules:
            for p in m.contract.outputs():
                graph[(m.name, p.name)] = (
                    [drivers[(m.name, q.name)] for q in m.contract.data_inputs()]
                    if p.timing == "combinational" else []
                )
        visiting, done = set(), set()

        def visit(node):
            if node in visiting:
                raise ValueError("combinational cycle between modules")
            if node in done:
                return
            visiting.add(node)
            for source in graph.get(node, []):
                visit(source)
            visiting.remove(node)
            done.add(node)

        for node in graph:
            visit(node)
        return self

    def unresolved_items(self) -> list[str]:
        return list(self.top.unresolved) + [f"{m.name}: {q}" for m in self.modules for q in m.contract.unresolved]


def render_top(system: SystemContract) -> str:
    """Generate named-port wiring after revalidating mutable nested contracts."""
    system = SystemContract.model_validate(system.model_dump())
    top = system.top
    used = {c.source for c in system.connections}
    drivers = {c.target: c.source for c in system.connections}
    nets = {("TOP", p.name): p.name for p in top.inputs()}
    occupied = {p.name for p in top.ports} | {m.name for m in system.modules}
    lines = ["// Structural assembly only; behavioral integration is not verified.", "`default_nettype none"]

    def decl(p):
        return ("signed " if p.signed else "") + (f"[{p.width - 1}:0] " if p.width > 1 else "")

    # Top parameters retain their defaults; connection widths are elaborated at
    # those defaults. Do not expose overrides that would silently change wiring.
    lines += [f"module {top.module_name} (", ",\n".join(f"  {p.direction.value} wire {decl(p)}{p.name}" for p in top.ports), ");"]
    for m in system.modules:
        for p in m.ports().values():
            key = (m.name, p.name)
            if p.direction == "output" and key in used:
                name = f"oc_net_{len(nets)}"
                while name in occupied:
                    name += "_"
                occupied.add(name)
                nets[key] = name
                lines.append(f"wire {decl(p)}{name};")
    for m in system.modules:
        values = m.contract.param_defaults() | m.parameters
        params = " #(" + ", ".join(f".{k}({v})" for k, v in values.items()) + ")" if values else ""
        mapping = []
        for p in m.contract.ports:
            key = (m.name, p.name)
            wire = nets[drivers[key]] if p.direction == "input" else nets.get(key, "")
            mapping.append(f".{p.name}({wire})")
        lines.append(f"{m.contract.module_name}{params} {m.name} ({', '.join(mapping)});")
    for p in top.outputs():
        lines.append(f"assign {p.name} = {nets[drivers[('TOP', p.name)]]};")
    lines += ["endmodule", "`default_nettype wire", ""]
    return "\n".join(lines)
