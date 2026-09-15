"""Triage of the intake's `unresolved` list before the sign-off gate.

An `unresolved` item is a question the delivery puts to the user, so it has to be worth asking:
it must change the observable behaviour at the ports, and the request must not already answer it.
Measured on `evals/results/matrix-v1/20260913-141011`, deepseek-v4-flash instead files the answer
itself as a question ("... is not stated; it is implemented as a synchronous reset ... matching
'active high synchronous reset'"), which made 53 to 61 of 78 accepted designs `provisional` and
buried the few genuinely open questions.

This module scores each item from its own text and demotes the ones that answer themselves. A
demoted item is kept in the contract as an `assumption` carrying the rule that demoted it, so
nothing is lost and a reviewer can audit every demotion in `reports/outcome.json`.

The sign-off gate itself (ADR 0012, `contracts/underspec.py`) is untouched: it reads the request
text, not this list, and an item that survives triage still makes the result provisional.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------------------------
# Signals. Every pattern below is a statement the item makes about ITSELF: that the request
# already decided it, that it is not about this module's ports, or that a documented convention
# decides it. None of them look at the request text.
# ---------------------------------------------------------------------------------------------

# "the request only says X" / "the request does not say X" is the opposite claim: the request is
# named as the thing that fails to decide. It suppresses the settled-by-request signals, except a
# quoted fragment of the request, which decides the question whatever else the sentence says.
_ONLY_SAYS = re.compile(
    r"request only (?:says|states|specifies|gives)"
    r"|(?:request|it) (?:does not|doesn'?t|never|did not) (?:say|state|specify|determine|define)",
    re.I,
)
_QUOTES_REQUEST = re.compile(r"matching\s*['\"‘]|interpretation of\s*['\"‘]|wording\s*['\"‘]", re.I)

SETTLED = [
    (r"matching\s*['\"‘]|matching (?:the|its) (?:request|stated|given|specified|literal)",
     "the item quotes the request wording that decides it"),
    (r"interpretation of\s*['\"‘]|\b(?:request'?s?|user'?s?) (?:wording|phrase|instruction)\b|\bthe wording\s*['\"‘]|\bper the .{0,20}wording\b",
     "the item quotes the request wording that decides it"),
    (r"\brequest (?:says|states|specifies|fixes|lists|names|defines|gives|already|explicitly|implies|permits|allows)",
     "the item says the request decides it"),
    (r"\bas stated\b|\bper the request\b|\bas requested\b|\bas the request\b|\bper the stated\b|\bwhat was requested\b|\bthe request as written\b|\bthe request literally\b|\bhonou?r the request\b",
     "the item says the request decides it"),
    (r"\b(?:per|as|follows) the (?:stated|requested|given|literal|user'?s?) (?:request|interface|port list|ranges?|examples?|mapping|order|instruction|text|description)",
     "the item says the request decides it"),
    (r"\bthe stated (?:examples?|interface|ranges?|mapping|order|request|wording|description)",
     "the item says the request decides it"),
    (r"\bexamples? (?:fix|fixes|force|forces)\b|\bexplicit example\b|\bstated example",
     "the request's examples decide it"),
    (r"\b(?:supplied|given|printed|stated) (?:table|waveform|port list|interface|diagram|map)|\bkarnaugh map\b|\bk-?map\b|\btruth table\b|\bprinted order\b",
     "the request's own table, waveform or map decides it"),
    (r"\b(?:table|waveform|diagram|map) (?:shows|show|forces|fixes|indicates|unambiguously|supports)|\bimplied by the\b|\bis implied by\b|\bin the diagram\b",
     "the request's own table, waveform or map decides it"),
    (r"\bwhich was chosen\b|\bwas followed\b|\bwhat (?:this|the) contract (?:implements|specifies|does)\b",
     "the item records the choice the request already fixed"),
    (r"\bthe (?:requested|stated|given) interface\b|\bthe port list\b|\bin the interface\b|\bthe interface (?:has|lists|exposes|contains|exists)\b|\bfollows the literal interface\b",
     "the request's port list decides it"),
    (r"\b(?:names?|lists?|specifies) no (?:clock|reset|parameters?|ports?)\b|\bno clock\b[^.;]{0,40}\b(?:is|was|in|exists|intended|port)\b|\bhas no clock\b|\binterface has no\b|\bdoes not (?:ask for|mention|include|contain|name|list|request) (?:a |an |any )?(?:clock|reset|parameter|port|enable|valid|handshake)\b|\bno (?:clock|reset)(?:/reset)? was specified\b",
     "the request's port list decides it"),
    (r"\bpermits any value\b|\bfree choice\b|\bdon'?t[- ]care",
     "the request leaves the value free, so any choice satisfies it"),
    (r"\bnot requested\b|\bnone (?:is|was) (?:added|provided|included)\b|\bso (?:it|none|no .{0,24}) is (?:omitted|dropped|discarded|added|provided)\b|\bno .{0,30}(?:ports?|signals?) (?:were|was) requested\b",
     "the request did not ask for it, so it is out of the contract"),
    (r"\bpin[- ](?:to[- ]gate|mapping|grouping)\b|\bbased on the .{0,24}naming\b",
     "the request's port names decide it"),
]

# Not about this module's observable ports: a downstream or surrounding consumer, the grading
# harness, a port the request did not ask for, or a pipeline stage nobody asked for.
OUT_OF_SCOPE = [
    (r"\bdownstream\b|\bupstream\b|\bparent module\b|\bconsumer\b|\bsurrounding (?:system|shift register|logic|circuit)\b|\blarger (?:system|memory|circuit|shift)\b|\bwider\b.{0,40}\b(?:system|register|circuit|design|module)\b|\bcontains this stage\b",
     "the item is about a consumer outside this module"),
    (r"\bout of scope\b|\bfor reuse\b|\bin the future\b|\bfor a specific pipeline\b|\bfor integration\b|\blater stage\b|\bplaceholder\b",
     "the item is outside the scope of this request"),
    (r"\bgrader\b|\bgrading\b|\btestbench\b|\btest collateral\b|\bchecker (?:uses|expects|requires)\b|\bfor acceptance\b",
     "the item is about the grading harness, not the design"),
    (r"\badditional (?:port|output|input|ports)\b|\bextra (?:port|output|input)\b|\bseparate output\b|\bexpos(?:e|es|ed|ing)\b.{0,40}\b(?:output|port|word)\b|\bon an output port\b",
     "the item proposes a port the request did not ask for"),
    (r"\bpipeline stage\b|\bone[- ]cycle latency\b|\bone cycle of latency\b|\bclocked/registered version\b|\bregistered variant\b|\bregistered on an optional clock\b|\bpipelined\b",
     "the item proposes a pipeline stage the request did not ask for"),
    (r"\bnone exists\b|\bnot applicable\b|\balready covered\b|\bmoot\b|\bno such\b|\bit is automatically\b",
     "the item answers itself: the design has nothing of the kind"),
]

# The alternatives the item names are indistinguishable at the ports.
NOT_OBSERVABLE = [
    (r"identical observable|functionally (?:equivalent|identical)|behaviou?rally identical|both (?:produce|give|are) identical|no functional impact|purely cosmetic|not observable|no observable effect|no impact on (?:logical |observable )?behaviou?r|style choice|no effect on the|is unaffected",
     "the alternatives are indistinguishable at the ports"),
    (r"\bstructural\b.{0,90}\b(?:behaviou?ral|dataflow|continuous assignment)|\b(?:behaviou?ral|dataflow|continuous assignment)\b.{0,90}\bstructural\b|\bgate primitive|\bgate-level\b|\bassign\b.{0,24}\bstyle\b|\bwire\b.{0,40}\breg\b|\bminimi[sz]ed\b|\bsum[- ]of[- ](?:products|minterms)\b|\bintermediate[- ]wire\b|\bintermediate wires?\b|\binternal .{0,24}names\b|\bsensitivity list\b|\bcase statement\b",
     "the item is an RTL coding style with the same port behaviour"),
    (r"\bstate encodings?\b|\bencodings? of the .{0,24}states\b|\bstate codes?\b|\bbinary encoding\b|\bdiscrete flip-flop|\bpreserved individually\b|\bmerged by the synthesi",
     "internal encoding or structure is not observable at the ports"),
    (r"\bunused (?:states?|state encodings?)\b|\bunspecified states?\b|\bunreachable\b|\bstates? 101\b|\brecovery transitions?\b",
     "states the reset state cannot reach do not change what the ports do"),
]

# Reset synchroniser internals: a clock-domain question about the reset input, never a question
# about what this module computes.
SYNCHRONIZER = [
    (r"(?:reset|areset|aresetn|\brst\b)[^.]{0,70}synchroni[sz]|synchroni[sz][^.]{0,70}(?:reset|areset|aresetn|\brst\b|deassert)|metastab|two[- ]flop|reset[- ]release|synchronously deassert|asynchronous[- ]assert|deassertion",
     "reset synchroniser internals are a clock-domain concern, not port behaviour"),
]

# Delay, drive, technology and simulation-only modelling: not part of a functional RTL contract.
TIMING_MODEL = [
    (r"propagation delay|drive strength|delay model|zero[- ]delay|timing constraint|technology mapping|process library|open[- ]collector|glitch|min/typ/max|timing closure|output load|pin[- ]level|electrical characteristic|74[a-z]{0,2}\d{2,}|placement information|synthesis attribute|x/z|4-state|simulation-only|simulation convenience|for simulation\b",
     "delay, drive, technology and simulation-only modelling are outside a functional RTL contract"),
]

# Parameterisation the request did not ask for.
PARAMETERIZATION = [
    (r"parameteri[sz](?:e|ed|able|ation|ing)|\bgenerali[sz]ed to\b",
     "the request names no parameter, so a parameterised variant is out of scope"),
]

# ---------------------------------------------------------------------------------------------
# Documented project conventions (also listed in the intake prompt). Each is (what the item is
# about, which choice the convention makes, the note). A convention with a specific choice
# demotes only when the contract took that choice: an intake that departed from the convention is
# asking a real question.
# ---------------------------------------------------------------------------------------------
_ANY = r"."
_ZERO = r"\b0\b|\bzero\b|\d*'[bBhHdD]0+\b|all[- ]zero|\b0000\b|cleared to 0|\bx\b|undefined"
# A table, memory or array of counters is not "the state" the reset convention speaks about: its
# initial value is a design decision (a predictor bias, a lookup content), so the two reset-value
# conventions below stand aside for it. This is what keeps Prob153's PHT reset value a question.
_TABLE_STATE = re.compile(r"\bpht\b|pattern history|\btable\b|\bentries\b|\bmemory\b|\barray\b|\bram\b|register file|\bcounters\b", re.I)
CONVENTIONS = [
    (r"reset\b.{0,70}(?:polarity|active[- ]low)|(?:polarity|active[- ]low).{0,70}\breset",
     r"active[- ]high",
     "project convention: a reset is active high and synchronous unless the request says otherwise"),
    (r"reset value|resets? to|reset[- ]to|value of .{0,24} (?:after|on) reset",
     _ZERO,
     "project convention: state resets to 0 unless the request gives another value"),
    (r"reset\b.{0,70}\bclear|clear(?:s|ing|ed)?\b.{0,40}\breset",
     r"clear(?:ing|s|ed)? (?:both|it|them|the|all)|" + _ZERO,
     "project convention: reset clears state and outputs to 0"),
    (r"power[- ]up|\binitial\b|start[- ]up|at time 0|before the first clock|initiali[sz]|before any reset|reset is never asserted|never asserted",
     _ANY,
     "project convention: an unreset register initialises to 0"),
    (r"priority|both (?:are )?(?:asserted|high|1)\b|simultaneous",
     r"\bload\b|\bl\s+over\s+e\b|\bl=1\b|\breset\b[^.;]{0,40}\bpriority\b|\bpriority\b[^.;]{0,40}\breset\b|priority over the enable|reset (?:wins|beats|dominates)",
     "project convention: load beats enable, and reset beats both"),
    (r"registered|combinational",
     r"\bmoore\b|state (?:bit|decode|register|machine)|\bfsm\b|\bmealy\b",
     "project convention: a Moore output is decoded from the current state with no extra output register"),
    (r"\boutputs?\b|\bout\b",
     r"\bregistered\b[^.;]{0,90}\bcombinational\b|\bcombinational\b[^.;]{0,90}\bregistered\b",
     "project convention: outputs are registered unless the request describes them as a function of the current inputs"),
    (r"endian|bit[- ]order|vector range|word[- ]order|slice order|bit ordering|\bmsb\b.{0,40}\blsb\b",
     r"little[- ]endian|\[\s*\d+\s*:\s*0\s*\]|as indexed|\blsb\b|default",
     "project convention: packed vectors are little endian, indexed as declared"),
    (r"rising edge|posedge|falling[- ]edge|dual[- ]edge",
     r"only the rising edge|rising[- ]edge (?:of \w+ )?(?:is|was|were) (?:used|chosen|assumed)|posedge (?:is|was) (?:used|chosen|assumed)",
     "project convention: a design is rising-edge clocked unless the request describes otherwise"),
    (r"\bconvention(?:al|s)?\b|\bstandard (?:template|practice|synthesis)\b",
     _ANY,
     "the item calls its own answer a convention, so it is a default and not a question"),
]

# The item states an observable consequence of the choice, or is a deterministic guard finding.
# Such an item is never demoted by a convention.
KEEP = re.compile(
    r"\bthis changes\b|\bwould change the (?:observable|behaviou?r|value|result|prediction|function|cycle|first)"
    r"|\bchanges the (?:first|cycle-accuracy|observable|behaviou?r|prediction)"
    r"|\binternally inconsistent\b|\breasoning fragments\b|\bthe intake was unsure\b",
    re.I,
)

_GROUPS = [
    ("settled_by_request", SETTLED),
    ("out_of_scope", OUT_OF_SCOPE),
    ("not_observable", NOT_OBSERVABLE),
    ("synchronizer_internals", SYNCHRONIZER),
    ("timing_model", TIMING_MODEL),
    ("parameterization", PARAMETERIZATION),
]

DEMOTE_THRESHOLD = 1.0


@dataclass
class Verdict:
    """One unresolved item after triage. `score >= DEMOTE_THRESHOLD` means it answers itself."""

    text: str
    score: float
    rule: str = ""
    note: str = ""

    @property
    def demoted(self) -> bool:
        return self.score >= DEMOTE_THRESHOLD

    def assumption(self) -> str:
        return f"{self.text} [triage: {self.note}]"


@dataclass
class Triage:
    kept: list[str] = field(default_factory=list)
    demoted: list[Verdict] = field(default_factory=list)

    def records(self) -> list[dict]:
        return [{"text": v.text, "rule": v.rule, "note": v.note, "score": round(v.score, 2)} for v in self.demoted]


def score_unresolved(item: str) -> Verdict:
    """Score one unresolved item from its own text."""
    text = " ".join((item or "").split())
    if not text:
        return Verdict(text, 0.0)
    suppress_settled = bool(_ONLY_SAYS.search(text)) and not _QUOTES_REQUEST.search(text)
    for rule, patterns in _GROUPS:
        if rule == "settled_by_request" and suppress_settled:
            continue
        for pat, note in patterns:
            if re.search(pat, text, re.I):
                return Verdict(text, 1.0, rule, note)
    if not KEEP.search(text):
        table = bool(_TABLE_STATE.search(text))
        for context, choice, note in CONVENTIONS:
            if table and "resets to 0" in note or table and "initialises to 0" in note:
                continue
            if re.search(context, text, re.I) and re.search(choice, text, re.I):
                return Verdict(text, 1.0, "convention", note)
    return Verdict(text, 0.0)


def triage_unresolved(items: list[str]) -> Triage:
    """Split `unresolved` into the questions worth asking and the ones that answer themselves."""
    out = Triage()
    for item in items or []:
        v = score_unresolved(item)
        if v.demoted:
            out.demoted.append(v)
        else:
            out.kept.append(" ".join(item.split()))
    return out
