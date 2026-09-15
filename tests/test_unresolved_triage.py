"""An `unresolved` item that answers itself must not withhold sign-off, and a real one must.

Every string below is verbatim from a recorded deepseek-v4-flash run in
`evals/results/matrix-v1/20260913-141011`, where 53 of 78 accepted designs were marked
provisional by questions the request had already answered.
"""
from openchip.contracts.triage import triage_unresolved

# Answered by the request, by the port list, or by a documented convention.
SELF_ANSWERING = [
    # Prob041_dff8r: the request says "active high synchronous reset".
    "Whether the reset must be synchronized internally is not stated; it is implemented as a "
    "synchronous reset sampled directly at the positive clk edge, matching 'active high synchronous reset'.",
    # Prob021_mux256to1v: the request's own examples fix the slice order.
    "Whether the user wants the 4-bit slices interpreted in big-endian order (sel=0 as the most-significant "
    "4 bits) — the stated examples fix little-endian, i.e. sel=0 is in[3:0], which was chosen.",
    # Prob021_mux256to1v: a question about somebody else's module.
    "Whether `in`'s word-endianness or bit ordering matters for a downstream consumer (e.g. a systolic array "
    "or UART packing), which would be handled by the parent module, not here.",
    # Prob073_dff16e: the reset-to-zero convention.
    "Whether the reset value of q should be 16'h0000 (chosen default) or some other constant such as "
    "all-ones; the request only says the reset is synchronous and active-low.",
    # Prob109_fsm1: the Moore-output convention.
    "Confirm that `out` should be combinational rather than registered; if a one-cycle registered output "
    "is desired, that changes the observed timing.",
]

# Prob153_gshare: the request describes a table of saturating counters and a reset but never
# gives the counters' reset value, which changes the first prediction at every index.
REALLY_OPEN = (
    "Confirm the PHT reset value: 2'b00 (strongly not taken, assumed) versus 2'b10 (weakly taken) versus "
    "2'b01 (weakly not taken). This changes the first prediction after reset for every index."
)


def test_triage_demotes_self_answering_questions_and_keeps_open_ones():
    t = triage_unresolved(SELF_ANSWERING + [REALLY_OPEN])
    assert t.kept == [REALLY_OPEN], t.kept
    assert [d.text for d in t.demoted] == [" ".join(s.split()) for s in SELF_ANSWERING]
    # Nothing is lost: each demotion carries the rule and the reason into the assumptions.
    assert all(d.rule and d.note and d.text in d.assumption() for d in t.demoted)
    assert {d.rule for d in t.demoted} <= {"settled_by_request", "out_of_scope", "not_observable",
                                           "synchronizer_internals", "timing_model", "parameterization",
                                           "convention"}
