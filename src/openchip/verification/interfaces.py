"""Exact interface eligibility for fixed, request-derived clocked checkers."""
from __future__ import annotations

from ..contracts.schema import Contract


def matches_clocked_interface(contract: Contract, module: str,
                              inputs: dict[str, int], outputs: dict[str, int], *,
                              reset: tuple[str, str, str] | None,
                              output_timings: tuple[str, ...] = ('registered',)) -> bool:
    """Match unsigned zero-based ports, posedge clk, and the checker's reset policy.

    Reset is (name, kind, polarity), or None for a resetless interface. Other
    contract metadata is deliberately outside these existing eligibility gates.
    """
    ports = {p.name: (p.direction.value, p.width, p.lsb, p.signed) for p in contract.ports}
    wanted = {name: (direction, width, 0, False)
              for direction, widths in (('input', inputs), ('output', outputs))
              for name, width in widths.items()}
    cr = contract.clock_reset
    return bool(contract.module_name == module and not contract.parameters and ports == wanted
                and cr and cr.clock == 'clk' and cr.clock_edge == 'posedge'
                and cr.reset == (reset[0] if reset else None)
                and (reset is None or (cr.reset_kind, cr.reset_active) == reset[1:])
                and all(p.timing in output_timings for p in contract.outputs()))
