"""Deterministic, semantics-preserving normalisation of model-written Verilog before verification.

Only fixes declaration-level mistakes that tools reject outright and that carry no design intent:
  - an `output` (or internal `wire`) that is assigned inside an `always` block is redeclared `reg`.
Every change is returned so it can be recorded in the run's event log.
"""
from __future__ import annotations

import re

ALWAYS_RE = re.compile(r"\balways\b[^;]*?\bbegin\b(.*?)\bend\b|\balways\b[^;]*?\n\s*([^;]*;)", re.S)
LVAL_RE = re.compile(r"(?<![<>!=\w])([A-Za-z_]\w*)\s*(?:\[[^\]]*\])?\s*(?:<=|=)(?![=<>])")
COND_RE = re.compile(r"\b(?:if|case|casez|casex|while|for)\s*\((?:[^()]|\([^()]*\))*\)")
OUT_DECL_RE = re.compile(r"(\boutput\s+)(?!reg\b)(?:wire\s+)?((?:signed\s+)?(?:\[[^\]]*\]\s*)?)([A-Za-z_]\w*)")


def procedural_lvalues(src: str) -> set[str]:
    names: set[str] = set()
    for m in re.finditer(r"\balways\b", src):
        # take the block that follows: either begin...end (balanced) or a single statement
        rest = src[m.end():]
        b = re.search(r"\bbegin\b", rest)
        semi = rest.find(";")
        if b and (semi == -1 or b.start() < semi):
            depth = 0
            i = b.start()
            for t in re.finditer(r"\bbegin\b|\bend\b", rest[i:]):
                depth += 1 if t.group() == "begin" else -1
                if depth == 0:
                    body = rest[i:i + t.end()]
                    break
            else:
                body = rest[i:]
        else:
            body = rest[: semi + 1] if semi != -1 else rest
        body = COND_RE.sub(" ", body)  # drop conditions so `<=` comparisons are not mistaken for assignments
        for lv in LVAL_RE.finditer(body):
            names.add(lv.group(1))
    return names


def normalize_rtl(src: str) -> tuple[str, list[str]]:
    changes: list[str] = []
    lvals = procedural_lvalues(src)
    if not lvals:
        return src, changes

    def fix(m: re.Match) -> str:
        name = m.group(3)
        if name in lvals:
            changes.append(f"output {name}: declared reg (assigned in an always block)")
            return f"{m.group(1)}reg {m.group(2)}{name}"
        return m.group(0)

    out = OUT_DECL_RE.sub(fix, src)
    return out, changes


# -- module header ---------------------------------------------------------------------------
# The interface gate compares the delivered module's own port list with the contract's, so the
# reader below never repairs anything: it reports the ports exactly as the model wrote them.

PORT_KEYWORDS = frozenset({"input", "output", "inout", "reg", "wire", "logic", "signed", "tri",
                           "integer", "genvar", "parameter", "localparam", "supply0", "supply1"})
IDENT_TOKEN_RE = re.compile(r"[A-Za-z_]\w*")


def strip_comments(src: str) -> str:
    src = re.sub(r"//[^\n]*", " ", src)
    return re.sub(r"/\*.*?\*/", " ", src, flags=re.S)


def _balanced(text: str, start: int, open_ch: str, close_ch: str) -> tuple[str, int] | None:
    """Contents of the group beginning at `text[start] == open_ch`, and the index just past it."""
    if start >= len(text) or text[start] != open_ch:
        return None
    depth = 0
    for i in range(start, len(text)):
        if text[i] == open_ch:
            depth += 1
        elif text[i] == close_ch:
            depth -= 1
            if depth == 0:
                return text[start + 1:i], i + 1
    return None


def _split_top_level(text: str) -> list[str]:
    parts, depth, cur = [], 0, []
    for ch in text:
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    parts.append("".join(cur))
    return [p for p in (p.strip() for p in parts) if p]


def module_ports(src: str, module_name: str) -> list[str] | None:
    """Port names in the header of `module module_name`, in order. None when it is not found.

    Handles both the Verilog-2001 ANSI header (`module m(input clk, output reg [2:0] q);`) and the
    older form (`module m(clk, q); input clk; output [2:0] q;`): in both, the header names every
    port, which is what the interface gate compares.
    """
    code = strip_comments(src)
    m = re.search(rf"\bmodule\s+{re.escape(module_name)}\b", code)
    if m is None:
        return None
    i = m.end()
    while i < len(code) and code[i].isspace():
        i += 1
    if i < len(code) and code[i] == "#":  # parameter block
        j = i + 1
        while j < len(code) and code[j].isspace():
            j += 1
        grp = _balanced(code, j, "(", ")")
        if grp is None:
            return None
        i = grp[1]
        while i < len(code) and code[i].isspace():
            i += 1
    if i < len(code) and code[i] == ";":
        return []
    grp = _balanced(code, i, "(", ")")
    if grp is None:
        return None
    names: list[str] = []
    for item in _split_top_level(grp[0]):
        item = re.sub(r"\[[^\]]*\]", " ", item)  # widths and bit selects carry no port name
        item = re.sub(r"=.*$", " ", item)
        tokens = [t for t in IDENT_TOKEN_RE.findall(item) if t not in PORT_KEYWORDS]
        if not tokens:
            return None
        names.append(tokens[-1])
    return names
