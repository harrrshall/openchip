"""One-step properties from a complete, strictly parsed cell-transition request."""
from __future__ import annotations

from ..contracts.cellular import cellular_scope
from ..contracts.schema import Contract
from .interfaces import matches_clocked_interface


def cellular_contract_matches(contract: Contract, binding: dict) -> bool:
    return matches_clocked_interface(contract, binding['module'],
                                     {'clk': 1, 'load': 1, 'data': binding['width']},
                                     {'q': binding['width']}, reset=None)


def cellular_properties(contract: Contract, request: str) -> str | None:
    binding, incomplete = cellular_scope(request)
    if (not binding or incomplete or not binding['label_consistent']
            or not cellular_contract_matches(contract, binding)):
        return None
    width = binding['width']
    rule = sum(value << bit for bit, value in enumerate(binding['table']))
    return f"""// Request-derived cell table; arbitrary initial DUT state, no assumptions.
module {contract.module_name}_props(input clk, input load,
    input [{width-1}:0] data, input [{width-1}:0] q);
  localparam [7:0] oc_rule = 8'd{rule};
  reg oc_valid = 1'b0;
  reg oc_load;
  reg [{width-1}:0] oc_data, oc_state;
  function [{width-1}:0] oc_next;
    input [{width-1}:0] value;
    integer i;
    reg left_cell, right_cell;
    begin
      for (i = 0; i < {width}; i = i + 1) begin
        left_cell = (i == {width-1}) ? 1'b0 : value[i+1];
        right_cell = (i == 0) ? 1'b0 : value[i-1];
        oc_next[i] = oc_rule[{{left_cell, value[i], right_cell}}];
      end
    end
  endfunction
  always @(posedge clk) begin
    if (oc_valid) begin
      if (oc_load) assert(q == oc_data);
      else assert(q == oc_next(oc_state));
    end
    oc_state <= q;
    oc_data <= data;
    oc_load <= load;
    oc_valid <= 1'b1;
  end
endmodule
"""
