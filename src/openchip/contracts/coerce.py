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


def coerce_contract(data: dict[str, Any], request: str = "") -> tuple[dict[str, Any], list[str]]:
    notes: list[str] = []
    d = dict(data)
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
        d["clock_reset"] = cr
    # ports
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
        if q["direction"] == "input":
            q["timing"] = "n/a"
        elif q.get("timing") not in ("registered", "combinational"):
            desc = f"{q.get('description','')} {q.get('name','')}"
            if d.get("clock_reset") is None:
                q["timing"] = "combinational"
            elif COMB_HINT.search(desc) and not REG_HINT.search(desc):
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
