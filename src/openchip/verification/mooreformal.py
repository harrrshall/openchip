"""Request-derived Moore shadow state, without DUT assumptions."""
from __future__ import annotations
from ..contracts.moore import moore_scope
from ..contracts.schema import Contract


def moore_contract_matches(contract: Contract, binding: dict) -> bool:
    ports = {p.name:(p.direction.value,p.width,p.lsb,p.signed) for p in contract.ports}
    cr = contract.clock_reset
    return bool(contract.module_name == binding['module'] and not contract.parameters
                and ports == {'clk':('input',1,0,False),'reset':('input',1,0,False),
                              'in':('input',1,0,False),'out':('output',1,0,False)}
                and cr and cr.clock == 'clk' and cr.clock_edge == 'posedge'
                and cr.reset == 'reset' and cr.reset_kind == 'synchronous'
                and cr.reset_active == binding['polarity']
                and all(p.timing in {'registered', 'combinational'} for p in contract.outputs()))


def moore_properties(contract: Contract, request: str) -> str | None:
    binding, incomplete = moore_scope(request)
    if not binding or incomplete or not moore_contract_matches(contract,binding):
        return None
    rows=binding['rows']; ids={name:i for i,name in enumerate(rows)}
    width=max(1,(len(rows)-1).bit_length())
    active='reset' if binding['polarity']=='high' else '!reset'
    assertions='\n'.join(f"        {width}'d{ids[s]}: assert(out == 1'b{v[2]});" for s,v in rows.items())
    transitions='\n'.join(f"        {width}'d{ids[s]}: oc_state <= in ? {width}'d{ids[v[1]]} : {width}'d{ids[v[0]]};" for s,v in rows.items())
    return f'''// Complete public Moore table; compare current pre-edge state, then advance.
module {contract.module_name}_props(input clk, input reset, input in, input out);
  reg oc_valid = 1'b0;
  reg [{width-1}:0] oc_state;
  always @(posedge clk) begin
    if (oc_valid) begin
      case (oc_state)
{assertions}
      endcase
    end
    if ({active}) begin
      oc_valid <= 1'b1;
      oc_state <= {width}'d{ids[binding['initial']]};
    end else begin
      case (oc_state)
{transitions}
      endcase
    end
  end
endmodule
'''
