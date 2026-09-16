"""Independent HDLC reference replay derived from complete public bit patterns."""
from __future__ import annotations
import hashlib
import json
import tempfile
from pathlib import Path

from ..contracts.hdlc import hdlc_scope
from ..contracts.schema import Contract
from .harness import run_reference
from .hdlcformal import hdlc_contract_matches


def check_hdlc(contract: Contract, request: str, reference: Path, work: Path,
               timeout_s: float, python: str) -> dict | None:
    binding, incomplete = hdlc_scope(request)
    if not binding:
        return None
    result = dict(status='error', tables=0, rows=0, mismatches=[],
                  checked_kinds=['hdlc_framing'], binding=binding)
    if incomplete:
        return {**result, 'detail': 'Provide the complete updated HDLC specification before checking this revision.'}
    if not hdlc_contract_matches(contract, binding):
        return {**result, 'detail': 'Contract cannot represent the specified HDLC ports and synchronous active-high reset.'}
    if timeout_s <= 0:
        return {**result, 'detail': 'No remaining budget for independent HDLC replay.'}
    inputs = []
    for pattern in range(4096):
        inputs.extend({'in': bit} for bit in
                      [0] + [(pattern >> index) & 1 for index in range(12)] + [0, 0])
    expected = []
    history = '0'
    previous = {'disc': 0, 'flag': 0, 'err': 0}
    for vector in inputs:
        expected.append(previous)
        history = (history + str(vector['in']))[-8:]
        previous = {'disc': int(history.endswith('0111110')),
                    'flag': int(history.endswith('01111110')),
                    'err': int(history.endswith('1111111'))}
    work.mkdir(parents=True, exist_ok=True)
    run = Path(tempfile.mkdtemp(prefix='hdlc-', dir=work))
    contract_path = run / 'contract.json'
    contract_path.write_text(contract.model_dump_json(indent=1))
    replay = run / 'inputs.json'
    replay.write_text(json.dumps({'inputs': inputs}))
    (run / 'expected.json').write_text(json.dumps(expected))
    data = run_reference(reference, contract_path, 0, len(inputs), run / 'reference.json',
                         python=python, timeout_s=timeout_s, replay=replay)
    if data.get('error') or len(data.get('outputs', [])) != len(inputs):
        return {**result, 'detail': 'HDLC reference replay failed: ' +
                str(data.get('error') or 'incomplete outputs')[:600]}
    failed = 0
    mismatches = []
    for cycle, (wanted, actual) in enumerate(zip(expected, data['outputs'])):
        if wanted != actual:
            failed += 1
            if len(mismatches) < 6:
                mismatches.append(dict(cycle=cycle, preceding_inputs=inputs[max(0, cycle - 9):cycle],
                                       request_says=wanted, reference_says=actual))
    result.update(status='mismatch' if failed else 'ok', rows=len(inputs),
                  checked_cycles=len(inputs), patterns=4096,
                  mismatch_vectors=failed, mismatches=mismatches,
                  reference_sha256=hashlib.sha256(reference.read_bytes()).hexdigest(),
                  detail=f'{failed}/{len(inputs)} observations disagree with HDLC framing: disc after exactly five ones then zero, '
                         'flag after exactly six then zero, error while seven or more ones persist. '
                         'Reference returns outputs before consuming this edge input.')
    (run / 'result.json').write_text(json.dumps(result, indent=2))
    return result
