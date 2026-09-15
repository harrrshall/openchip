"""Clocked waveform dumps are traces, not combinational tables."""
from pathlib import Path

from openchip.contracts.schema import Contract
from openchip.contracts.tables import (
    expand_printed_tables, parse_clocked_waveforms, parse_request_tables, posedge_indices, render_trace,
)
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
I would like you to implement a module named TopModule with the following
interface. All input and output ports are one bit unless otherwise
specified.

 - input  clock
 - input  a
 - output p
 - output q

The module should implement a sequential circuit. Read the simulation
waveforms to determine what the circuit does, then implement it.

  time   clock   a   p   q
  0ns    0       0   x   x
  5ns    0       0   x   x
  10ns   0       0   x   x
  15ns   0       0   x   x
  20ns   0       0   x   x
  25ns   1       0   0   x
  30ns   1       0   0   x
  35ns   1       0   0   x
  40ns   1       0   0   x
  45ns   1       0   0   x
  50ns   1       0   0   x
  55ns   0       0   0   0
  60ns   0       0   0   0
  65ns   0       0   0   0
  70ns   0       1   0   0
  75ns   0       0   0   0
  80ns   0       1   0   0
  85ns   1       0   0   0
  90ns   1       1   1   0
  95ns   1       0   0   0
  100ns  1       1   1   0
  105ns  1       0   0   0
  110ns  1       1   1   0
  115ns  0       0   1   1
  120ns  0       1   1   1
  125ns  0       0   1   1
  130ns  0       1   1   1
  135ns  0       0   1   1
  140ns  0       0   1   1
  145ns  1       0   0   1
  150ns  1       0   0   1
  155ns  1       0   0   1
  160ns  1       0   0   1
  165ns  1       1   1   1
  170ns  1       0   0   1
  175ns  0       1   0   0
  180ns  0       0   0   0
  185ns  0       1   0   0
  190ns  0       0   0   0
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
    text = expand_printed_tables(COMB_WAVE)
    assert "Rising edges" not in text
    assert "Clocked waveform" not in text


def test_prob117_expansion_states_the_wrap_point():
    """Every recorded run counted modulo 8; the dump wraps at 6. The expansion must say so."""
    text = expand_printed_tables(PROB117)
    assert "q` goes 6 -> 0" in text
    assert "wraps at 6" in text and "modulo" in text
    # a=1 writes 4 over an undefined q at the first edge: it is a load, not a hold
    assert "becomes 4 from an undefined value while a=1" in text
    rows = [ln for ln in text.splitlines() if ln.strip().startswith(("1.", "6.", "9."))]
    assert "before: a=1, q=x  ->  after: q=4" in rows[0]
    assert "before: a=0, q=4  ->  after: q=5" in rows[1]
    assert "before: a=0, q=0  ->  after: q=1" in rows[2]


def test_prob145_expansion_names_the_latch_and_the_falling_edge():
    """p is transparent while clock is high and q is captured on the falling edge; both were
    modelled as rising-edge flip-flops in every recorded run."""
    text = expand_printed_tables(PROB145)
    assert "`p` is a TRANSPARENT LATCH, open while `clock` is HIGH" in text
    assert "if (clock) p = a;" in text
    assert "`q` changes only at FALLING edges" in text
    assert "No output changes at a rising edge" in text
    falling = [ln for ln in text.splitlines() if "before: a=" in ln]
    assert len(falling) == 3
    assert "115ns  before: a=1, q=0  ->  after: q=1" in falling[1]


def test_render_trace_without_an_interface_falls_back_to_posedge_samples():
    (tr,) = parse_clocked_waveforms(PROB145)
    text = render_trace(tr)  # no output names: the direction of each column is unknown
    edges = [ln for ln in text.splitlines() if ln.startswith("  ")]
    assert len(edges) == 3
    assert "p=0" in edges[0] and "q=x" in edges[0]


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
    # the dump prints q=x at 0ns, so the first step constrains nothing; 10ns already reads q=4
    assert b.steps[0][1] == {}
    assert b.steps[1][1]["q"] == 4
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


def test_a_modulo_reference_is_caught_by_the_wrap(tmp_path):
    """A reference that counts modulo 8 agrees with the dump until 6 -> 0. That one row is the
    whole problem: every recorded run on Prob117 used a modulo and none ever passed."""
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
    assert res["mismatches"][0]["request_says"] == 0
    assert res["mismatches"][0]["reference_says"] == 7

    # The same reference with the printed wrap agrees on every defined row, and is NOT asked to
    # invent a power-up value the dump prints as `x`.
    good = tmp_path / "good.py"
    good.write_text(
        "class Reference:\n"
        "    def __init__(self, params):\n"
        "        self.q = 0\n"
        "    def reset(self):\n"
        "        self.q = 0\n"
        "    def step(self, inputs):\n"
        "        out = {'q': self.q}\n"
        "        if inputs['a']:\n"
        "            self.q = 4\n"
        "        elif self.q == 6:\n"
        "            self.q = 0\n"
        "        else:\n"
        "            self.q = (self.q + 1) & 7\n"
        "        return out\n"
    )
    ok = check_reference_against_request_tables(c, PROB117, good, Path(tmp_path) / "work2")
    assert ok["status"] == "ok", ok["detail"]
    assert ok["rows"] == 8  # nine rising edges, the first one undefined in the dump


def test_prob145_is_not_replayed_through_a_posedge_reference():
    """`p` is a latch and `q` a falling-edge register: one value per cycle cannot express either, and
    replaying them anyway rejected three correct references in a row and delivered no RTL."""
    (tr,) = parse_clocked_waveforms(PROB145)
    c = Contract.model_validate({
        "module_name": "TopModule", "purpose": "seq", "behavior": "x" * 160,
        "ports": [
            {"name": "clock", "direction": "input", "width": 1, "role": "clock", "timing": "n/a"},
            {"name": "a", "direction": "input", "width": 1, "timing": "n/a"},
            {"name": "p", "direction": "output", "width": 1, "timing": "registered"},
            {"name": "q", "direction": "output", "width": 1, "timing": "registered"},
        ],
        "clock_reset": {"clock": "clock", "reset": None},
        "requirements": [{"id": "R001", "text": "p is transparent while clock is high.", "source": "user_text"}],
    })
    assert bind_trace(tr, c) is None
