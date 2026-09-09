"""Delivery report: human-readable Markdown plus machine-readable outcome JSON.

Outcome language is precise and scoped: what was generated, which checks ran with which tool
versions and seeds, which requirements have evidence, and what remains unverified.
"""
from __future__ import annotations

import hashlib
import json
import platform
import time
from pathlib import Path
from typing import TYPE_CHECKING

from ..contracts.schema import Contract, Disposition
from ..tools.base import tool_version

if TYPE_CHECKING:
    from ..config import Config
    from ..runtime.store import RunStore
    from ..runtime.workspace import Workspace


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else ""


def write_report(ws: "Workspace", store: "RunStore", run_id: str, ck: dict, cfg: "Config", final_state: str, reason: str,
                 budget: dict, tool_time_s: float) -> dict:
    reports = ws.dir("reports")
    contract = Contract.model_validate_json(Path(ck["contract_path"]).read_text()) if ck.get("contract_path") else None
    evidence = json.loads(Path(ck["last_evidence"]).read_text()) if ck.get("last_evidence") and Path(ck["last_evidence"]).is_file() else None
    accepted = bool(evidence and evidence.get("accepted"))
    history = ck.get("history", [])
    rtl_path = Path(ck["rtl_path"]) if ck.get("rtl_path") else None
    ref_path = Path(ck["reference_path"]) if ck.get("reference_path") else None

    # ---- requirement-to-evidence index --------------------------------------------------
    req_index = []
    if contract:
        for r in contract.requirements:
            if accepted:
                disp = "tested (random simulation vs. independent reference; not a proof)"
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
    status_line = f"[{final_state}] " + "; ".join(parts) + (f". Reason: {reason}" if reason else "")

    tools = {k: tool_version(getattr(cfg.tools, k), ("-V",) if k in ("iverilog", "vvp", "yosys") else ("--version",)) for k in ("iverilog", "vvp", "verilator", "yosys", "sby")}
    outcome = {
        "run_id": run_id, "state": final_state, "accepted": accepted, "status_line": status_line, "reason": reason,
        "module": contract.module_name if contract else None, "contract_version": contract.version if contract else None,
        "contract_digest": contract.digest() if contract else None,
        "artifacts": {
            "contract": ck.get("contract_path"), "contract_sha256": _sha(Path(ck["contract_path"])) if ck.get("contract_path") else "",
            "rtl": str(rtl_path) if rtl_path else None, "rtl_sha256": _sha(rtl_path) if rtl_path else "",
            "reference": str(ref_path) if ref_path else None, "reference_sha256": _sha(ref_path) if ref_path else "",
            "final_evidence": ck.get("final_evidence") or ck.get("last_evidence"),
            "properties": ck.get("properties_path"), "properties_sha256": _sha(Path(ck["properties_path"])) if ck.get("properties_path") else "",
        },
        "formal": (evidence or {}).get("formal") and {k: (evidence or {})["formal"].get(k) for k in ("status", "depth", "failed_assert", "version")},
        "attempts": len(history), "history": history, "reference_consensus": ck.get("consensus"),
        "model": {"model": cfg.model.model, "revision": cfg.model.revision, "temperature": cfg.model.temperature, "top_p": cfg.model.top_p,
                  "seed": cfg.model.seed, "thinking": cfg.model.thinking, "max_tokens": cfg.model.max_tokens},
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
    if evidence:
        md.append(f"Final verification attempt reached stage **{evidence.get('stage')}**: {evidence.get('summary')}.")
        md.append("")
        if evidence.get("lint"):
            lint = evidence["lint"]
            md.append(f"- Verilator lint (`{lint.get('version','')}`): {'ok' if lint.get('ok') else 'FAILED'}; {len(lint.get('diagnostics', []))} diagnostic(s).")
        if evidence.get("compile"):
            md.append(f"- Icarus compile (`{evidence['compile'].get('version','')}`): {'ok' if evidence['compile'].get('ok') else 'FAILED'}.")
        for s in evidence.get("sims", []):
            md.append(f"- Simulation seed {s['seed']}: **{s['status']}** ({s['cycles']} cycles after reset; {s['mismatches']} mismatching cycles).")
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
           f"Model: `{cfg.model.model}` @ `{cfg.model.revision}` (temperature {cfg.model.temperature}, seed {cfg.model.seed}, thinking={cfg.model.thinking}). Tools: " + ", ".join(f"{k}: {v or 'missing'}" for k, v in tools.items()), "",
           f"Budget: {budget}. Tool execution time {tool_time_s:.1f}s.", ""]
    (reports / "report.md").write_text("\n".join(md))
    return outcome
