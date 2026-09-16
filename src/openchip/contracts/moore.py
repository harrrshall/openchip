"""Complete, bounded public one-bit Moore transition tables.

Grammar recognition is conservative: no additional behavioral prose is ignored.
State names, transitions, outputs, reset state and reset polarity are data.
"""
from __future__ import annotations
import re

_I = r'[A-Za-z_]\w*'
_HEADER = re.compile(
    rf'I would like you to implement a module named (?P<module>{_I}) with the following '
    r'interface\. All input and output ports are one bit unless otherwise specified\. '
    r'- input clk - input reset - input in - output out '
    r'The module should implement a Moore state machine with the following '
    r'state transition table with one input, one output, and (?P<count>\w+) states\. '
    r'Include a synchronous active (?P<polarity>high|low) reset that resets the FSM to state '
    rf'(?P<initial>{_I})\. Assume all sequential logic is triggered on the positive edge of the '
    r'clock\. State \| Next state in=0, Next state in=1 \| Output (?P<rows>.+)')
_ROW = re.compile(rf'({_I})\s*\|\s*({_I})\s*,\s*({_I})\s*\|\s*([01])(?:\s+|$)')
_COUNTS = {w:i for i,w in enumerate(('zero','one','two','three','four','five','six','seven','eight','nine','ten','eleven','twelve','thirteen','fourteen','fifteen','sixteen'))}


def moore_binding(request: str) -> dict | None:
    if len(request) > 100_000:
        return None
    match = _HEADER.fullmatch(' '.join(request.split()))
    if not match:
        return None
    count = _COUNTS.get(match['count'], int(match['count']) if match['count'].isdecimal() and len(match['count']) <= 2 else 0)
    if not 2 <= count <= 16:
        return None
    rows = {}; position = 0
    for row in _ROW.finditer(match['rows']):
        if row.start() != position or row[1] in rows:
            return None
        rows[row[1]] = (row[2], row[3], int(row[4]))
        position = row.end()
    if position != len(match['rows']) or len(rows) != count or match['initial'] not in rows:
        return None
    if any(a not in rows or b not in rows for a,b,_ in rows.values()):
        return None
    return dict(module=match['module'], initial=match['initial'], polarity=match['polarity'], rows=rows)


def moore_scope(request: str) -> tuple[dict | None, bool]:
    parts = re.split(r'\n\nChange request \(v\d+\): ', request)
    latest = moore_binding(parts[-1])
    return (latest, False) if latest else (moore_binding(parts[0]), len(parts) > 1)
