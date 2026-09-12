"""Clocked waveform dumps are traces, not combinational tables."""
from pathlib import Path

from openchip.contracts.schema import Contract
from openchip.contracts.tables import parse_clocked_waveforms, parse_request_tables, posedge_indices
from openchip.verification.tablecheck import bind_trace, check_reference_against_request_tables

PROB117 = """
 - input  clk
 - input  a
 - output q (3 bits)

The module implements a sequential circuit. Read the simulation waveforms
to determine what the circuit does, then implement it.

  time  clk a   q
  0ns   0   1   x
  5ns   1   1   4
  10ns  0   1   4
  15ns  1   1   4
  20ns  0   1   4
  25ns  1   1   4
  30ns  0   1   4
  35ns  1   1   4
  40ns  0   1   4
  45ns  1   0   4
  50ns  0   0   4
  55ns  1   0   5
  60ns  0   0   5
  65ns  1   0   6
  70ns  0   0   6
  75ns  1   0   0
  80ns  0   0   0
  85ns  1   0   1
  90ns  0   0   1
"""

PROB145 = """
 - input  clock
 - input  a
 - output p
 - output q

  time   clock   a   p   q
  0ns    0       0   x   x
  25ns   1       0   0   x
  55ns   0       0   0   0
  85ns   1       0   0   0
  90ns   1       1   1   0
  115ns  0       0   1   1
  145ns  1       0   0   1
"""

COMB_WAVE = """
 - input  a
 - input  b
 - output q

  time  a  b  q
  0ns   0  0  0
  5ns   0  1  1
  10ns  1  0  1
  15ns  1  1  0
"""


def test_clocked_dump_is_not_a_combinational_table():
    assert parse_request_tables(PROB117) == []
    assert parse_request_tables(PROB145) == []


def test_combinational_waveform_is_not_a_clocked_trace():
    assert parse_clocked_waveforms(COMB_WAVE) == []
    assert parse_request_tables(COMB_WAVE)


def test_prob117_posedge_samples():
    (tr,) = parse_clocked_waveforms(PROB117)
    assert tr.clock == "clk"
    assert tr.columns == ("clk", "a", "q")
    edges = posedge_indices(tr)
    assert edges[0] == 1
    first = dict(zip(tr.columns, tr.samples[edges[0]]))
    assert first == {"clk": 1, "a": 1, "q": 4}


def test_prob145_first_posedge_has_undefined_q():
    (tr,) = parse_clocked_waveforms(PROB145)
    assert tr.clock == "clock"
    i = posedge_indices(tr)[0]
    sample = dict(zip(tr.columns, tr.samples[i]))
    assert sample["p"] == 0 and sample["q"] is None


def test_bind_trace_needs_a_matching_clock():
    (tr,) = parse_clocked_waveforms(PROB117)
    c = Contract.model_validate({
        "module_name": "TopModule", "purpose": "seq", "behavior": "x" * 160,
        "ports": [
            {"name": "clk", "direction": "input", "width": 1, "role": "clock", "timing": "n/a"},
            {"name": "rst", "direction": "input", "width": 1, "role": "reset", "timing": "n/a"},
            {"name": "a", "direction": "input", "width": 1, "timing": "n/a"},
            {"name": "q", "direction": "output", "width": 3, "timing": "registered"},
        ],
        "clock_reset": {"clock": "clk", "reset": "rst"},
        "requirements": [{"id": "R001", "text": "Hold q while a is high then count.", "source": "user_text"}],
    })
    b = bind_trace(tr, c)
    assert b is not None
    assert b.inputs == ("a",)
    assert b.steps[0][1]["q"] == 4
    c2 = Contract.model_validate({
        "module_name": "TopModule", "purpose": "comb", "behavior": "x" * 160,
        "ports": [
            {"name": "a", "direction": "input", "width": 1, "timing": "n/a"},
            {"name": "q", "direction": "output", "width": 3, "timing": "combinational"},
        ],
        "clock_reset": None,
        "requirements": [{"id": "R001", "text": "Hold q while a is high then count.", "source": "user_text"}],
    })
    assert bind_trace(tr, c2) is None


def test_wrong_reset_value_mismatches_the_first_posedge(tmp_path):
    ref = tmp_path / "reference.py"
    ref.write_text(
        "class Reference:\n"
        "    def __init__(self, params):\n"
        "        self.q = 0\n"
        "    def reset(self):\n"
        "        self.q = 0\n"
        "    def step(self, inputs):\n"
        "        out = {'q': self.q}\n"
        "        if inputs['a']:\n"
        "            self.q = 4\n"
        "        else:\n"
        "            self.q = (self.q + 1) & 7\n"
        "        return out\n"
    )
    c = Contract.model_validate({
        "module_name": "TopModule", "purpose": "seq", "behavior": "x" * 160,
        "ports": [
            {"name": "clk", "direction": "input", "width": 1, "role": "clock", "timing": "n/a"},
            {"name": "rst", "direction": "input", "width": 1, "role": "reset", "timing": "n/a"},
            {"name": "a", "direction": "input", "width": 1, "timing": "n/a"},
            {"name": "q", "direction": "output", "width": 3, "timing": "registered"},
        ],
        "clock_reset": {"clock": "clk", "reset": "rst"},
        "requirements": [{"id": "R001", "text": "Hold q while a is high then count.", "source": "user_text"}],
    })
    res = check_reference_against_request_tables(c, PROB117, ref, Path(tmp_path) / "work")
    assert res["status"] == "mismatch"
    assert res["mismatches"][0]["request_says"] == 4
    assert res["mismatches"][0]["reference_says"] == 0
