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
        sims = previous.get("sims")
        if not isinstance(sims, list):
            continue
        failed = [sim for sim in sims if isinstance(sim, dict) and sim.get("status") == "fail"
                  and isinstance(sim.get("mismatches"), int) and sim["mismatches"] > 0]
        if failed:
            failures.append({"evidence": str(path), "sha256": hashlib.sha256(raw).hexdigest(),
                             "simulations": [{key: sim.get(key) for key in ("seed", "cycles", "mismatches")}
                                             for sim in failed]})
    return failures
