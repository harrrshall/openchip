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


NULLISH = ("", "null", "none", "n/a", "na", "nil", "no reset")
CLOCK_NAMES = ("clk", "clock", "clk_i", "i_clk", "clkin", "clk_in", "sysclk", "clock_in")


def _clock_port(ports: list) -> str | None:
    """The declared clock input, by role first and then by conventional name."""
    ins = [p for p in ports if isinstance(p, dict)
           and str(p.get("direction", p.get("dir", ""))).lower().startswith("in") and p.get("name")]
    for p in ins:
        if str(p.get("role", "")).lower() == "clock":
            return str(p["name"])
    for p in ins:
        if str(p.get("name", "")).strip().lower() in CLOCK_NAMES:
            return str(p["name"])
    return None


def _reconcile_clock(d: dict[str, Any], notes: list[str]) -> None:
    """A declared clock port means the design is clocked, whatever `clock_reset` says.

    Models that decide there is no reset often answer `clock_reset: null` (or with a null clock) for a
    design that plainly has a clock port. Taken literally that says "purely combinational", which then
    forces every registered output to be relabelled and the contract is rejected with
    "a combinational contract (no clock) cannot have registered outputs". The port list decides here
    too: only a design with no clock port at all is combinational.
    """
    ports = d.get("ports") or []
    clk = _clock_port(ports)
    declared = {p.get("name") for p in ports if isinstance(p, dict)}
    cr = d.get("clock_reset")
    if isinstance(cr, dict):
        c = cr.get("clock")
        if isinstance(c, str) and c.strip().lower() in NULLISH:
            c = None
        if c and c in declared:
            return
        if clk:
            notes.append(f"clock_reset.clock was {c!r}; used the declared clock port {clk!r}")
            cr["clock"] = clk
        else:
            d["clock_reset"] = None
            notes.append(f"clock_reset names no declared clock port ({c!r}); recorded as a COMBINATIONAL design")
        return
    if cr is None and clk:
        registered = any(isinstance(p, dict) and str(p.get("direction", p.get("dir", ""))).lower().startswith("out")
                         and p.get("timing") == "registered" for p in ports)
        notes.append(f"clock_reset was null but clock port {clk!r} is declared"
                     + (" and an output is registered" if registered else "")
                     + "; recorded as a CLOCKED design")
        d["clock_reset"] = {"clock": clk}


def _reconcile_reset(d: dict[str, Any], notes: list[str]) -> None:
    """Make `clock_reset.reset` agree with the declared port list.

    The port list is the interface the request asked for, so it decides. A design may legitimately have
    no reset (`reset: null`); models also write the string "null", or keep the habitual default `rst`
    while listing only the requested ports. Naming a reset port that is not declared is never right:
    it either belongs to a port the model did declare under `role: "reset"`, or the design has no reset.
    """
    cr = d.get("clock_reset")
    if not isinstance(cr, dict):
        return
    ports = d.get("ports") or []
    declared = {p.get("name") for p in ports if isinstance(p, dict)}
    reset_ports = [p["name"] for p in ports if isinstance(p, dict) and p.get("direction") == "input"
                   and str(p.get("role", "")).lower() == "reset" and p.get("name")]
    rst = cr.get("reset", "rst")
    if rst is None or (isinstance(rst, str) and rst.strip().lower() in NULLISH):
        rst = None
    if rst is None:
        if reset_ports:
            cr["reset"] = reset_ports[0]
            notes.append(f"clock_reset.reset was null but port {reset_ports[0]!r} is declared with role 'reset'; adopted it")
        else:
            cr["reset"] = None
    elif rst not in declared:
        if reset_ports:
            cr["reset"] = reset_ports[0]
            notes.append(f"clock_reset.reset {rst!r} is not a declared port; used the declared reset port {reset_ports[0]!r}")
        else:
            cr["reset"] = None
            notes.append(f"clock_reset.reset {rst!r} is not a declared port and no port has role 'reset'; recorded as NO RESET")


def _as_outputs(v: Any) -> dict[str, str]:
    """`outputs` of a transition row, however the model wrote it, as {port: value}."""
    if isinstance(v, dict):
        return {str(k): str(x) for k, x in v.items() if isinstance(k, str)}
    items = v if isinstance(v, list) else ([v] if isinstance(v, str) else [])
    out: dict[str, str] = {}
    for item in items:
        if isinstance(item, dict) and item.get("output") is not None:
            out[str(item["output"])] = str(item.get("value", ""))
            continue
        for part in re.split(r"[,;]", str(item)):
            m = re.match(r"\s*([A-Za-z_][A-Za-z0-9_]*)\s*[=:]\s*(.+?)\s*$", part)
            if m:
                out[m.group(1)] = m.group(2)
    return out



_STATE_ID = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _state_ident(name: str) -> str:
    """Turn a model-chosen state label (`000`, `S-1`, `wait for stop`) into a Verilog/Python identifier."""
    n = re.sub(r"[^A-Za-z0-9_]+", "_", str(name).strip()).strip("_") or "S"
    if not _STATE_ID.match(n):
        n = "S_" + n
    return n

def _coerce_fsm(d: dict[str, Any], notes: list[str]) -> None:
    """Normalise the optional `fsm` section, or drop it when it is not usable.

    The section is optional, so a malformed table must never cost the whole contract: repair what is
    unambiguous, drop the rest, and record a note the reviewer sees.
    """
    f = d.get("fsm")
    if f in (None, {}, []):
        d.pop("fsm", None)
        return
    if not isinstance(f, dict):
        d.pop("fsm", None)
        notes.append("fsm section was not an object; dropped")
        return
    f = dict(f)
    states = []
    rename: dict[str, str] = {}
    for s in f.get("states") or []:
        if isinstance(s, str):
            name, meaning = s, ""
        elif isinstance(s, dict):
            name = s.get("name") or s.get("state") or s.get("id")
            meaning = str(s.get("meaning") or s.get("description") or "")
        else:
            continue
        if not name:
            continue
        ident = _state_ident(name)
        if ident != str(name):
            rename[str(name)] = ident
            notes.append(f"fsm state {name!r} renamed to identifier {ident}")
        states.append({"name": ident, "meaning": meaning})

    def _st(x: Any) -> Any:
        return rename.get(str(x), x) if x not in (None, "") else x
    styles = []
    raw_style = f.get("output_style")
    if isinstance(raw_style, dict):
        raw_style = [{"output": k, "style": v} for k, v in raw_style.items()]
    for o in raw_style or []:
        if not isinstance(o, dict):
            continue
        name = o.get("output") or o.get("name") or o.get("port")
        style = str(o.get("style") or o.get("kind") or "").strip().lower()
        if name and style in ("moore", "mealy"):
            styles.append({"output": str(name), "style": style, "note": str(o.get("note") or "")})
    trans = []
    known = {s["name"] for s in states}
    for t in f.get("transitions") or []:
        if not isinstance(t, dict):
            continue
        src = _st(t.get("state") or t.get("from") or t.get("current_state") or t.get("current"))
        dst = _st(t.get("next_state") or t.get("to") or t.get("next"))
        cond = t.get("condition")
        if cond is None:
            cond = t.get("input") if t.get("input") is not None else t.get("inputs")
        if not src or not dst:
            continue
        if str(src) not in known or str(dst) not in known:
            notes.append(f"fsm transition {src}->{dst} names an undeclared state; row dropped")
            continue
        note = t.get("note") if t.get("note") is not None else t.get("comment")
        trans.append({"state": str(src), "condition": str(cond if cond not in (None, "") else "default"),
                      "next_state": str(dst), "outputs": _as_outputs(t.get("outputs")),
                      "note": "" if note in (None, "") else str(note)})
    recov = []
    for e in f.get("error_recovery") or []:
        if not isinstance(e, dict):
            continue
        st = _st(e.get("state") or e.get("enters_state") or e.get("next_state"))
        if not st or str(st) not in known:
            continue
        recov.append({"violation": str(e.get("violation") or e.get("condition") or ""), "state": str(st),
                      "outputs": str(e.get("outputs") or ""), "resumes": str(e.get("resumes") or e.get("recovery") or "")})
    reset_state = _st(f.get("reset_state") or f.get("initial_state") or f.get("start_state"))
    if not states or not trans or not reset_state or str(reset_state) not in known:
        d.pop("fsm", None)
        notes.append("fsm section was incomplete (states, transitions or reset_state); dropped — the contract keeps only its prose")
        return
    d["fsm"] = {"reset_state": str(reset_state), "states": states, "output_style": styles,
                "transitions": trans, "error_recovery": recov}


def _coerce_update_rules(d: dict[str, Any], notes: list[str]) -> None:
    raw = d.get("update_rules")
    if isinstance(raw, dict):
        raw = [{"state_element": k, "priority": v} for k, v in raw.items()]
    if not isinstance(raw, list):
        d.pop("update_rules", None)
        return
    rules = []
    for r in raw:
        if not isinstance(r, dict):
            continue
        name = r.get("state_element") or r.get("state") or r.get("name") or r.get("signal")
        pri = r.get("priority") or r.get("rules") or r.get("order")
        if isinstance(pri, str):
            pri = [p.strip() for p in re.split(r"\s*(?:>|then|,)\s*", pri) if p.strip()]
        if not name or not isinstance(pri, list) or not pri:
            continue
        rules.append({"state_element": str(name), "priority": [str(p) for p in pri], "note": str(r.get("note") or "")})
    if rules:
        d["update_rules"] = rules
    else:
        d.pop("update_rules", None)


def _coerce_timing_conventions(d: dict[str, Any], notes: list[str]) -> None:
    tc = d.get("timing_conventions")
    if not isinstance(tc, dict):
        d.pop("timing_conventions", None)
        return
    tc = dict(tc)
    raw = tc.get("outputs")
    if isinstance(raw, dict):
        raw = [{"output": k, "timing": v} for k, v in raw.items()]
    outs = []
    for o in raw or []:
        if not isinstance(o, dict):
            continue
        name = o.get("output") or o.get("name") or o.get("port")
        t = str(o.get("timing") or o.get("style") or "").strip().lower()
        if t.startswith("comb"):
            t = "combinational"
        elif t.startswith("reg"):
            t = "registered"
        if name and t in ("registered", "combinational"):
            outs.append({"output": str(name), "timing": t, "when": str(o.get("when") or "")})
    tc["outputs"] = outs
    cc = str(tc.get("cascaded_carries") or "").strip().lower()
    tc["cascaded_carries"] = ("combinational" if cc.startswith("comb") else "registered" if cc.startswith("reg") else "not_applicable")
    for k in ("default_output_style", "window_start", "notes"):
        tc[k] = str(tc.get(k) or "")
    d["timing_conventions"] = tc


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
    _reconcile_clock(d, notes)
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
    _reconcile_reset(d, notes)
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
    _coerce_fsm(d, notes)
    _coerce_update_rules(d, notes)
    _coerce_timing_conventions(d, notes)
    return d, notes
