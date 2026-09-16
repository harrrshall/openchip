"""Recognize a complete adjacent-bit AND/OR/XOR vector specification.

This deliberately bounded grammar requires the examples, all output boundaries,
and wrapping rule. Partial revisions and additional behavior cannot be ignored.
"""
from __future__ import annotations

import re
from .revisions import revision_scope


def neighbor_binding(request: str) -> dict | None:
    if len(request) > 100_000:
        return None
    text = ' '.join(request.split())
    header = (r"I would like you to implement a module named (?P<module>[A-Za-z_]\w*) with the following interface\. "
              r"All input and output ports are one bit unless otherwise specified\. "
              r"- input in \((?P<width>\d{1,4}) bits\) - output out_both \((?P=width) bits\) "
              r"- output out_any \((?P=width) bits\) - output out_different \((?P=width) bits\) ")
    both = (r"The module takes as input a (?P=width)-bit input vector in\[(?P<last>\d{1,4}):0\] and should produce the following three outputs: "
            r"\(1\) out_both: Each bit of this output vector should indicate whether both the corresponding input bit and its neighbour to the left are '1'\. "
            r"For example, out_both\[(?P<interior>\d{1,4})\] should indicate if in\[(?P=interior)\] and in\[(?P=last)\] are both 1\. "
            r"Since in\[(?P=last)\] has no neighbour to the left, the answer is obvious so simply set out_both\[(?P=last)\] to be zero\. ")
    any_ = (r"\(2\) out_any: Each bit of this output vector should indicate whether any of the corresponding input bit and its neighbour to the right are '1'\. "
            r"For example, out_any\[2\] should indicate if either in\[2\] or in\[1\] are 1\. "
            r"Since in\[0\] has no neighbour to the right, the answer is obvious so simply set out_any\[0\] to be zero\. ")
    different = (r"\(3\) out_different: Each bit of this output vector should indicate whether the corresponding input bit is different from its neighbour to the left\. "
                 r"For example, out_different\[(?P=interior)\] should indicate if in\[(?P=interior)\] is different from in\[(?P=last)\]\. "
                 r"For this part, treat the vector as wrapping around, so in\[(?P=last)\]'s neighbour to the left is in\[0\]\.")
    match = re.fullmatch(header + both + any_ + different, text)
    if not match:
        return None
    width = int(match['width'])
    if not 3 <= width <= 1024 or int(match['last']) != width - 1 or int(match['interior']) != width - 2:
        return None
    return {'module': match['module'], 'width': width}


def neighbor_scope(request: str) -> tuple[dict | None, bool]:
    return revision_scope(request, neighbor_binding)
