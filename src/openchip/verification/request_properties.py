"""Ordered selection of a formal checker derived from a complete user request."""
from __future__ import annotations

from ..contracts.schema import Contract
from .cellularformal import cellular_properties
from .directionalformal import directional_properties
from .hdlcformal import hdlc_properties
from .lfsrcheck import lfsr_properties
from .mooreformal import moore_properties
from .packetformal import packet_properties


def request_properties(contract: Contract, request: str) -> tuple[str | None, str]:
    """Return the first applicable checker and its recorded provenance."""
    for generate, origin in (
        (lfsr_properties, "request-derived Galois transitions"),
        (cellular_properties, "request-derived cell-transition table"),
        (directional_properties, "request-derived directional transitions"),
        (packet_properties, "request-derived packet framing"),
        (moore_properties, "request-derived Moore transition table"),
        (hdlc_properties, "request-derived HDLC framing"),
    ):
        code = generate(contract, request)
        if code is not None:
            return code, origin
    return None, "existing checker"
