"""User-facing summaries derived from recorded run evidence."""
from __future__ import annotations

import difflib
from pathlib import Path


def result_summary(outcome: dict, state: str | None) -> dict:
    questions = [str(q) for q in outcome.get("unresolved", []) if str(q).strip()]
    questions = list(dict.fromkeys(questions))
    formal = outcome.get("formal") or {}
    provisional = bool(outcome.get("provisional"))
    withheld = "SIGN-OFF WITHHELD" in outcome.get("status_line", "")
    clock = outcome.get("clock_check") or {}
    clock_failed = clock.get("status") in {"mismatch", "error"}
    lfsr_failed = (outcome.get("lfsr_check") or {}).get("status") in {"mismatch", "error"}
    table_failed = (outcome.get("request_table_check") or {}).get("status") in {"mismatch", "error"}
    formal_failed = formal.get("status") == "counterexample"
    module_failed = bool(outcome.get("requested_module") and outcome["requested_module"] != outcome.get("module"))
    consensus = outcome.get("reference_consensus") or {}
    references_uncertain = bool(consensus) and consensus.get("confidence") != "high"
    if (provisional or (withheld and references_uncertain)) and not questions and not clock_failed and not table_failed and not formal_failed and not module_failed and not lfsr_failed:
        questions = ["The independent references disagree or lack corroboration. Please clarify the intended behavior, including timing and priority when inputs coincide."]
    if state in {"running", "planned", "created"}:
        sentence = "Building and checking your design"
    elif (outcome.get("artifact_integrity") or {}).get("status") == "changed":
        sentence = "Files changed since verification; previous sign-off does not apply"
    elif clock_failed:
        sentence = "Independent clock verification failed; sign-off withheld"
    elif lfsr_failed:
        sentence = "Independent LFSR verification failed; sign-off withheld"
    elif table_failed:
        sentence = "Request-table verification failed; sign-off withheld"
    elif formal_failed:
        sentence = "Formal counterexample needs review; sign-off withheld"
    elif module_failed:
        sentence = "The delivered module name differs from your request; sign-off withheld"
    elif questions:
        sentence = f"Needs your answer on {len(questions)} question{'s' if len(questions) != 1 else ''}"
    elif state == "completed" and outcome.get("accepted") and not provisional and not withheld:
        sentence = ("Simulation and synthesis passed; formal check needs review"
                    if formal.get("status") in {"counterexample", "error", "unknown", "timeout"}
                    else "Verified and signed off")
    elif state == "budget_exhausted":
        sentence = "Stopped at the time limit; verification is incomplete"
    elif state == "paused":
        sentence = "Paused; verification is incomplete"
    else:
        sentence = "Needs more work before sign-off"
    required = (outcome.get("verification_config") or {}).get("require_formal")
    return {"sentence": sentence, "questions": questions,
            "formal": {"status": formal.get("status", "not_run"),
                       "required": required,
                       "informational": required is False and not formal_failed}}


def stage_durations(events: list[dict], end: float) -> list[dict]:
    """Checkpoint timestamps mark stage entry; accumulate repeated repair visits."""
    durations: dict[str, float] = {}
    checkpoints = [e for e in events if e.get("kind") == "checkpoint" and e.get("step")]
    for index, event in enumerate(checkpoints):
        stop = checkpoints[index + 1]["ts"] if index + 1 < len(checkpoints) else end
        stage = event["step"]
        durations[stage] = durations.get(stage, 0) + max(0, stop - event["ts"])
    return [{"stage": stage, "seconds": round(seconds, 1)} for stage, seconds in durations.items()]


def contract_diff(spec: list[Path]) -> str:
    if len(spec) < 2:
        return "No previous contract version to compare."
    before, after = spec[-2:]
    return "".join(difflib.unified_diff(before.read_text().splitlines(True),
                                       after.read_text().splitlines(True),
                                       fromfile=before.name, tofile=after.name)) or "No text changes."
