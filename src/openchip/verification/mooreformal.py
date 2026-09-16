"""Request-derived Moore shadow state, without DUT assumptions."""
from __future__ import annotations
from ..contracts.moore import moore_scope
from ..contracts.schema import Contract
from .interfaces import matches_clocked_interface


def moore_contract_matches(contract: Contract, binding: dict) -> bool:
    return matches_clocked_interface(contract, binding['module'],
                                     dict.fromkeys(('clk', 'reset', 'in'), 1), {'out': 1},
                                     reset=('reset', 'synchronous', binding['polarity']),
                                     output_timings=('registered', 'combinational'))


def moore_properties(contract: Contract, request: str) -> str | None:
    binding, incomplete = moore_scope(request)
    if not binding or incomplete or not moore_contract_matches(contract, binding):
        return None
    rows = binding['rows']
    state_ids = {name: index for index, name in enumerate(rows)}
    width = max(1, (len(rows) - 1).bit_length())
    active = 'reset' if binding['polarity'] == 'high' else '!reset'
    assertions = '\n'.join(
        f"        {width}'d{state_ids[state]}: assert(out == 1'b{output});"
        for state, (_, _, output) in rows.items())
    transitions = '\n'.join(
        f"        {width}'d{state_ids[state]}: oc_state <= in ? {width}'d{state_ids[on_one]} : {width}'d{state_ids[on_zero]};"
        for state, (on_zero, on_one, _) in rows.items())
    return f'''// Complete public Moore table; compare current pre-edge state, then advance.
module {contract.module_name}_props(input clk, input reset, input in, input out);
  reg oc_valid = 1'b0;
  reg [{width - 1}:0] oc_state;
  always @(posedge clk) begin
    if (oc_valid) begin
      case (oc_state)
{assertions}
      endcase
    end
    if ({active}) begin
      oc_valid <= 1'b1;
      oc_state <= {width}'d{state_ids[binding['initial']]};
    end else begin
      case (oc_state)
{transitions}
      endcase
    end
  end
endmodule
'''
