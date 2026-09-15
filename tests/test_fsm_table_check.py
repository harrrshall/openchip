"""A reference that offsets the contract's own transition table by a cycle must not be signed off.

The measured failure (docs/research/false-acceptance-analysis.md §5, Prob089_ece241_2014_q5a): the
reference model and the RTL are both written from the contract, so a Mealy-vs-Moore misreading lands
in both and simulation sees no disagreement. The contract's transition table is the one statement
that can be replayed against the reference.
"""
import json

from openchip.contracts.schema import Contract
from openchip.reporting.report import sign_off_withheld
from openchip.verification.fsmcheck import (build_probes, check_reference_against_fsm,
                                            input_blind_message, input_blind_states)

# Serial 2's complementer, LSB first: copy bits up to and including the first 1, invert after it.
# z is Mealy: in state A it is x, in state B it is the complement of x.
MEALY_REFERENCE = """
class Reference:
    def __init__(self, params):
        self.state = "A"
    def reset(self):
        self.state = "A"
    def step(self, inputs):
        x = inputs["x"] & 1
        z = x if self.state == "A" else (1 - x)
        if self.state == "A" and x:
            self.state = "B"
        return {"z": z}
"""

# The same machine with z registered: every output arrives one cycle late.
LAGGING_REFERENCE = """
class Reference:
    def __init__(self, params):
        self.state = "A"
        self.z = 0
    def reset(self):
        self.state = "A"
        self.z = 0
    def step(self, inputs):
        out = {"z": self.z}
        x = inputs["x"] & 1
        self.z = x if self.state == "A" else (1 - x)
        if self.state == "A" and x:
            self.state = "B"
        return out
"""


def comp2_contract() -> Contract:
    return Contract.model_validate({
        "module_name": "comp2",
        "purpose": "Serial two's complementer, least significant bit first.",
        "ports": [
            {"name": "clk", "direction": "input", "width": 1, "role": "clock", "timing": "n/a"},
            {"name": "rst", "direction": "input", "width": 1, "role": "reset", "timing": "n/a"},
            {"name": "x", "direction": "input", "width": 1, "role": "data", "timing": "n/a"},
            {"name": "z", "direction": "output", "width": 1, "role": "data", "timing": "combinational"},
        ],
        "clock_reset": {"clock": "clk", "reset": "rst"},
        "behavior": ("The machine reads x one bit per cycle, least significant bit first, and produces the two's "
                     "complement on z in the same cycle. Before the first 1 has been seen the output copies the "
                     "input; from the bit after the first 1 onwards the output is the complement of the input. "
                     "Reset returns the machine to the copying state. z is combinational: it is a function of the "
                     "current state and the current x, so it is valid in the same cycle as the bit it answers."),
        "requirements": [{"id": "R001", "text": "z carries the two's complement of the serial input x.",
                          "source": "user_text"}],
        "fsm": {
            "reset_state": "A",
            "states": [{"name": "A", "meaning": "No 1 seen yet: copy the input."},
                       {"name": "B", "meaning": "The first 1 has been seen: invert from now on."}],
            "output_style": [{"output": "z", "style": "mealy"}],
            "transitions": [
                {"state": "A", "condition": "x == 0", "next_state": "A", "outputs": {"z": "0"}},
                {"state": "A", "condition": "x == 1", "next_state": "B", "outputs": {"z": "1"}},
                {"state": "B", "condition": "x == 0", "next_state": "B", "outputs": {"z": "1"}},
                {"state": "B", "condition": "x == 1", "next_state": "B", "outputs": {"z": "0"}},
            ],
        },
        "timing_conventions": {"default_output_style": "outputs are Moore and registered unless the request says otherwise",
                               "outputs": [{"output": "z", "timing": "combinational", "when": "in the same cycle as the input bit"}]},
    })


def test_reference_that_lags_the_transition_table_is_caught_and_withheld(tmp_path):
    contract = comp2_contract()

    good = tmp_path / "good.py"
    good.write_text(MEALY_REFERENCE)
    ok = check_reference_against_fsm(contract, good, tmp_path / "w1")
    assert ok["status"] == "ok", ok
    assert ok["probes"] == 4 and ok["checks"] == 4, ok
    assert not sign_off_withheld({"fsm_table_check": ok})

    bad = tmp_path / "bad.py"
    bad.write_text(LAGGING_REFERENCE)
    res = check_reference_against_fsm(contract, bad, tmp_path / "w2")
    assert res["status"] == "mismatch", res
    assert any(m["state"] == "A" and m["table_says"] == 1 and m["reference_says"] == 0 for m in res["mismatches"]), res
    withheld = sign_off_withheld({"fsm_table_check": res})
    assert "state-transition table" in withheld and "z=1" in withheld


def test_a_state_that_never_samples_a_sampled_input_is_rejected_at_intake():
    """The measured `seq_detect` false acceptance: the 1011 detector's MATCH state carried the single
    row `default -> GOT1`, so the bit sampled during the match cycle was dropped and overlapping
    detection was lost. The reference was written from the same table, so the table check agreed and
    simulation passed (evals/results/final-2026-09-14/.../heldout-v1-*/seq_detect/rep0).
    """
    base = {
        "module_name": "seq_detect",
        "purpose": "Overlapping 1011 sequence detector.",
        "ports": [
            {"name": "clk", "direction": "input", "width": 1, "role": "clock", "timing": "n/a"},
            {"name": "rst", "direction": "input", "width": 1, "role": "reset", "timing": "n/a"},
            {"name": "din", "direction": "input", "width": 1, "role": "data", "timing": "n/a"},
            {"name": "det", "direction": "output", "width": 1, "role": "data", "timing": "registered"},
        ],
        "clock_reset": {"clock": "clk", "reset": "rst"},
        "behavior": ("One bit din is sampled at every rising clock edge. det is a registered output: it becomes 1 at "
                     "the edge at which the fourth bit of a 1 0 1 1 sequence is sampled, and 0 otherwise, so det is 1 "
                     "during the cycle after that edge. Matches may overlap: after a match the last bits stay part of "
                     "the history. After reset the history is empty and det is 0."),
        "requirements": [{"id": "R001", "text": "Detect 1011 on din, overlapping matches allowed.",
                          "source": "user_text", "acceptance": "golden"}],
        "fsm": {
            "reset_state": "IDLE",
            "states": [{"name": n, "meaning": n} for n in ("IDLE", "GOT1", "GOT10", "GOT101", "MATCH")],
            "output_style": [{"output": "det", "style": "moore"}],
            "transitions": [
                {"state": "IDLE", "condition": "din == 1", "next_state": "GOT1", "outputs": {"det": "0"}},
                {"state": "IDLE", "condition": "default", "next_state": "IDLE", "outputs": {"det": "0"}},
                {"state": "GOT1", "condition": "din == 0", "next_state": "GOT10", "outputs": {"det": "0"}},
                {"state": "GOT1", "condition": "din == 1", "next_state": "GOT1", "outputs": {"det": "0"}},
                {"state": "GOT10", "condition": "din == 1", "next_state": "GOT101", "outputs": {"det": "0"}},
                {"state": "GOT10", "condition": "default", "next_state": "IDLE", "outputs": {"det": "0"}},
                {"state": "GOT101", "condition": "din == 1", "next_state": "MATCH", "outputs": {"det": "0"}},
                {"state": "GOT101", "condition": "din == 0", "next_state": "GOT10", "outputs": {"det": "0"}},
                {"state": "MATCH", "condition": "default", "next_state": "GOT1", "outputs": {"det": "1"}},
            ],
        },
    }
    contract = Contract.model_validate(base)
    found = input_blind_states(contract, contract.fsm)
    assert [(f["state"], f["input"]) for f in found] == [("MATCH", "din")]
    assert "MATCH" in input_blind_message(found) and "din" in input_blind_message(found)

    # The stimulus drives the value the table never distinguishes, so it is on the record.
    probes, unexercised = build_probes(contract, contract.fsm)
    assert unexercised == {}
    assert {p.rows[-1]["din"] for p in probes if p.state == "MATCH"} == {0, 1}

    # Splitting the row by din, as the request requires, clears the finding.
    fixed = json.loads(json.dumps(base))
    fixed["fsm"]["transitions"][-1:] = [
        {"state": "MATCH", "condition": "din == 1", "next_state": "GOT1", "outputs": {"det": "1"}},
        {"state": "MATCH", "condition": "din == 0", "next_state": "GOT10", "outputs": {"det": "1"}},
    ]
    fixed_contract = Contract.model_validate(fixed)
    assert input_blind_states(fixed_contract, fixed_contract.fsm) == []

    # So does an explicit note claiming the request ignores din there.
    noted = json.loads(json.dumps(base))
    noted["fsm"]["transitions"][-1]["note"] = "the request says din is ignored during the match cycle"
    noted_contract = Contract.model_validate(noted)
    assert input_blind_states(noted_contract, noted_contract.fsm) == []
