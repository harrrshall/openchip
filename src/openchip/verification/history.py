"""Keep recorded simulation counterexamples attached to unchanged artifacts."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


def prior_simulation_failures(workspace: Path, artifacts: dict) -> list[dict]:
    """Find retained failures for this exact RTL, reference and contract.

    A shorter run or a different seed can miss a previously observed failure.
    Such a pass does not invalidate the failing trace. Changed designs or
    references have different hashes and must be checked on their own merits.
    Only workspace-contained verification receipts are read, never their
    embedded absolute paths (which may refer to a workspace before relocation).
    """
    root = workspace.resolve()
    keys = ("rtl_sha256", "reference_sha256", "contract_digest")
    identity = {key: artifacts.get(key) for key in keys}
    # Contract.digest() is an abbreviated identifier; source hashes are full
    # SHA-256 values. Require every identity component without assuming they
    # have the same representation.
    if not all(isinstance(value, str) and value for value in identity.values()):
        return []
    failures = []
    for path in sorted((root / "verification").rglob("evidence.json")):
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            continue
        try:
            raw = path.read_bytes()
            previous = json.loads(raw)
        except (OSError, ValueError):
            continue
        if not isinstance(previous, dict) or not isinstance(previous.get("artifacts"), dict):
            continue
        if any(previous["artifacts"].get(key) != value for key, value in identity.items()):
            continue
        sims = previous.get("sims") or []
        netlist_sims = previous.get("netlist_sims") or []
        if not isinstance(sims, list) or not isinstance(netlist_sims, list):
            continue
        # A short replay or skipping synthesis cannot erase a demonstrated
        # source-to-hardware discrepancy for these unchanged artifacts.
        failed = [sim for sim in sims + netlist_sims if isinstance(sim, dict) and sim.get("status") == "fail"
                  and isinstance(sim.get("mismatches"), int) and sim["mismatches"] > 0]
        if failed:
            failures.append({"evidence": str(path), "sha256": hashlib.sha256(raw).hexdigest(),
                             "simulations": [{key: sim.get(key) for key in ("seed", "cycles", "mismatches")}
                                             for sim in failed]})
    return failures


def prior_formal_failures(workspace: Path, artifacts: dict, formal: dict | None) -> list[dict]:
    """Retain counterexamples until RTL/contract or a verified checker changes.

    A disabled/missing checker or a smaller bound cannot resolve a recorded
    contradiction. A corrected checker must pass at least the recorded depth.
    This records evidence continuity, not proof that a changed checker is sound.
    """
    root = workspace.resolve()
    keys = ("rtl_sha256", "contract_digest")
    identity = {key: artifacts.get(key) for key in keys}
    if not all(isinstance(value, str) and value for value in identity.values()):
        return []
    current = {**(formal or {}).get("extra", {}), **(formal or {})}
    failures = []
    for path in sorted((root / "verification").rglob("evidence.json")):
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            continue
        try:
            raw = path.read_bytes()
            previous = json.loads(raw)
        except (OSError, ValueError):
            continue
        if not isinstance(previous, dict) or not isinstance(previous.get("artifacts"), dict):
            continue
        if any(previous["artifacts"].get(key) != value for key, value in identity.items()):
            continue
        old_formal = previous.get("formal")
        if not isinstance(old_formal, dict):
            continue
        old = {**old_formal.get("extra", {}), **old_formal}
        if not isinstance(old, dict) or old.get("status") != "counterexample":
            continue
        old_hash = previous["artifacts"].get("properties_sha256")
        new_hash = artifacts.get("properties_sha256")
        changed = bool(old_hash and new_hash and old_hash != new_hash)
        old_depth, new_depth = old.get("depth"), current.get("depth")
        if (changed and (formal or {}).get("ok") is True
                and current.get("status") == "bounded_pass"
                and type(old_depth) is int and type(new_depth) is int
                and new_depth >= old_depth):
            continue
        failures.append({"evidence": str(path), "sha256": hashlib.sha256(raw).hexdigest(),
                         "depth": old_depth, "properties_sha256": old_hash,
                         "checker_changed": changed})
    return failures
