"""Deterministic acceptance guards: fire on the observed contradictions, stay silent on legitimate forms."""
import json
from pathlib import Path

from openchip.contracts.schema import Contract
from openchip.verification.guards import acceptance_guards, contract_guards

FIX = Path(__file__).parent / "fixtures"


def contract(**cr) -> Contract:
    d = json.loads((FIX / "counter_contract.json").read_text())
    if cr.get("clock_reset", "x") is None:
        d["clock_reset"] = None
        d["ports"] = [p for p in d["ports"] if p.get("role") not in ("clock", "reset")]
        for p in d["ports"]:
            p["timing"] = "combinational"
        return Contract.model_validate(d)
    d["clock_reset"] = {"clock": "clk", "reset": "rst", **cr}
    return Contract.model_validate(d)


SYNC_HIGH = """module m(input clk, input rst, output reg [7:0] count);
always @(posedge clk) begin
  if (rst) count <= 8'd0; else count <= count + 1;
end
endmodule"""

ASYNC_LOW = """module m(input clk, input rst, output reg [7:0] count);
always @(posedge clk or negedge rst) begin
  if (!rst) count <= 8'd0; else count <= count + 1;
end
endmodule"""

ASYNC_LOW_SV = """module m(input clk, input rst, output logic [7:0] count);
always_ff @(posedge clk or negedge rst) begin
  if (!rst) count <= '0; else count <= count + 1;
end
endmodule"""

SYNC_LOW_INVERTED = """module m(input clk, input rst, output reg [7:0] count);
always @(posedge clk) begin
  if (rst) begin
    count <= count + 1;
  end else begin
    count <= 8'd0;
  end
end
endmodule"""

SYNC_LOW_AS_HIGH = """module m(input clk, input rst, output reg [7:0] count);
always @(posedge clk) begin
  if (rst) count <= 8'd0;
  else count <= count + 1;
end
endmodule"""


def codes(findings):
    return sorted(f.code for f in findings)


def test_silent_on_matching_designs():
    assert acceptance_guards(contract(reset_active="high", reset_kind="synchronous"), SYNC_HIGH) == []
    assert acceptance_guards(contract(reset_active="low", reset_kind="asynchronous"), ASYNC_LOW) == []
    assert acceptance_guards(contract(reset_active="low", reset_kind="asynchronous"), ASYNC_LOW_SV) == []
    assert acceptance_guards(contract(reset_active="low", reset_kind="synchronous"), SYNC_LOW_INVERTED) == []


def test_async_reset_missing():
    assert codes(acceptance_guards(contract(reset_active="high", reset_kind="asynchronous"), SYNC_HIGH)) == ["async_reset_missing"]


def test_active_low_never_tested_low():
    assert codes(acceptance_guards(contract(reset_active="low", reset_kind="synchronous"), SYNC_LOW_AS_HIGH)) == ["reset_polarity"]


def test_active_high_treated_as_low():
    assert codes(acceptance_guards(contract(reset_active="high", reset_kind="synchronous"), ASYNC_LOW)) == ["reset_polarity"]


def test_comments_are_ignored():
    rtl = SYNC_HIGH.replace("always @(posedge clk)", "// always @(posedge clk or negedge rst)\nalways @(posedge clk)")
    assert codes(acceptance_guards(contract(reset_active="high", reset_kind="asynchronous"), rtl)) == ["async_reset_missing"]


def test_clocked_rtl_for_combinational_contract():
    c = contract(clock_reset=None)
    assert codes(acceptance_guards(c, "module m(input a, output reg y);\nalways @(posedge a) y <= 1;\nendmodule")) == ["clocked_combinational"]
    assert acceptance_guards(c, "module m(input a, output y);\nassign y = ~a;\nendmodule") == []


def test_unusable_reset_name_is_skipped():
    c = contract(reset_active="low", reset_kind="asynchronous")
    c.clock_reset.reset = ""
    assert acceptance_guards(c, SYNC_HIGH) == []


def test_behavior_leak_makes_contract_provisional():
    c = contract(reset_active="high")
    assert contract_guards(c) == []
    c.behavior = c.behavior + " Wait, the reset value might be 1 instead. ???"
    assert codes(contract_guards(c)) == ["behavior_leak"]
