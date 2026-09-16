"""Refresh retained reference simulations for a CLI recheck, without model calls."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ..config import Config
from ..contracts.schema import Contract
from .harness import VerificationResult, verify
from .history import prior_simulation_failures


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def recheck_consensus(consensus: dict | None, contract: Contract, rtl: Path,
                      primary: Path, primary_result: VerificationResult,
                      work: Path, cfg: Config, cycles: int, seeds: list[int]) -> dict:
    """Historical votes stay historical; fresh receipts describe only current bytes.

    Workspace copies retain absolute historical paths. Resolve their recorded file
    names inside the current reference directory, never execute the old location.
    Agreement is bounded simulation evidence, not proof of independent reasoning.
    """
    if not consensus:
        return {"status": "not_applicable", "references": []}
    result = {"status": "error", "cycles": cycles, "seeds": list(seeds),
              "historical_outcome": consensus.get("outcome"), "references": [],
              "detail": ""}
    entries = consensus.get("references")
    if not isinstance(entries, list) or len(entries) < 2:
        result["detail"] = "the historical reference set is incomplete"
        return result
    try:
        rtl_hash = _sha(rtl)
        primary_hash = _sha(primary)
        if (primary_result.artifacts.get("rtl_sha256") != rtl_hash or
                primary_result.artifacts.get("reference_sha256") != primary_hash):
            raise ValueError("RTL or primary reference changed during verification")
        paths = []
        for entry in entries:
            name = Path(entry.get("path", "")).name
            if not name or not name.endswith(".py"):
                raise ValueError("a historical reference has no usable Python file name")
            path = primary.parent / name
            if not path.is_file() or path.is_symlink():
                raise ValueError(f"retained reference is missing or not a regular file: {name}")
            paths.append((entry, path, _sha(path)))
        if len({p for _, p, _ in paths}) < 2:
            raise ValueError("the historical reference set has fewer than two distinct files")
        if primary not in {p for _, p, _ in paths}:
            raise ValueError("the historical reference set does not identify the current primary")
        result["rtl_sha256"] = rtl_hash
        comparison_cfg = cfg.model_copy(deep=True)
        comparison_cfg.verification.require_formal = False
        comparison_cfg.verification.run_formal = False
        cache = {primary_hash: primary_result}
        all_passed = True
        for index, (entry, path, sha) in enumerate(paths):
            if sha not in cache:
                comparison_work = work / f"reference_{index}"
                cache[sha] = verify(contract, rtl, path, comparison_work,
                                    comparison_cfg, cycles=cycles, seeds=seeds, run_synth=False)
                (comparison_work / "evidence.json").write_text(
                    json.dumps(cache[sha].to_dict(), indent=2))
            measured = cache[sha]
            passed = bool(measured.sims) and len(measured.sims) == len(seeds) and all(
                s["status"] == "pass" and s["cycles"] == cycles and s["seed"] == seed
                for s, seed in zip(measured.sims, seeds))
            prior_failures = prior_simulation_failures(primary.parent.parent, measured.artifacts)
            passed = passed and not prior_failures
            # For alternatives also require successful lint/compile completion.
            if sha != primary_hash:
                passed = passed and measured.accepted
            result["references"].append({"role": entry.get("role"),
                "historical_path": entry.get("path"), "path": str(path),
                "sha256": sha, "passed": passed, "sims": measured.sims,
                "prior_simulation_failures": prior_failures,
                "artifacts": measured.artifacts, "summary": measured.summary})
            all_passed = all_passed and passed
        if _sha(rtl) != rtl_hash or any(_sha(path) != sha for _, path, sha in paths):
            raise ValueError("RTL or retained references changed during the consensus recheck")
        result["status"] = "pass" if all_passed else "fail"
        result["detail"] = ("all retained references passed the current simulation schedule"
                            if all_passed else "a retained reference failed the current simulation schedule")
    except (OSError, ValueError, TypeError, AttributeError) as exc:
        result["status"] = "error"
        result["detail"] = str(exc)
    return result
