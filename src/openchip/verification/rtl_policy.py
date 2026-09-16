"""Restrict generated RTL to the synthesizable subset supported by the product.

Check the simulator's expanded source so conditional macros cannot conceal
simulation control or filesystem tasks from a raw-text check.
"""
from pathlib import Path
import re

from ..tools.base import run_tool

# These functions compute values; none control simulation or access files.
VALUE_FUNCTIONS = {'clog2', 'bits', 'signed', 'unsigned', 'size', 'left', 'right',
                   'low', 'high', 'increment', 'dimensions', 'unpacked_dimensions',
                   'countones', 'countbits', 'onehot', 'onehot0', 'isunknown'}
IGNORED = re.compile(r'"(?:\\.|[^"\\])*"|/\*.*?\*/|//[^\n]*', re.S)


def _driver_check_suppressed(source: str) -> bool:
    # Only inspect comments, not quoted strings. Keep the submitted RTL intact;
    # a model cannot opt its own output out of a required structural check.
    for token in IGNORED.finditer(source):
        comment = token[0]
        if not comment.startswith(('//', '/*')):
            continue
        body = comment[2:-2] if comment.startswith('/*') else comment[2:]
        directive = re.match(r'\s*verilator\s+lint_off(?:\s+([A-Za-z_][A-Za-z_0-9]*))?', body)
        if directive and directive[1] in {None, 'MULTIDRIVEN', 'ALL'}:
            return True
    return False


def check_rtl(path: Path, work: Path, exe: str, timeout_s: float) -> tuple[list[dict], dict]:
    expanded = work.resolve() / 'expanded_rtl.v'
    result = run_tool('iverilog-preprocess', [exe, '-g2012', '-E', '-o', str(expanded), str(path.resolve())],
                      work, timeout_s, inputs=[path.resolve()])
    evidence = result.to_dict()
    if not result.ok or not expanded.is_file():
        return [{'message': 'RTL preprocessing failed: ' + (result.error or result.tail())}], evidence
    expanded_text = expanded.read_text()
    text = IGNORED.sub(' ', expanded_text)
    forbidden = sorted(set(re.findall(r'\$([A-Za-z_][A-Za-z_0-9]*)', text)) - VALUE_FUNCTIONS)
    findings = []
    if _driver_check_suppressed(path.read_text()) or _driver_check_suppressed(expanded_text):
        findings.append({'message': 'Generated RTL cannot disable the MULTIDRIVEN structural lint check. Remove the suppression and give each output bit a single driver.'})
    if forbidden:
        findings.append({'message': 'Generated RTL cannot use simulation/system tasks: ' + ', '.join('$'+x for x in forbidden)})
    if re.search(r'\b(initial|force|release|bind)\b', text):
        findings.append({'message': 'Generated RTL cannot contain initial, force, release or bind constructs; use clocked reset logic.'})
    if re.search(r'\b[A-Za-z_][A-Za-z_0-9]*\s*\.\s*[A-Za-z_]', text):
        findings.append({'message': 'Cross-hierarchy references are unsupported in generated RTL; connect modules through declared ports.'})
    return findings, evidence
