"""Check a sequential reference against the request's complete cell-transition table."""
from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path

from ..contracts.cellular import cellular_scope
from ..contracts.schema import Contract
from .harness import run_reference


def check_cellular(contract: Contract, request: str, reference: Path, work: Path,
                   timeout_s: float, python: str) -> dict | None:
    b, incomplete = cellular_scope(request)
    if b is None:
        return None
    result = {'status': 'error', 'tables': 1, 'source_rows': 8, 'rows': 0, 'mismatches': [],
              'checked_kinds': ['cellular_transition_table'], 'binding': b}
    def fail(detail):
        return {**result, 'detail': detail}
    if incomplete:
        return fail('Provide the complete updated cell-transition specification before checking this revision.')
    if not b['label_consistent']:
        return fail('The printed rule number and explicit transition table conflict.')
    from .cellularformal import cellular_contract_matches
    if not cellular_contract_matches(contract, b):
        return fail('Contract ports/timing cannot represent the explicit sequential cell table.')
    if timeout_s <= 0:
        return fail('No remaining budget for the sequential cell-table check.')
    width = b['width']; mask = (1 << width) - 1
    # Every neighbourhood at interior positions, boundary ones, and dense states.
    patterns = {0, mask, 1, 1 << (width - 1), int('10' * ((width + 1) // 2), 2) & mask}
    for center in {1, width // 2, width - 2}:
        patterns.update(i << (center - 1) for i in range(8))
    inputs, expected = [], []
    state = None
    for value in sorted(patterns):
        for vector in [{'load': 1, 'data': value}] + [{'load': 0, 'data': mask ^ value}] * 4:
            inputs.append(vector); expected.append(state)
            if vector['load']:
                state = vector['data']
            else:
                state = sum(b['table'][(((state >> (i + 1)) & 1) << 2) |
                                       (((state >> i) & 1) << 1) |
                                       ((state >> (i - 1)) & 1 if i else 0)] << i for i in range(width))
    # Observe the last transition too. Power-up before the first load is unspecified.
    inputs.append({'load': 1, 'data': 0}); expected.append(state)
    work.mkdir(parents=True, exist_ok=True)
    run = Path(tempfile.mkdtemp(prefix='cellular-', dir=work))
    cp = run / 'contract.json'; cp.write_text(contract.model_dump_json(indent=1))
    replay = run / 'inputs.json'; replay.write_text(json.dumps({'inputs': inputs}))
    (run / 'request-expected.json').write_text(json.dumps(expected))
    data = run_reference(reference, cp, 0, len(inputs), run / 'reference.json', python=python, timeout_s=timeout_s, replay=replay)
    if data.get('error') or len(data.get('outputs', [])) != len(inputs):
        return fail('Sequential reference evaluation failed: ' + str(data.get('error') or 'incomplete outputs')[:600])
    mismatches = []
    total = 0
    for cycle, (want, outputs) in enumerate(zip(expected, data['outputs'])):
        if want is None:
            continue
        actual = outputs.get('q')
        if not isinstance(actual, int) or not 0 <= actual <= mask:
            return fail('Sequential reference output does not fit its declared unsigned width.')
        if actual != want:
            total += 1
            if len(mismatches) < 6:
                mismatches.append({'cycle': cycle, 'preceding_inputs': inputs[max(0, cycle-2):cycle],
                                   'request_says': want, 'reference_says': actual})
    result.update(status='mismatch' if total else 'ok', rows=len(inputs)-1, checked_cycles=len(inputs)-1,
                  mismatch_cycles=total, mismatches=mismatches,
                  reference_sha256=hashlib.sha256(reference.read_bytes()).hexdigest(),
                  detail=f"{total}/{len(inputs)-1} observed cycles disagree with the explicit cell-transition table; power-up before the first load is not checked.")
    (run / 'result.json').write_text(json.dumps(result, indent=2))
    return result
