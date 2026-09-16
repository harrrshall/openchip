"""One-step properties from a complete, strictly parsed cell-transition request."""
from __future__ import annotations

from ..contracts.cellular import cellular_scope
from ..contracts.schema import Contract


def cellular_contract_matches(contract: Contract, binding: dict) -> bool:
    cr = contract.clock_reset
    ports = {p.name: (p.direction.value, p.width) for p in contract.ports}
    return bool(not contract.parameters and contract.module_name == binding['module']
                and cr is not None and cr.clock == 'clk' and cr.clock_edge == 'posedge'
                and cr.reset is None and all(p.lsb == 0 and not p.signed for p in contract.ports)
                and ports == {'clk': ('input', 1), 'load': ('input', 1),
                              'data': ('input', binding['width']), 'q': ('output', binding['width'])}
                and next(p for p in contract.ports if p.name == 'q').timing == 'registered')


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
