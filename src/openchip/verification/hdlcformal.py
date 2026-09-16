"""Request-derived HDLC pulse expectations, independently advanced at each edge."""
from __future__ import annotations
from ..contracts.hdlc import hdlc_scope
from ..contracts.schema import Contract
from .interfaces import matches_clocked_interface


def hdlc_contract_matches(contract: Contract, binding: dict) -> bool:
    return matches_clocked_interface(contract, binding['module'],
                                     dict.fromkeys(('clk', 'reset', 'in'), 1),
                                     dict.fromkeys(('disc', 'flag', 'err'), 1),
                                     reset=('reset', 'synchronous', 'high'),
                                     output_timings=('registered', 'combinational'))


def hdlc_properties(contract: Contract, request: str) -> str | None:
    binding,incomplete=hdlc_scope(request)
    if not binding or incomplete or not hdlc_contract_matches(contract,binding):
        return None
    return f'''// Independent HDLC history and expected outputs. No assumptions on DUT.
module {contract.module_name}_props(input clk, input reset, input in,
                                   input disc, input flag, input err);
  reg oc_valid = 1'b0;
  reg [2:0] oc_ones;
  reg oc_disc, oc_flag, oc_err;
  always @(posedge clk) begin
    if (oc_valid) begin
      assert(disc == oc_disc);
      assert(flag == oc_flag);
      assert(err == oc_err);
    end
    if (reset) begin
      oc_valid <= 1'b1;
      oc_ones <= 0;
      oc_disc <= 0; oc_flag <= 0; oc_err <= 0;
    end else begin
      oc_disc <= !in && oc_ones == 5;
      oc_flag <= !in && oc_ones == 6;
      oc_err <= in && oc_ones >= 6;
      if (!in) oc_ones <= 0;
      else if (oc_ones < 7) oc_ones <= oc_ones + 1'b1;
    end
  end
endmodule
'''
