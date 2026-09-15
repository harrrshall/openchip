"""The three mechanical losses measured on the final benchmark, one behaviour test each.

1. the structured sections were never produced, because guided decoding omits what is not required;
2. a Moore output was flopped a second time and arrived one cycle late;
3. the request's own module name and interface were lost mechanically.
"""
import json
from pathlib import Path

import pytest

from openchip.contracts.interface import parse_interface, requested_module_name
from openchip.contracts.schema import Contract, contract_json_schema
from openchip.runtime.run import request_requires_fsm
from openchip.verification.guards import moore_output_findings
from openchip.verification.testbench import generate_testbench

FIX = Path(__file__).parent / "fixtures"

FSM_REQUEST = """I would like you to implement a module named TopModule.

 - input  clk
 - input  reset
 - input  in
 - output out

Implement the following Moore state machine with two states.

  B (out=1) --in=0--> A
  A (out=0) --in=1--> A
"""

MOORE_RTL_FLOPPED = """module m(input clk, input rst, input in, output reg out);
reg state;
always @(posedge clk) begin
  if (rst) begin state <= 1'b1; out <= 1'b1; end
  else begin state <= in ? state : ~state; out <= (state == 1'b1); end
end
endmodule"""

MOORE_RTL_COMB = """module m(input clk, input rst, input in, output out);
reg state; wire next = in ? state : ~state;
always @(posedge clk) begin
  if (rst) state <= 1'b1; else state <= next;
end
assign out = (state == 1'b1);
endmodule"""

MOORE_RTL_NEXT_STATE = """module m(input clk, input rst, input in, output reg out);
reg state; wire next = in ? state : ~state;
always @(posedge clk) begin
  if (rst) begin state <= 1'b1; out <= 1'b1; end
  else begin state <= next; out <= (next == 1'b1); end
end
endmodule"""


def fsm_contract() -> Contract:
    d = json.loads((FIX / "counter_contract.json").read_text())
    d["ports"] = [p for p in d["ports"] if p.get("role") in ("clock", "reset")]
    d["ports"] += [{"name": "in", "direction": "input", "width": 1, "role": "data", "timing": "n/a", "description": "in"},
                   {"name": "out", "direction": "output", "width": 1, "role": "data", "timing": "combinational", "description": "out"}]
    d["fsm"] = {"reset_state": "B", "states": [{"name": "A", "meaning": "zero"}, {"name": "B", "meaning": "one"}],
                "output_style": [{"output": "out", "style": "moore"}],
                "transitions": [{"state": "B", "condition": "in == 0", "next_state": "A", "outputs": {"out": "1"}},
                                {"state": "A", "condition": "default", "next_state": "A", "outputs": {"out": "0"}}]}
    return Contract.model_validate(d)


def test_structured_sections_must_be_emitted():
    """Under guided decoding an optional key is simply never produced: make the model decide."""
    required = contract_json_schema()["required"]
    for key in ("fsm", "update_rules", "timing_conventions"):
        assert key in required
    # still nullable: "this design has no state machine" stays sayable
    assert {"type": "null"} in contract_json_schema()["properties"]["fsm"]["anyOf"]


def test_fsm_section_is_demanded_for_a_state_machine_only():
    assert request_requires_fsm(FSM_REQUEST)
    assert not request_requires_fsm("Build a 4-bit priority encoder. Note that a 4-bit number has 16 combinations.")
    assert not request_requires_fsm("q: The 16x16 current state of the game, updated every clock cycle.")


def test_moore_output_must_not_be_flopped_again():
    c = fsm_contract()
    assert [f.code for f in moore_output_findings(c, MOORE_RTL_FLOPPED)] == ["moore_output_registered"]
    assert moore_output_findings(c, MOORE_RTL_COMB) == []
    # registering the decode of the NEXT state costs no cycle and is not a defect
    assert moore_output_findings(c, MOORE_RTL_NEXT_STATE) == []


def test_module_name_and_interface_are_not_lost():
    assert requested_module_name(FSM_REQUEST) == "TopModule"
    # a printed list with no output at all is misread or wrong: decline instead of locking it
    assert parse_interface("- input clk\n- input d\n- input q\n") is None
    assert parse_interface("- input clk\n- output q\n") is not None
    c = fsm_contract()
    c.ports = [p for p in c.ports if p.direction.value != "output"]
    with pytest.raises(ValueError, match="no output port"):
        generate_testbench(c, 10)
