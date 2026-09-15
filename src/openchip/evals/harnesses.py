"""Pipeline variants ("harnesses") evaluated by the matrix runner.

A harness is a named overlay on the validated `Config` plus the protocol used to run one
problem (`agent` = full OpenChip pipeline, `direct` = one model call, `vote` = N pipeline
runs cross-checked against each other). Overlays are deep-merged onto a base Config and
re-validated, so a harness can never introduce a field the schema does not know about.

Ablation harnesses exist to attribute the pipeline's cost and its false-acceptance rate to
individual mechanisms: review (independent spec review), corroborate (second reference),
formal (bounded model checking), alt (cross-family second reference).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional

from ..config import Config

Mode = Literal["agent", "direct", "vote"]


def deep_merge(base: dict, overlay: dict) -> dict:
    """Recursively merge `overlay` into a copy of `base`. Non-dict values replace."""
    out = dict(base)
    for k, v in overlay.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def apply_overlay(cfg: Config, overlay: dict) -> Config:
    """Return a new Config with `overlay` deep-merged on top. Validation is re-run."""
    if not overlay:
        return Config.model_validate(cfg.model_dump())
    return Config.model_validate(deep_merge(cfg.model_dump(), overlay))


@dataclass(frozen=True)
class Harness:
    name: str
    description: str
    overlay: dict = field(default_factory=dict)
    mode: Mode = "agent"
    votes: int = 0            # only meaningful for mode "vote"
    requires_alt: bool = False  # the matrix spec must supply an `[alt_model]` block

    def config(self, base: Config, alt_model: Optional[dict] = None) -> Config:
        overlay = dict(self.overlay)
        if self.requires_alt:
            if not alt_model:
                raise ValueError(f"harness {self.name} needs an [alt_model] block in the matrix spec")
            overlay = deep_merge(overlay, {"model": {"alt": alt_model}})
        return apply_overlay(base, overlay)


REGISTRY: dict[str, Harness] = {
    h.name: h
    for h in (
        Harness("baseline", "full pipeline as configured (no overlay)"),
        Harness("direct", "single model call, prompt -> Verilog, no tools", mode="direct"),
        Harness("no-review", "no independent spec review of the contract",
                overlay={"review": {"enabled": False}}),
        Harness("no-corroborate", "acceptance does not need a second independent reference",
                overlay={"verification": {"corroborate": False}}),
        Harness("no-formal", "no bounded model checking (SBY) even when a checker exists",
                overlay={"verification": {"run_formal": False}}),
        Harness("alt-ref", "second reference comes from a different model family", requires_alt=True),
        Harness("vote3", "three pipeline runs, cross-checked; accept only on 2-of-3 agreement",
                mode="vote", votes=3),
    )
}


def get_harness(name: str) -> Harness:
    try:
        return REGISTRY[name]
    except KeyError:
        raise KeyError(f"unknown harness {name!r}; known: {', '.join(sorted(REGISTRY))}") from None


def harness_names() -> list[str]:
    return sorted(REGISTRY)


def run_vote(*_args, **_kwargs) -> dict:
    """DOCUMENTED STUB - vote3 is not implemented.

    The intended protocol: run `harness.votes` full agent pipelines on the same problem with
    different `model.seed` values in separate workspaces; then cross-check every candidate RTL
    against every candidate reference with `openchip.verification.harness.verify(contract, rtl,
    reference_py, work, cfg)`, which is the existing reference-vs-RTL simulation entry point
    (src/openchip/verification/harness.py:169). Accept the RTL agreeing with the most references
    when at least 2 of 3 agree; otherwise withhold with state "no_consensus" and record the
    full vote table. Blocked only on wiring, not on missing APIs: `verify()` already takes an
    arbitrary (contract, rtl, reference) triple, and each run's artefacts land at
    <ws>/spec/contract.v*.json, <ws>/rtl/<module>.v and <ws>/reference/reference.py.
    Deferred by the 2026-09-13 scope decision (ship the runner first).
    """
    raise NotImplementedError(
        "harness vote3 is a documented stub; see openchip.evals.harnesses.run_vote")
