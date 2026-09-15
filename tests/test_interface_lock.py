"""The request's printed interface is the port list, and the request's waveform is the spec.

Both are ground truth that never passes through a model. These tests use the two VerilogEval
requests that no model has passed in 36 recorded runs.
"""
import pytest

from openchip.contracts.interface import interface_violations, parse_interface
from openchip.contracts.schema import Contract
from openchip.runtime.run import _drop_invented_reset
from openchip.verification.guards import interface_findings
from openchip.verification.wavecheck import replay_request_waveform

PROB117 = """I would like you to implement a module named TopModule with the following
interface. All input and output ports are one bit unless otherwise
specified.

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

PROB145 = """I would like you to implement a module named TopModule with the following
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


def _contract(ports, clock):
    return Contract.model_validate({
        "module_name": "TopModule", "purpose": "from a waveform", "behavior": "x" * 160,
        "ports": ports, "clock_reset": {"clock": clock, "reset": None},
        "requirements": [{"id": "R001", "text": "Reproduce the printed waveform.", "source": "user_text"}],
    })


PROB117_CONTRACT = _contract([
    {"name": "clk", "direction": "input", "width": 1, "role": "clock", "timing": "n/a"},
    {"name": "a", "direction": "input", "width": 1, "timing": "n/a"},
    {"name": "q", "direction": "output", "width": 3, "timing": "registered"},
], "clk")

PROB145_CONTRACT = _contract([
    {"name": "clock", "direction": "input", "width": 1, "role": "clock", "timing": "n/a"},
    {"name": "a", "direction": "input", "width": 1, "timing": "n/a"},
    {"name": "p", "direction": "output", "width": 1, "timing": "registered"},
    {"name": "q", "direction": "output", "width": 1, "timing": "registered"},
], "clock")


def test_the_printed_interface_is_read_exactly():
    ports = parse_interface(PROB117)
    assert [(p.direction, p.name, p.width) for p in ports] == [
        ("input", "clk", None), ("input", "a", None), ("output", "q", 3)]
    assert parse_interface("no interface here at all") is None


def test_an_invented_reset_is_a_violation_of_the_requested_interface():
    ports = parse_interface(PROB117)
    ok = [("clk", "input", 1), ("a", "input", 1), ("q", "output", 3)]
    assert interface_violations(ports, ok) == []
    with_rst = ok + [("rst", "input", 1)]
    assert any("`rst`" in v and "not in the request" in v for v in interface_violations(ports, with_rst))
    assert any("`q`" in v and "3 bits" in v
               for v in interface_violations(ports, [("clk", "input", 1), ("a", "input", 1), ("q", "output", 1)]))


def test_intake_drops_a_reset_the_request_does_not_have():
    """The recorded Prob117 run died here: the model wrote a reset the request has no port for and
    the contract failed validation three times, so the run produced no RTL at all (ADR 0016 L2)."""
    data = {"clock_reset": {"clock": "clk", "reset": "rst"},
            "ports": [{"name": "clk"}, {"name": "a"}, {"name": "q"}, {"name": "rst"}]}
    notes = _drop_invented_reset(data, PROB117)
    assert notes and "rst" in notes[0]
    assert data["clock_reset"]["reset"] is None
    assert [p["name"] for p in data["ports"]] == ["clk", "a", "q"]
    # a request without a printed interface is left alone
    untouched = {"clock_reset": {"clock": "clk", "reset": "rst"}, "ports": [{"name": "rst"}]}
    assert _drop_invented_reset(untouched, "build me a counter") == []


def test_rtl_declaring_an_extra_reset_is_rejected_before_simulation():
    rtl = "module TopModule(input clk, input rst, input a, output reg [2:0] q);\nendmodule\n"
    (f,) = interface_findings(PROB117_CONTRACT, rtl)
    assert f.code == "interface_mismatch" and "`rst`" in f.message
    good = "module TopModule(input clk, input a, output reg [2:0] q);\nendmodule\n"
    assert interface_findings(PROB117_CONTRACT, good) == []
    missing = "module TopModule(input clk, output reg [2:0] q);\nendmodule\n"
    assert "does not declare contract port(s): `a`" in interface_findings(PROB117_CONTRACT, missing)[0].message


PROB117_RIGHT = """module TopModule(input clk, input a, output reg [2:0] q);
  always @(posedge clk) begin
    if (a) q <= 3'd4;
    else if (q == 3'd6) q <= 3'd0;
    else q <= q + 3'd1;
  end
endmodule
"""

PROB117_MODULO = PROB117_RIGHT.replace("    else if (q == 3'd6) q <= 3'd0;\n", "")

PROB145_RIGHT = """module TopModule(input clock, input a, output reg p, output reg q);
  always @(*) if (clock) p = a;
  always @(negedge clock) q <= a;
endmodule
"""

PROB145_TWO_FLOPS = """module TopModule(input clock, input a, output reg p, output reg q);
  always @(posedge clock) p <= a;
  always @(posedge clock) q <= p;
endmodule
"""


@pytest.mark.cloud
@pytest.mark.parametrize("request_text,contract,rtl,expected", [
    (PROB117, PROB117_CONTRACT, PROB117_RIGHT, "pass"),
    (PROB117, PROB117_CONTRACT, PROB117_MODULO, "fail"),
    (PROB145, PROB145_CONTRACT, PROB145_RIGHT, "pass"),
    (PROB145, PROB145_CONTRACT, PROB145_TWO_FLOPS, "fail"),
])
def test_the_delivered_rtl_is_replayed_against_the_printed_waveform(tmp_path, request_text, contract, rtl, expected):
    """The whole point: a wrap at 6 and a transparent latch are visible in the dump and in nothing
    else, so the dump itself is simulated against the delivered module."""
    rtl_path = tmp_path / "TopModule.v"
    rtl_path.write_text(rtl)
    res = replay_request_waveform(contract, request_text, rtl_path, tmp_path / "work")
    assert res["status"] == expected, res["detail"]
    if expected == "pass":
        assert res["checks"] > 0
