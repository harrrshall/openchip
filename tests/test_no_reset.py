"""A clocked design with no reset must be representable and verifiable end to end.

VerilogEval Prob053_m2014_q4d ("a D flip-flop ... there is no reset") failed intake for every model
in every recorded run because `clock_reset.reset` was mandatory. These tests exercise the real path:
contract -> testbench -> iverilog/vvp simulation against the reference model.
"""
import json

import pytest

from openchip.config import Config
from openchip.contracts.coerce import coerce_contract
from openchip.contracts.schema import Contract
from openchip.verification.harness import verify
from openchip.verification.testbench import generate_testbench

CONTRACT = {
    "module_name": "dff_bare",
    "purpose": "A D flip-flop with no reset.",
    "ports": [
        {"name": "clk", "direction": "input", "width": 1, "role": "clock", "timing": "n/a", "description": "clock"},
        {"name": "in", "direction": "input", "width": 1, "role": "data", "timing": "n/a", "description": "data in"},
        {"name": "out", "direction": "output", "width": 1, "role": "data", "timing": "registered", "description": "data out"},
    ],
    "clock_reset": {"clock": "clk", "clock_edge": "posedge", "reset": None},
    "behavior": ("A single D flip-flop positive-edge triggered by clk. There is no reset port: the flip-flop "
                 "powers up at 0 and is never forced back to it. At every rising edge of clk, out takes the "
                 "value of in sampled just before that edge; between edges out holds its value."),
    "requirements": [{"id": "R001", "text": "out takes in at every posedge clk", "source": "user_text"}],
}

GOOD_RTL = "module dff_bare (input clk, input in, output reg out);\n  initial out = 1'b0;\n  always @(posedge clk) out <= in;\nendmodule\n"
# no power-up value: `out` is X on cycle 0, which is exactly what a no-reset design must not leave undefined
UNINIT_RTL = "module dff_bare (input clk, input in, output reg out);\n  always @(posedge clk) out <= in;\nendmodule\n"
REFERENCE = (
    "class Reference:\n"
    "    def __init__(self, params):\n        self.q = 0\n"
    "    def reset(self):\n        self.q = 0\n"
    "    def step(self, inputs):\n"
    "        out = {'out': self.q}\n"
    "        self.q = inputs['in'] & 1\n"
    "        return out\n"
)


def _contract() -> Contract:
    data, _ = coerce_contract(dict(CONTRACT))
    return Contract.model_validate(data)


def test_null_reset_is_a_valid_contract():
    c = _contract()
    assert c.clock_reset is not None and c.clock_reset.reset is None
    assert not c.has_reset and not c.combinational
    assert [p.name for p in c.data_inputs()] == ["in"]
    assert "No reset port" in c.summary_md()


def test_invented_reset_is_dropped_rather_than_rejected():
    """Models keep the habitual `rst` in clock_reset while listing only the ports the request names."""
    data = dict(CONTRACT)
    data["clock_reset"] = {"clock": "clk", "reset": "rst"}
    coerced, notes = coerce_contract(data)
    assert coerced["clock_reset"]["reset"] is None
    assert any("NO RESET" in n for n in notes)
    assert Contract.model_validate(coerced).has_reset is False


def test_declared_reset_port_is_adopted_when_clock_reset_omits_it():
    data = dict(CONTRACT)
    data["ports"] = CONTRACT["ports"] + [
        {"name": "areset", "direction": "input", "width": 1, "role": "reset", "timing": "n/a", "description": "async reset"}]
    data["clock_reset"] = {"clock": "clk", "reset": None}
    coerced, notes = coerce_contract(data)
    assert coerced["clock_reset"]["reset"] == "areset" and notes


def test_testbench_never_mentions_a_reset_port():
    import re
    tb = generate_testbench(_contract(), 20)
    code = re.sub(r"//.*", "", tb)          # the comment explains the missing reset; the code must not use one
    assert "rst" not in code and "reset" not in code.lower()
    assert ".clk(clk)" in code and ".in(in)" in code
    # cycle 0 is sampled before any clock edge at all, so it reads the power-up state whether the
    # DUT clocks on the rising edge, the falling edge, or is a level-sensitive latch
    assert "reg clk = 1'b0;" in code
    assert "if (i > 0) @(negedge clk);" in code


@pytest.mark.cloud
def test_no_reset_dff_verifies_against_its_reference(tmp_path):
    cfg = Config.load()
    ref = tmp_path / "ref.py"
    ref.write_text(REFERENCE)
    good = tmp_path / "dff_bare.v"
    good.write_text(GOOD_RTL)
    res = verify(_contract(), good, ref, tmp_path / "work", cfg, cycles=60, seeds=[1, 2])
    assert res.accepted, json.dumps(res.to_dict(), indent=1)[:2000]
    assert all(s["status"] == "pass" for s in res.sims)

    bad = tmp_path / "bad" / "dff_bare.v"
    bad.parent.mkdir()
    bad.write_text(UNINIT_RTL)
    res = verify(_contract(), bad, ref, tmp_path / "work_bad", cfg, cycles=60, seeds=[1])
    assert not res.accepted and any(s["status"] == "fail" for s in res.sims)
    assert "got=0xx" in res.evidence_for_model()  # undefined on cycle 0, not merely wrong


# A clocked design whose intake answered `clock_reset: null` because it has no reset. Taken literally
# that says "purely combinational", and the registered output q then fails validation with
# "a combinational contract (no clock) cannot have registered outputs" (VerilogEval Prob105_rotate100,
# Prob061_2014_q4a). The declared clock port decides instead.
ROTATOR = {
    "module_name": "TopModule",
    "purpose": "100-bit rotator with synchronous load and rotate enable.",
    "ports": [
        {"name": "clk", "direction": "input", "width": 1, "role": "clock", "timing": "n/a", "description": "clock"},
        {"name": "load", "direction": "input", "width": 1, "role": "control", "timing": "n/a", "description": "load"},
        {"name": "ena", "direction": "input", "width": 2, "role": "control", "timing": "n/a", "description": "rotate"},
        {"name": "data", "direction": "input", "width": 100, "role": "data", "timing": "n/a", "description": "load data"},
        {"name": "q", "direction": "output", "width": 100, "role": "data", "timing": "registered", "description": "register"},
    ],
    "clock_reset": None,
    "behavior": ("A 100-bit shift register with synchronous load and left/right rotate. On a rising clock edge "
                 "load takes priority: q is replaced by data. Otherwise ena selects a rotation by one bit. "
                 "There is no reset port; q powers up at 0 and is only changed by a clock edge."),
    "requirements": [{"id": "R001", "text": "load replaces q with data at the clock edge", "source": "user_text"}],
}


@pytest.mark.parametrize("clock_reset", [None, {"clock": None, "reset": None}, {"clock": "null", "reset": "null"}])
def test_a_declared_clock_port_beats_a_null_clock_reset(clock_reset):
    data = dict(ROTATOR, clock_reset=clock_reset)
    coerced, notes = coerce_contract(data)
    c = Contract.model_validate(coerced)          # used to raise "cannot have registered outputs"
    assert not c.combinational and c.clock_reset.clock == "clk"
    assert not c.has_reset                        # no reset port is declared, so there is no reset
    assert c.registered_outputs() and notes
    assert [p.name for p in c.data_inputs()] == ["load", "ena", "data"]


def test_a_design_with_no_clock_port_stays_combinational():
    data = dict(ROTATOR, clock_reset=None)
    data["ports"] = [p for p in ROTATOR["ports"] if p["name"] != "clk"]
    data["ports"] = [dict(p, timing="combinational") if p["direction"] == "output" else p for p in data["ports"]]
    c = Contract.model_validate(coerce_contract(data)[0])
    assert c.combinational and c.clock_reset is None


LATCH_CONTRACT = {
    "module_name": "TopModule",
    "purpose": "A transparent-high latch and a falling-edge register, read from a timing diagram.",
    "ports": [
        {"name": "clock", "direction": "input", "width": 1, "role": "clock", "timing": "n/a", "description": "clock"},
        {"name": "a", "direction": "input", "width": 1, "role": "data", "timing": "n/a", "description": "data in"},
        {"name": "p", "direction": "output", "width": 1, "role": "data", "timing": "registered", "description": "latch"},
        {"name": "q", "direction": "output", "width": 1, "role": "data", "timing": "registered", "description": "negedge register"},
    ],
    "clock_reset": {"clock": "clock", "clock_edge": "posedge", "reset": None},
    "behavior": ("p is a transparent latch open while clock is high: while clock is 1 it follows a, and it holds "
                 "its value while clock is 0. q is a register clocked on the FALLING edge of clock: at each 1 to 0 "
                 "transition it captures a. There is no reset port; both power up at 0."),
    "requirements": [{"id": "R001", "text": "p follows a while clock is high and holds while it is low.",
                      "source": "user_text"}],
}

LATCH_RTL = ("module TopModule (input clock, input a, output reg p = 1'b0, output reg q = 1'b0);\n"
             "  always @(*) if (clock) p = a;\n"
             "  always @(negedge clock) q <= a;\n"
             "endmodule\n")

LATCH_REFERENCE = (
    "class Reference:\n"
    "    def __init__(self, params):\n        self.p = 0\n        self.q = 0\n"
    "    def reset(self):\n        self.p = 0\n        self.q = 0\n"
    "    def step(self, inputs):\n"
    "        out = {'p': self.p, 'q': self.q}\n"
    "        self.p = inputs['a'] & 1\n"
    "        self.q = inputs['a'] & 1\n"
    "        return out\n"
)


@pytest.mark.cloud
def test_a_latch_and_a_negedge_register_verify_against_their_reference(tmp_path):
    """Cycle 0 must read the power-up state of a falling-edge register and a transparent latch.

    With the clock starting high, the first falling edge landed before that sample and overwrote the
    DUT's power-up value with the still-undriven inputs: correct `Prob145_circuit8` RTL reported
    `got=x` at cycle 0 through four repairs and was never accepted, though it passed the hidden
    testbench.
    """
    cfg = Config.load()
    ref = tmp_path / "ref.py"
    ref.write_text(LATCH_REFERENCE)
    rtl = tmp_path / "TopModule.v"
    rtl.write_text(LATCH_RTL)
    res = verify(Contract.model_validate(LATCH_CONTRACT), rtl, ref, tmp_path / "work", cfg, cycles=60, seeds=[1, 2])
    assert res.accepted, json.dumps(res.to_dict(), indent=1)[:2000]
