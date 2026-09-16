"""Bounded checker derived from the complete public direction-controller rules."""
from __future__ import annotations
from ..contracts.directional import directional_scope
from ..contracts.schema import Contract
from .interfaces import matches_clocked_interface


def directional_contract_matches(contract: Contract, binding: dict) -> bool:
    return matches_clocked_interface(contract, binding['module'],
                                     dict.fromkeys(('clk', 'areset', 'bump_left', 'bump_right', 'ground', 'dig'), 1),
                                     dict.fromkeys(('walk_left', 'walk_right', 'aaah', 'digging'), 1),
                                     reset=('areset', 'asynchronous', 'high'))


def directional_properties(contract: Contract, request: str) -> str | None:
    binding, incomplete = directional_scope(request)
    if not binding or incomplete or not directional_contract_matches(contract, binding):
        return None
    return f"""// Independent public-request transition checker; no DUT output assumptions.
module {contract.module_name}_props(input clk, input areset,
  input bump_left, input bump_right, input ground, input dig,
  input walk_left, input walk_right, input aaah, input digging);
  localparam WL=0, WR=1, FL=2, FR=3, DL=4, DR=5;
  reg [2:0] oc_state;
  always @(posedge clk or posedge areset) begin
    if (areset) oc_state <= WL;
    else case (oc_state)
      WL: if (!ground) oc_state <= FL;
          else if (dig) oc_state <= DL;
          else if (bump_left) oc_state <= WR;
      WR: if (!ground) oc_state <= FR;
          else if (dig) oc_state <= DR;
          else if (bump_right) oc_state <= WL;
      FL: if (ground) oc_state <= WL;
      FR: if (ground) oc_state <= WR;
      DL: if (!ground) oc_state <= FL;
      DR: if (!ground) oc_state <= FR;
      default: oc_state <= WL;
    endcase
  end
  always @(posedge clk) begin
    if (!areset) begin
      assert(walk_left == (oc_state == WL));
      assert(walk_right == (oc_state == WR));
      assert(aaah == ((oc_state == FL) || (oc_state == FR)));
      assert(digging == ((oc_state == DL) || (oc_state == DR)));
    end
  end
endmodule
"""
