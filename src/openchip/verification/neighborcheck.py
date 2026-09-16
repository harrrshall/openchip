"""Check reference behavior against a complete, explicitly indexed neighbor request."""
from __future__ import annotations

import hashlib
import json
import random
import tempfile
from pathlib import Path

from ..contracts.neighbors import neighbor_scope
from ..contracts.schema import Contract
from .harness import run_reference


def check_neighbors(contract: Contract, request: str, reference: Path, work: Path,
                    timeout_s: float, python: str) -> dict | None:
    binding, incomplete = neighbor_scope(request)
    if binding is None:
        return None
    result = {'status': 'error', 'tables': 0, 'rows': 0, 'mismatches': [],
              'checked_kinds': ['neighbor_vector_equations'], 'binding': binding}
    def fail(detail):
        return {**result, 'detail': detail}
    if incomplete:
        return fail('Provide the complete updated vector-neighbor specification before checking this revision.')
    width = binding['width']
    ports = {p.name: (p.direction.value, p.width, p.lsb, p.signed) for p in contract.ports}
    expected_ports = {'in': ('input', width, 0, False), **{name: ('output', width, 0, False)
                      for name in ['out_both', 'out_any', 'out_different']}}
    if (contract.module_name != binding['module'] or contract.parameters or contract.clock_reset is not None
            or ports != expected_ports or any(p.timing != 'combinational' for p in contract.outputs())):
        return fail('Contract ports/timing cannot represent the explicit combinational neighbor specification.')
    if timeout_s <= 0:
        return fail('No remaining budget for the independent neighbor check.')
    mask = (1 << width) - 1
    patterns = {0, mask, int('10' * ((width + 1) // 2), 2) & mask, 1 | (1 << (width-1))}
    for bit in range(width):
        patterns.add(1 << bit)
        patterns.add(mask ^ (1 << bit))
        if bit + 1 < width:
            patterns.add(3 << bit)
    rng = random.Random(1701)
    patterns.update(rng.getrandbits(width) for _ in range(64))
    if width <= 10:
        patterns = set(range(1 << width))
    inputs = [{'in': value} for value in sorted(patterns)]
    expected = []
    for vector in inputs:
        value = vector['in']
        # Derive each destination independently from its source indices.
        expected.append({
            'out_both': sum((((value >> bit) & 1) & ((value >> (bit+1)) & 1)) << bit for bit in range(width-1)),
            'out_any': sum((((value >> bit) & 1) | ((value >> (bit-1)) & 1)) << bit for bit in range(1, width)),
            'out_different': sum((((value >> bit) & 1) ^ ((value >> ((bit+1) % width)) & 1)) << bit for bit in range(width)),
        })
    work.mkdir(parents=True, exist_ok=True)
    run = Path(tempfile.mkdtemp(prefix='neighbors-', dir=work))
    cp = run / 'contract.json'; cp.write_text(contract.model_dump_json(indent=1))
    replay = run / 'inputs.json'; replay.write_text(json.dumps({'inputs': inputs}))
    (run / 'request-expected.json').write_text(json.dumps(expected))
    data = run_reference(reference, cp, 0, len(inputs), run / 'reference.json', python=python,
                         timeout_s=timeout_s, replay=replay)
    if data.get('error') or len(data.get('outputs', [])) != len(inputs):
        return fail('Neighbor reference evaluation failed: ' + str(data.get('error') or 'incomplete outputs')[:600])
    mismatches = []; total = 0
    for vector, want, got in zip(inputs, expected, data['outputs']):
        if got != want:
            total += 1
            if len(mismatches) < 6:
                mismatches.append({'input': vector, 'request_says': want, 'reference_says': got})
    result.update(status='mismatch' if total else 'ok', rows=len(inputs), mismatch_vectors=total,
                  mismatches=mismatches, reference_sha256=hashlib.sha256(reference.read_bytes()).hexdigest(),
                  detail=f'{total}/{len(inputs)} vectors disagree with the explicit indexed neighbor equations. '
                         'Use source bit i+1 for the higher neighbor and i-1 for the lower; force the specified output boundary bits to zero.')
    (run / 'result.json').write_text(json.dumps(result, indent=2))
    return result
