"""Deterministic, semantics-preserving normalisation of model-written Verilog before verification.

Only fixes declaration-level mistakes that tools reject outright and that carry no design intent:
  - an `output` assigned inside an `always` block is redeclared `reg`.
Every change is returned so it can be recorded in the run's event log.
"""
from __future__ import annotations

import re

LVAL_RE = re.compile(r"(?<![<>!=\w])([A-Za-z_]\w*)\s*(?:\[[^\]]*\])?\s*(?:<=|=)(?![=<>])")
COND_RE = re.compile(r"\b(?:if|case|casez|casex|while|for)\s*\((?:[^()]|\([^()]*\))*\)")
OUT_DECL_RE = re.compile(r"(\boutput\s+)(?!reg\b)(?:wire\s+)?((?:signed\s+)?(?:\[[^\]]*\]\s*)?)([A-Za-z_]\w*)")


def procedural_lvalues(src: str) -> set[str]:
    names: set[str] = set()
    for always in re.finditer(r"\balways\b", src):
        # take the block that follows: either begin...end (balanced) or a single statement
        rest = src[always.end():]
        begin = re.search(r"\bbegin\b", rest)
        semi = rest.find(";")
        if begin and (semi == -1 or begin.start() < semi):
            depth = 0
            start = begin.start()
            for token in re.finditer(r"\bbegin\b|\bend\b", rest[start:]):
                depth += 1 if token.group() == "begin" else -1
                if depth == 0:
                    body = rest[start:start + token.end()]
                    break
            else:
                body = rest[start:]
        else:
            body = rest[: semi + 1] if semi != -1 else rest
        body = COND_RE.sub(" ", body)  # drop conditions so `<=` comparisons are not mistaken for assignments
        names.update(match.group(1) for match in LVAL_RE.finditer(body))
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
