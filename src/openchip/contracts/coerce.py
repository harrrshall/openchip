"""Tolerant normalisation of model-written contract JSON before strict validation.

Hosted providers do not all honour JSON-schema guidance, so replies arrive with renamed keys
(`description` for `text`), missing fields (`purpose`, per-port `timing`) or string widths. Only
unambiguous repairs are made here; every defaulted timing label is reported so the reviewer can
check it, and anything still wrong is rejected by the strict schema.
"""
from __future__ import annotations

import re
from typing import Any

COMB_HINT = re.compile(r"combinational|asynchronous|reflects|shows|function of|immediately|same cycle|no clock", re.I)
REG_HINT = re.compile(r"register|flip-?flop|at the (rising|clock) edge|becomes|pulse|latch|hold", re.I)


def requested_module_name(request: str) -> str | None:
    """Recognize one explicit initial module name; user revisions need their own authority."""
    if re.search(r"\n\nChange request \(v\d+\):", request):
        return None
    matches = re.finditer(r"\b(?:implement|create|build)\s+(?:a\s+)?module\s+named\s+[`\"']?([A-Za-z_]\w*)", request, re.I)
    names = {m[1] for m in matches
             if not re.search(r"\b(?:not|never|don't|avoid)\s+$", request[:m.start()], re.I)}
    return next(iter(names)) if len(names) == 1 else None


def coerce_contract(data: dict[str, Any], request: str = "", *, enforce_module_name: bool = False,
                    enforce_table_bounds: bool = False) -> tuple[dict[str, Any], list[str]]:
    notes: list[str] = []
    d = dict(data)
    named = requested_module_name(request) if enforce_module_name else None
    if named and d.get("module_name") != named:
        d["module_name"] = named
        notes.append(f"module_name restored to explicitly requested {named}")
    if not d.get("purpose"):
        d["purpose"] = (d.get("behavior") or request or "").strip().split("\n")[0][:200] or "See behavior."
        notes.append("purpose defaulted from behavior")
    d.setdefault("parameters", [])
    d.setdefault("assumptions", []); d.setdefault("defaults", []); d.setdefault("unresolved", []); d.setdefault("unsupported", [])
    # clock/reset: accept dict or null; map common key aliases
    cr = d.get("clock_reset")
    if isinstance(cr, dict):
        cr = {("clock" if k in ("clk", "clock_name") else "reset" if k in ("rst", "reset_name") else k): v for k, v in cr.items()}
        if str(cr.get("reset_active", "")).lower() in ("active-high", "1", "high"):
            cr["reset_active"] = "high"
        if str(cr.get("reset_active", "")).lower() in ("active-low", "0", "low"):
            cr["reset_active"] = "low"
        if str(cr.get("reset_kind", "")).lower().startswith("sync"):
            cr["reset_kind"] = "synchronous"
        if str(cr.get("reset_kind", "")).lower().startswith("async"):
            cr["reset_kind"] = "asynchronous"
        reset = cr.get("reset", "rst")
        declared = {p.get("name") for p in d.get("ports", []) if isinstance(p, dict)}
        if isinstance(reset, str) and reset.lower().strip() in {"", "none", "null", "no reset"} and reset not in declared:
            cr["reset"] = None
            notes.append("explicit absence of a reset normalized to null")
        if cr.get("reset", "rst") is None:
            # These fields have no physical meaning without a reset port.
            cr["reset_active"] = "high"
            cr["reset_kind"] = "synchronous"
        d["clock_reset"] = cr
    # ports
    table_bounds = {}
    if enforce_table_bounds:
        from .tables import request_table_port_bounds
        bounds = request_table_port_bounds(request)
        if not bounds["ambiguities"]:
            table_bounds = bounds["ranges"]
    ports = []
    for p in d.get("ports", []) or []:
        if not isinstance(p, dict):
            continue
        q = dict(p)
        dirn = str(q.get("direction", q.get("dir", ""))).lower()
        q["direction"] = "input" if dirn.startswith("in") else "output" if dirn.startswith("out") else dirn
        w = q.get("width", 1)
        if isinstance(w, str):
            m = re.search(r"\d+", w)
            if m:
                if not q.get("width_expr") and not w.strip().isdigit():
                    q["width_expr"] = w.strip()
                q["width"] = int(m.group())
        q.setdefault("description", "")
        bound = table_bounds.get(q.get("name"))
        if (bound and q["direction"] == "input" and q.get("width") == bound["width"]
                and not q.get("width_expr") and q.get("lsb", 0) != bound["lsb"]):
            old = q.get("lsb", 0)
            q["lsb"] = bound["lsb"]
            low, width = bound["lsb"], bound["width"]
            notes.append(f"{q['name']}.lsb restored from {old} to {low}: the literal {width}-bit input and complete public table labels {q['name']}[{low}] through {q['name']}[{low+width-1}] require [{low+width-1}:{low}]. Review all behavior with these labels; no truth rows or equations were changed.")
        if q["direction"] == "input":
            q["timing"] = "n/a"
        elif q.get("timing") not in ("registered", "combinational"):
            desc = f"{q.get('description','')} {q.get('name','')}"
            if d.get("clock_reset") is None or (COMB_HINT.search(desc) and not REG_HINT.search(desc)):
                q["timing"] = "combinational"
            else:
                q["timing"] = "registered"
            notes.append(f"timing of output {q.get('name')} defaulted to {q['timing']}")
        ports.append(q)
    d["ports"] = ports
    # requirements: aliases and ids
    reqs = []
    for i, r in enumerate(d.get("requirements", []) or []):
        if isinstance(r, str):
            r = {"text": r}
        if not isinstance(r, dict):
            continue
        q = dict(r)
        if not q.get("text"):
            q["text"] = q.get("description") or q.get("requirement") or q.get("statement") or ""
        rid = str(q.get("id", ""))
        if not re.match(r"^R\d{3}$", rid):
            q["id"] = f"R{i + 1:03d}"
        src = str(q.get("source", "inference")).lower()
        q["source"] = src if src in ("user_text", "document", "inference", "default", "protocol") else ("user_text" if "user" in src else "inference")
        q.pop("description", None)
        reqs.append(q)
    d["requirements"] = reqs
    return d, notes
