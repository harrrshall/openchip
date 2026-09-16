"""Independent bounded checks for an explicitly specified three-byte framer."""
from __future__ import annotations
from ..contracts.packet import packet_scope
from ..contracts.schema import Contract


def packet_contract_matches(contract: Contract, binding: dict) -> bool:
    ports = {p.name: (p.direction.value, p.width, p.lsb, p.signed) for p in contract.ports}
    cr = contract.clock_reset
    return bool(contract.module_name == binding['module'] and not contract.parameters
                and ports == {'clk': ('input', 1, 0, False), 'reset': ('input', 1, 0, False),
                              'in': ('input', 8, 0, False), 'done': ('output', 1, 0, False)}
                and cr and cr.clock == 'clk' and cr.reset == 'reset' and cr.clock_edge == 'posedge'
                and cr.reset_active == 'high' and cr.reset_kind == 'synchronous'
                and all(p.timing == 'registered' for p in contract.outputs()))


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
