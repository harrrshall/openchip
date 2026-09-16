"""Reference replay from complete public packet-boundary and completion rules."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
from ..contracts.packet import packet_scope
from ..contracts.schema import Contract
from .harness import replay_reference
from .packetformal import packet_contract_matches


def check_packet(contract: Contract, request: str, reference: Path, work: Path,
                 timeout_s: float, python: str) -> dict | None:
    binding, incomplete = packet_scope(request)
    if not binding:
        return None
    result = {'status': 'error', 'tables': 0, 'rows': 0, 'mismatches': [],
              'checked_kinds': ['packet_framing'], 'binding': binding}
    def fail(detail):
        return {**result, 'detail': detail}
    if incomplete:
        return fail('Provide the complete updated packet specification before checking this revision.')
    if not packet_contract_matches(contract, binding):
        return fail('Contract cannot represent the specified byte input, registered done and synchronous reset.')
    if timeout_s <= 0:
        return fail('No remaining budget for the independent packet check.')
    inputs = []
    for pattern in range(256):
        markers = [0]*3 + [(pattern >> i) & 1 for i in range(8)] + [0]*3
        for i, marker in enumerate(markers):
            inputs.append({'in': ((pattern ^ (73*i)) & 0xf7) | (marker << 3)})
    # Track an absolute completion edge, independently of the RTL state encoding.
    expected = []; completion_edge = None; previous_done = 0
    for edge, vector in enumerate(inputs):
        expected.append({'done': previous_done})  # reference API observes before this edge
        previous_done = 0
        if completion_edge is None:
            if vector['in'] & 8:
                completion_edge = edge + 2
        elif edge == completion_edge:
            previous_done = 1
            completion_edge = None  # closing byte cannot also become a new start
    run, data = replay_reference(contract, reference, work, 'packets-', inputs,
                                 expected, timeout_s, python)
    if data.get('error') or len(data.get('outputs', [])) != len(inputs):
        return fail('Packet reference evaluation failed: ' + str(data.get('error') or 'incomplete outputs')[:600])
    mismatches = []; total = 0
    for i, (want, got) in enumerate(zip(expected, data['outputs'])):
        if want != got:
            total += 1
            if len(mismatches) < 6:
                mismatches.append({'cycle': i, 'input': inputs[i], 'preceding_inputs': inputs[max(0,i-7):i],
                                   'request_says': want, 'reference_says': got})
    result.update(status='mismatch' if total else 'ok', rows=len(inputs), checked_cycles=len(inputs),
                  marker_patterns=256, mismatch_vectors=total, mismatches=mismatches,
                  reference_sha256=hashlib.sha256(reference.read_bytes()).hexdigest(),
                  detail=f'{total}/{len(inputs)} observations disagree with the explicit three-byte framing rule. '
                         'After accepting a marker byte, consume exactly two payload bytes regardless of their bit3; '
                         'the third byte is not also a start. Search resumes with the fourth byte, without dropping it. '
                         'done is high after the third edge and clears on the next edge while consuming that next byte. '
                         'Reference step returns outputs before consuming the current input.')
    (run / 'result.json').write_text(json.dumps(result, indent=2))
    return result
