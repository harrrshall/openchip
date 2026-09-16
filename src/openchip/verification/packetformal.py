"""Independent bounded checks for an explicitly specified three-byte framer."""
from __future__ import annotations
from ..contracts.packet import packet_scope
from ..contracts.schema import Contract
from .interfaces import matches_clocked_interface


def packet_contract_matches(contract: Contract, binding: dict) -> bool:
    return matches_clocked_interface(contract, binding['module'],
                                     {'clk': 1, 'reset': 1, 'in': 8}, {'done': 1},
                                     reset=('reset', 'synchronous', 'high'))


def packet_properties(contract: Contract, request: str) -> str | None:
    binding, incomplete = packet_scope(request)
    if not binding or incomplete or not packet_contract_matches(contract, binding):
        return None
    return f"""// Independent request-derived framer; no assumptions on DUT outputs.
module {contract.module_name}_props(input clk, input reset, input [7:0] in, input done);
  reg oc_valid = 1'b0;
  reg [1:0] oc_remaining;
  reg oc_done;
  always @(posedge clk) begin
    if (oc_valid) assert(done == oc_done);
    if (reset) begin
      oc_valid <= 1'b1;
      oc_remaining <= 0;
      oc_done <= 0;
    end else begin
      oc_done <= (oc_remaining == 1);
      if (oc_remaining != 0) oc_remaining <= oc_remaining - 1'b1;
      else if (in[3]) oc_remaining <= 2;
    end
  end
endmodule
"""
