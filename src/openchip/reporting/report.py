"""Delivery report: human-readable Markdown plus machine-readable outcome JSON.

Outcome language is precise and scoped: what was generated, which checks ran with which tool
versions and seeds, which requirements have evidence, and what remains unverified.
"""
from __future__ import annotations

import hashlib
import copy
import json
import platform
import time
from pathlib import Path
from typing import TYPE_CHECKING

from ..contracts.schema import Contract, Disposition
from ..contracts.coerce import requested_module_name
from ..tools.base import tool_version

if TYPE_CHECKING:
    from ..config import Config
    from ..runtime.store import RunStore
    from ..runtime.workspace import Workspace


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else ""


def consensus_confidence(ck: dict) -> str:
    """Confidence in the reference vote behind an acceptance.

    No consensus block means no reference vote was held, which is the ordinary
    single-reference path. A consensus block that records no confidence means an
    arbitration path reached a conclusion without stating one; that is treated as
    low, never as full confidence.
    """
    c = ck.get("consensus") or {}
    if not c:
        return "high"
    return c.get("confidence") or "low"


# Arbitration outcomes meaning the independently derived references never reached
# unanimity. Acceptances carrying one of these were wrong in 14 of 17 recorded cases
# (11 of 11 on the VerilogEval agent corpus); see docs/decisions/0009-signoff-gate.md.
NON_UNANIMOUS_OUTCOMES = frozenset({"no_majority", "majority_initial", "majority_alt1"})


def sign_off_withheld(ck: dict, evidence: dict | None = None, contract: Contract | None = None) -> str:
    """Why the design must not be signed off, or "" when it may be.

    Independent acceptance gates beyond agreement between generated RTL and references:
      - the contract still records decisions requiring user clarification;
      - the delivered name contradicts an explicit initial module-name request;
      - the model's own independent reference derivations never agreed unanimously;
      - the reference contradicts a table printed in the request, which is ground truth that
        never passed through the model (docs/decisions/0010-request-tables.md).
      - a recognized standard-clock request lacks a passing independent RTL check.
      - a formal counterexample leaves a contradiction requiring review.
    """
    reasons: list[str] = []
    if contract is not None and contract.unresolved:
        reasons.append(f"{len(contract.unresolved)} unresolved contract decision(s) require clarification before sign-off")
    property_review = ck.get("property_review") or {}
    if (property_review and property_review.get("status") != "bounded_pass"
            and ((evidence or {}).get("formal") or {}).get("status") != "bounded_pass"):
        reasons.append("the original formal counterexample remains unresolved after checker review")
    named = requested_module_name(ck.get("request", ""))
    if named and contract is not None and contract.module_name != named:
        reasons.append(f"the request names module `{named}`, but the contract delivers `{contract.module_name}`")
    c = ck.get("consensus") or {}
    if c:
        outcome = c.get("outcome") or ""
        if not outcome:
            reasons.append("the reference arbitration recorded no outcome")
        elif outcome in NON_UNANIMOUS_OUTCOMES or c.get("confidence") != "high":
            reasons.append(f"the independently derived references never agreed unanimously (arbitration outcome `{outcome}`)")
    t = ck.get("request_table_check") or {}
    if t.get("status") == "mismatch":
        reasons.append("the reference model contradicts the independently checked request: " + (t.get("detail") or ""))
    elif t.get("status") == "error":
        reasons.append("the request-table check could not complete: " + (t.get("detail") or "checker error"))
    if t.get("status") not in {"mismatch", "error"}:
        from ..contracts.cellular import cellular_scope
        if cellular_scope(ck.get("request", ""))[0] and (t.get("status") != "ok" or "cellular_transition_table" not in t.get("checked_kinds", [])):
            reasons.append("the independent sequential cell-table check has not completed")
        from ..contracts.neighbors import neighbor_scope
        if neighbor_scope(ck.get("request", ""))[0] and (t.get("status") != "ok" or "neighbor_vector_equations" not in t.get("checked_kinds", [])):
            reasons.append("the independent vector-neighbor check has not completed")
        from ..contracts.state_tables import parse_state_tables
        try:
            state_tables = parse_state_tables(ck.get("request", ""))
        except (ValueError, OverflowError):
            reasons.append("the independent state-table check could not establish its scope")
        else:
            if state_tables and (t.get("status") != "ok" or "one_hot_state_table" not in t.get("checked_kinds", [])):
                reasons.append("the independent one-hot state-table check has not completed")
    from ..verification.clockcheck import requires_clock_check
    clock = ck.get("clock_check") or {}
    if requires_clock_check(ck.get("request", "")) and clock.get("status") != "ok":
        reasons.append("the independent standard-clock check did not pass: " + (clock.get("detail") or "check not completed"))
    from ..verification.lfsrcheck import requires_lfsr_check, lfsr_contract_matches
    lfsr = ck.get("lfsr_check") or {}
    if requires_lfsr_check(ck.get("request", "")) and lfsr.get("status") != "ok":
        reasons.append("the independent LFSR check did not pass: " + (lfsr.get("detail") or "check not completed"))
    if contract is not None and lfsr_contract_matches(contract, ck.get("request", "")) is False:
        reasons.append("the generated LFSR contract has not been reconciled with the request-derived specification; create a new build from the original request to derive a consistent contract")
    if ((evidence or {}).get("formal") or {}).get("status") == "counterexample":
        reasons.append("formal checking found a counterexample; the RTL or property checker requires review")
    return "; ".join(reasons)


def write_report(ws: "Workspace", store: "RunStore", run_id: str, ck: dict, cfg: "Config", final_state: str, reason: str,
                 budget: dict, tool_time_s: float) -> dict:
    reports = ws.dir("reports")
    contract = Contract.model_validate_json(Path(ck["contract_path"]).read_text()) if ck.get("contract_path") else None
    evidence = json.loads(Path(ck["last_evidence"]).read_text()) if ck.get("last_evidence") and Path(ck["last_evidence"]).is_file() else None
    accepted = bool(evidence and evidence.get("accepted"))
    withheld = sign_off_withheld(ck, evidence, contract) if accepted else ""
    if withheld:
        accepted = False
    history = copy.deepcopy(ck.get("history", []))
    rtl_path = Path(ck["rtl_path"]) if ck.get("rtl_path") else None
    ref_path = Path(ck["reference_path"]) if ck.get("reference_path") else None
    retention_errors = []

    def retained(path, expected=None):
        if not path:
            return None
        try:
            return store.retain(Path(path), expected)
        except (OSError, ValueError) as exc:
            retention_errors.append(str(exc))
            return None

    verified_artifacts = (evidence or {}).get("artifacts", {})
    rtl_path = retained(rtl_path, verified_artifacts.get("rtl_sha256"))
    ref_path = retained(ref_path, verified_artifacts.get("reference_sha256"))
    contract_path = retained(ck.get("contract_path"))
    properties_path = retained(ck.get("properties_path"))
    final_evidence = retained(ck.get("final_evidence") or ck.get("last_evidence"))
    consensus = copy.deepcopy(ck.get("consensus"))
    for reference in (consensus or {}).get("references", []):
        saved = retained(reference.get("path"), reference.get("sha256"))
        reference.update(path=str(saved) if saved else None, sha256=_sha(saved) if saved else "")
    for item in history:
        if item.get("evidence"):
            saved = retained(item["evidence"])
            item["evidence"] = str(saved) if saved else None
    if retention_errors:
        accepted = False
        withheld = (withheld + "; " if withheld else "") + "artifact retention failed: " + "; ".join(sorted(set(retention_errors)))

    # ---- requirement-to-evidence index --------------------------------------------------
    req_index = []
    if contract:
        for r in contract.requirements:
            if accepted:
                disp = "tested (random simulation vs. independent reference; not a proof)"
            elif evidence and evidence.get("accepted") and withheld:
                disp = "NOT signed off — an independent acceptance gate failed or is incomplete"
            elif evidence:
                disp = f"NOT verified — last verification stopped at stage '{evidence.get('stage')}'"
            else:
                disp = "NOT verified — no verification ran"
            if r.disposition == Disposition.unsupported:
                disp = "unsupported (declared in contract)"
            req_index.append({"id": r.id, "text": r.text, "source": r.source.value, "evidence": disp})

    # ---- status line ---------------------------------------------------------------------
    parts = []
    if rtl_path and rtl_path.is_file():
        parts.append("RTL generated")
    else:
        parts.append("RTL not generated")
    if evidence:
        if evidence.get("lint"):
            parts.append("lint " + ("passed" if evidence["lint"].get("ok") else "FAILED"))
        if evidence.get("compile"):
            parts.append("compile " + ("passed" if evidence["compile"].get("ok") else "FAILED"))
        sims = evidence.get("sims", [])
        if sims:
            npass = sum(1 for s in sims if s["status"] == "pass")
            parts.append(f"simulation passed for {npass}/{len(sims)} seeds x {sims[0]['cycles']} cycles")
        if evidence.get("synth"):
            parts.append("generic synthesis " + ("passed" if evidence["synth"].get("ok") else "FAILED"))
        else:
            parts.append("synthesis not run")
    if evidence and evidence.get("formal"):
        f = evidence["formal"]
        parts.append(f"formal BMC depth {f.get('depth')}: {f.get('status')}" + (" (bounded, not a proof)" if f.get("status") == "bounded_pass" else ""))
    else:
        parts.append("formal not run")
    parts.append("timing closure not evaluated")
    if withheld:
        parts.append("SIGN-OFF WITHHELD: " + withheld)
    conf = consensus_confidence(ck)
    n_unresolved = len(contract.unresolved) if contract else 0
    provisional = accepted and (n_unresolved > 0 or conf != "high")
    if accepted and conf != "high":
        parts.append(f"reference vote not unanimous ({conf} confidence)")
    if provisional:
        why = [f"{n_unresolved} unresolved decision(s)"] if n_unresolved else []
        if conf != "high":
            why.append("non-unanimous reference vote")
        parts.append("PROVISIONAL: " + " and ".join(why) + " need the user")
    status_line = f"[{final_state}] " + "; ".join(parts) + (f". Reason: {reason}" if reason else "")

    tools = {k: tool_version(getattr(cfg.tools, k), ("-V",) if k in ("iverilog", "vvp", "yosys") else ("--version",)) for k in ("iverilog", "vvp", "verilator", "yosys", "sby")}
    outcome = {
        "run_id": run_id, "state": final_state, "accepted": accepted, "status_line": status_line, "reason": reason,
        "module": contract.module_name if contract else None, "contract_version": contract.version if contract else None,
        "requested_module": requested_module_name(ck.get("request", "")),
        "contract_digest": contract.digest() if contract else None,
        "artifacts": {
            "contract": str(contract_path) if contract_path else None, "contract_sha256": _sha(contract_path) if contract_path else "",
            "rtl": str(rtl_path) if rtl_path else None, "rtl_sha256": _sha(rtl_path) if rtl_path else "",
            "reference": str(ref_path) if ref_path else None, "reference_sha256": _sha(ref_path) if ref_path else "",
            "final_evidence": str(final_evidence) if final_evidence else None,
            "properties": str(properties_path) if properties_path else None, "properties_sha256": _sha(properties_path) if properties_path else "",
        },
        "formal": (evidence or {}).get("formal") and {k: (evidence or {})["formal"].get(k) for k in ("status", "depth", "failed_assert", "version")},
        "attempts": len(history), "history": history, "reference_consensus": consensus, "review": ck.get("review"), "provisional": provisional,
        "request_table_repair": ck.get("table_repair"),
        "request_table_check": ck.get("request_table_check"),
        "clock_check": ck.get("clock_check"),
        "lfsr_check": ck.get("lfsr_check"),
        "properties_origin": ck.get("properties_origin", "model-generated"),
        "property_review": ck.get("property_review"),
        "contract_origin": ck.get("contract_origin", "model-generated"),
        "resetless_startup": ({"conditioning": contract.clock_reset.conditioning or [{p.name: 0 for p in contract.data_inputs()}] * 3,
                               "conditioning_edges": len(contract.clock_reset.conditioning) or 3, "power_up_state_verified": False}
                              if contract and contract.clock_reset and contract.clock_reset.reset is None else None),
        "model": {"model": cfg.model.model, "revision": cfg.model.revision, "temperature": cfg.model.temperature, "top_p": cfg.model.top_p,
                  "seed": cfg.model.seed, "thinking": cfg.model.thinking, "thinking_requested": cfg.model.thinking,
                  "effective_thinking": "unknown", "max_tokens": cfg.model.max_tokens},
        "tools": tools, "verification_config": cfg.verification.model_dump(),
        "budget": budget, "tool_time_s": round(tool_time_s, 1),
        "requirements": req_index,
        "unresolved": contract.unresolved if contract else [], "assumptions": contract.assumptions if contract else [],
        "defaults": contract.defaults if contract else [], "unsupported": contract.unsupported if contract else [],
        "host": platform.node(), "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    (reports / "outcome.json").write_text(json.dumps(outcome, indent=1))

    # ---- markdown --------------------------------------------------------------------------
    md = [f"# OpenChip delivery report — run `{run_id}`", "", f"**Outcome:** {status_line}", ""]
    if outcome["resetless_startup"]:
        startup = outcome["resetless_startup"]
        md += [f"**Startup scope:** no reset port. Simulation checks outputs after {startup['conditioning_edges']} input-conditioning edges. "
               "DUT state is not initialized by the harness; X/Z remains a failure. Power-up state is not verified.",
               "", "Conditioning inputs (one vector per edge):", "", "```json", json.dumps(startup["conditioning"]), "```", ""]
    if ck.get("properties_origin"):
        md += [f"**Formal checker source:** {ck['properties_origin']}. Earlier replaced checkers are retained with the verification artifacts.", ""]
    if ck.get("table_repair"):
        retained = Path(ck["table_repair"]["retained"])
        retained_label = str(retained.relative_to(ws.root)) if retained.is_relative_to(ws.root) else str(retained)
        md += ["The original generated design contradicted a check derived from your request. "
               "One automatic contract correction was attempted; the outcome above reflects the subsequent verification.",
               f"Earlier contract, code and evidence are retained in `{retained_label}`.", ""]
    if contract:
        md += [f"**Module:** `{contract.module_name}` (contract v{contract.version}, digest `{contract.digest()}`)", ""]
        md += ["## Request", "", "```text", ws.request_text().strip(), "```", ""]
        md += ["## Contract summary", "", f"See `spec/contract.v{contract.version}.md` and `.json`. Interface:", "", contract.port_table_md(), ""]
    md += ["## Artifacts", "", "| Artifact | Path | SHA-256 |", "|---|---|---|"]
    for k in ("contract", "reference", "properties", "rtl"):
        p = outcome["artifacts"].get(k)
        if p:
            md.append(f"| {k} | `{Path(p).relative_to(ws.root) if str(p).startswith(str(ws.root)) else p}` | `{outcome['artifacts'][k + '_sha256'][:16]}…` |")
    md.append("")
    md += ["## Verification evidence", ""]
    clock = ck.get("clock_check") or {}
    if clock.get("status") and clock["status"] != "not_applicable":
        md += [f"Independent standard-clock check: **{clock['status']}**, {clock.get('checked_cycles', 0)} cycles checked. "
               + clock.get("detail", ""), ""]
    if evidence:
        md.append(f"Final verification attempt reached stage **{evidence.get('stage')}**: {evidence.get('summary')}.")
        md.append("")
        if evidence.get("lint"):
            lint = evidence["lint"]
            md.append(f"- Verilator lint (`{lint.get('version','')}`): {'ok' if lint.get('ok') else 'FAILED'}; {len(lint.get('diagnostics', []))} diagnostic(s).")
        if evidence.get("compile"):
            md.append(f"- Icarus compile (`{evidence['compile'].get('version','')}`): {'ok' if evidence['compile'].get('ok') else 'FAILED'}.")
        for s in evidence.get("sims", []):
            md.append(f"- Simulation seed {s['seed']}: **{s['status']}** ({s['cycles']} checked cycles; {s['mismatches']} mismatching cycles).")
        if evidence.get("synth"):
            syn = evidence["synth"]
            cells = syn.get("num_cells")
            md.append(f"- Yosys generic synthesis (`{syn.get('version','')}`): {'ok' if syn.get('ok') else 'FAILED'}" + (f"; {cells} generic cells after techmap (not a technology-mapped area; no timing analysis)." if cells is not None else "."))
        if evidence.get("formal"):
            f = evidence["formal"]
            md.append(f"- SymbiYosys BMC (`{f.get('version','')}`, depth {f.get('depth')}) on the independent property checker: **{f.get('status')}**" + (f"; failed assertion `{f.get('failed_assert')}`" if f.get("failed_assert") else "") + ". Bounded result at the stated depth; immediate assertions only.")
        if evidence.get("reference_error"):
            md.append(f"- Reference model error: `{evidence['reference_error'].splitlines()[0]}`")
    else:
        md.append("No verification evidence was produced.")
    md.append("")
    if ck.get("property_review"):
        pr = ck["property_review"]
        md += ["### Property checker review", "", f"Review/recheck status: **{pr.get('status')}**. "
               "The checker was reviewed without candidate RTL or solver verdicts. Original checker and counterexample evidence were retained; this does not establish unbounded correctness.",
               f"Original evidence: `{pr.get('original_formal')}`. Reviewed evidence: `{pr.get('reviewed_formal', 'not produced')}`.", ""]
    if ck.get("review"):
        rv = ck["review"]
        md += ["### Independent spec review", "", f"Verdict: **{rv.get('verdict')}** (reviewer `{rv.get('reviewer_model')}`). Applied {len(rv.get('applied', []))} correction(s), rejected {len(rv.get('rejected', []))}, {len(rv.get('unresolved', []))} question(s) for the user." + (f" {rv.get('notes')}" if rv.get("notes") else ""), ""]
        for a in rv.get("applied", []):
            md.append(f"- applied `{a.get('kind')}` on `{a.get('target')}`: {a.get('result')} — {str(a.get('reason',''))[:160]}")
        if rv.get("applied"):
            md.append("")
    if ck.get("consensus"):
        c = ck["consensus"]
        md += ["### Reference cross-check", "", f"Outcome: **{c.get('outcome')}** (confidence: {c.get('confidence', 'n/a')}). References derived: " + ", ".join(f"`{Path(r['path']).name}` ({r['role']})" for r in c.get("references", [])) + ".",
               "A second independently derived reference arbitrates when RTL and reference disagree; agreement of two independent derivations is evidence, not proof.", ""]
    md += ["### Attempt history", "", "| # | Stage reached | Accepted | Summary |", "|---|---|---|---|"]
    md += [f"| {h['attempt']} | {h['stage']} | {h['accepted']} | {h['summary']} |" for h in history]
    md += ["", "Failed attempts are preserved under `verification/attempts/attempt_<n>/` with the RTL of that attempt and `evidence.json`.", ""]
    md += ["## Requirement-to-evidence index", "", "| ID | Requirement | Source | Evidence |", "|---|---|---|---|"]
    md += [f"| {r['id']} | {r['text']} | {r['source']} | {r['evidence']} |" for r in req_index]
    md.append("")
    for title, items in (("Unresolved decisions (need the user)", outcome["unresolved"]), ("Assumptions", outcome["assumptions"]),
                         ("Defaults taken", outcome["defaults"]), ("Unsupported", outcome["unsupported"])):
        if items:
            md += [f"## {title}", ""] + [f"- {i}" for i in items] + [""]
    md += ["## Scope of the claims", "",
           "- Simulation evidence is bounded: random/directed stimulus for the listed seeds and cycle counts, compared against a model-generated reference that was derived independently from the RTL but from the same contract. Agreement does not establish that the contract itself matches the user's intent.",
           "- No formal properties were proved. No timing, power, or technology-mapped area claims are made. Yosys generic cell counts are a sanity metric only.",
           "- This is a generated RTL deliverable, not a manufacturable chip.", ""]
    md += ["## Reproduction", "", "```bash", f"openchip verify --project {ws.root}", "```", "",
           f"Model: `{cfg.model.model}` @ `{cfg.model.revision}` (temperature {cfg.model.temperature}, seed {cfg.model.seed}, requested thinking setting={cfg.model.thinking}; effective provider reasoning is unknown). Tools: " + ", ".join(f"{k}: {v or 'missing'}" for k, v in tools.items()), "",
           f"Budget: {budget}. Tool execution time {tool_time_s:.1f}s.", ""]
    (reports / "report.md").write_text("\n".join(md))
    saved_json = store.retain(reports / "outcome.json")
    saved_md = store.retain(reports / "report.md")
    store.event(run_id, "report_retained", {"outcome": str(saved_json), "report": str(saved_md)})
    return outcome
