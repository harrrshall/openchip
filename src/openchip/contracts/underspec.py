"""Deterministic questions the request itself does not answer.

Intake currently invents a default for every consequential gap and leaves `unresolved` empty
(54 of 57 recorded false acceptances; `docs/research/false-acceptance-analysis.md` §6). These
patterns fire only when the request does not determine an observable behaviour. A prompt that
is clear — even if a hidden testbench wants the opposite — is not underspecified.
"""
from __future__ import annotations

import re

INDEX_THEN_AND_SO = re.compile(
    r"(\b[A-Za-z_]\w*)\[(\d+)\].{0,200}?\1\[(\d+)\].{0,80}and so (?:on|in)\b",
    re.I | re.S,
)
STOP_BIT_RECOVERY = re.compile(
    r"wait\s+until\s+it\s+finds\s+a\s+stop\s+bit\s+before\s+attempting\s+to\s+receive\s+the\s+next\s+byte",
    re.I,
)
TWELVE_HOUR = re.compile(r"12-hour clock", re.I)
HAS_PM = re.compile(r"\bpm\b", re.I)
NAMED_PM_INSTANT = re.compile(r"11:59|\bnoon\b|\bmidnight\b|pm (?:toggles|flips|changes)|toggles when", re.I)
SAT_COUNTERS = re.compile(r"saturating counters?", re.I)
COUNTER_RESET_VALUE = re.compile(
    r"(?:counters?|PHT|pattern history table).{0,80}reset(?:s|ted)? to"
    r"|reset(?:s|ted)? to.{0,80}(?:counters?|PHT|pattern history)",
    re.I | re.S,
)


def underspec_questions(request: str) -> list[str]:
    """Questions only the user can answer, or empty if the request determines the behaviour."""
    if not request or not request.strip():
        return []
    out: list[str] = []
    m = INDEX_THEN_AND_SO.search(request)
    if m:
        bus = m.group(1)
        out.append(
            f"the request lists `{bus}[{m.group(2)}]` and `{bus}[{m.group(3)}]` then says "
            f"\"and so on\"; it does not state the rest of the index mapping"
        )
    if STOP_BIT_RECOVERY.search(request):
        out.append(
            "the request says the FSM must wait until it finds a stop bit before the next byte, "
            "but does not say whether `done` is asserted on that recovered stop bit"
        )
    if TWELVE_HOUR.search(request) and HAS_PM.search(request) and not NAMED_PM_INSTANT.search(request):
        out.append(
            "the request is a 12-hour clock with a `pm` port but never names the instant "
            "`pm` toggles (11:59:59 → 12:00:00 vs 12:59:59 → 1:00)"
        )
    if SAT_COUNTERS.search(request) and not COUNTER_RESET_VALUE.search(request):
        out.append(
            "the request describes a table of saturating counters and a reset, but never states "
            "the counters' reset value"
        )
    return out
