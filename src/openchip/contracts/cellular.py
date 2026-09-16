"""Read complete, explicitly tabulated elementary cellular-automaton requests.

A named rule alone is not enough: all eight rows, direction, load priority and
zero boundaries must be present. Additional behavioral prose declines this
bounded grammar rather than silently being discarded.
"""
from __future__ import annotations

import re
from .revisions import revision_scope


def cellular_binding(request: str) -> dict | None:
    if len(request) > 100_000:
        return None
    text = ' '.join(request.split())
    header = (r"I would like you to implement a module named (?P<module>[A-Za-z_]\w*) with the following interface\. "
              r"All input and output ports are one bit unless otherwise specified\. "
              r"- input clk - input load - input data \((?P<width>\d{1,4}) bits\) - output q \((?P=width) bits\) ")
    intro = (r"The module should implement Rule (?P<rule>\d{1,3}), a one-dimensional cellular automaton"
             r"(?: with interesting properties \(such as being Turing-complete\))?\. "
             r"There is a one-dimensional array of cells \(on or off\)\. At each time step, the state of each cell changes\. "
             r"In Rule (?P=rule), the next state of each cell depends only on itself and its two neighbours, "
             r"according to the following table: Left\[i\+1\] \| Center\[i\] \| Right\[i-1\] \| Center's next state ")
    rows = r"(?P<rows>(?:[01]\s*\|\s*[01]\s*\|\s*[01]\s*\|\s*[01]\s+){8})"
    tail = (r"In this circuit, create a (?P=width)-cell system \(q\[(?P<last>\d{1,4}):0\]\), and advance by one time step each clock cycle\. "
            r"The synchronous active high load input indicates the state of the system should be loaded with data\[(?P=last):0\]\. "
            r"Assume the boundaries \(q\[-1\] and q\[(?P=width)\], if they existed\) are both zero \(off\)\. "
            r"Assume all sequential logic is triggered on the positive edge of the clock\.")
    m = re.fullmatch(header + intro + rows + tail, text, re.I)
    if not m:
        return None
    width, rule = int(m['width']), int(m['rule'])
    if not 3 <= width <= 1024 or int(m['last']) != width - 1 or rule > 255:
        return None
    table = {}
    for values in re.findall(r'([01])\s*\|\s*([01])\s*\|\s*([01])\s*\|\s*([01])', m['rows']):
        left, center, right, value = map(int, values)
        key = 4 * left + 2 * center + right
        if key in table:
            return None
        table[key] = value
    if len(table) != 8:
        return None
    return {'module': m['module'], 'width': width, 'rule': rule,
            'table': [table[i] for i in range(8)],
            'label_consistent': rule == sum(table[i] << i for i in range(8))}


def cellular_scope(request: str) -> tuple[dict | None, bool]:
    return revision_scope(request, cellular_binding)


def render_cellular(request: str) -> str:
    b, incomplete = cellular_scope(request)
    if not b or incomplete:
        return ''
    rows = '\n'.join(f"old left={i >> 2}, old center={(i >> 1) & 1}, old right={i & 1} -> next center={v}"
                     for i, v in enumerate(b['table']))
    return (f"Sequential cell transition table, {b['width']} cells. Left is q[i+1], right is q[i-1].\n"
            "At each positive clock edge: load=1 copies data to q; otherwise every cell updates simultaneously "
            "from the OLD q values below. Out-of-range neighbours are zero.\n" + rows +
            ('\nThe printed rule number conflicts with its table; resolve this contradiction.' if not b['label_consistent'] else ''))
