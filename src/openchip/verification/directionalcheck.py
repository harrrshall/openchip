"""Independent directed transitions from a complete walking-controller request."""
from __future__ import annotations
import hashlib
import itertools
import json
import tempfile
from pathlib import Path
from ..contracts.directional import directional_scope
from ..contracts.schema import Contract
from .harness import run_reference
from .directionalformal import directional_contract_matches


def check_directional(contract: Contract, request: str, reference: Path, work: Path,
                      timeout_s: float, python: str) -> dict | None:
    binding, incomplete = directional_scope(request)
    if binding is None:
        return None
    result = {'status': 'error', 'tables': 0, 'rows': 0, 'mismatches': [],
              'checked_kinds': ['directional_state_transitions'], 'binding': binding}
    def fail(detail):
        return {**result, 'detail': detail}
    if incomplete:
        return fail('Provide the complete updated controller specification before checking this revision.')
    if not directional_contract_matches(contract, binding):
        return fail('Contract cannot represent the requested one-bit Moore controller with positive-edge asynchronous reset.')
    if timeout_s <= 0:
        return fail('No remaining budget for the independent state-transition check.')
    inputs, expected, observations = [], [], []
    mode, direction = 'walk', 0
    def tick(bl, br, ground, dig, context):
        nonlocal mode, direction
        inputs.append(dict(bump_left=bl, bump_right=br, ground=ground, dig=dig))
        expected.append(dict(walk_left=int(mode == 'walk' and direction == 0),
                             walk_right=int(mode == 'walk' and direction == 1),
                             aaah=int(mode == 'fall'), digging=int(mode == 'dig')))
        observations.append({'state_before': [mode, direction], 'context': context})
        if mode == 'walk':
            if not ground:
                mode = 'fall'
            elif dig:
                mode = 'dig'
            elif bl and br:
                direction = 1 - direction
            elif bl:
                direction = 1
            elif br:
                direction = 0
        elif mode == 'fall' and ground:
            mode = 'walk'
        elif mode == 'dig' and not ground:
            mode = 'fall'
    cases = 0
    for target_mode, target_direction in itertools.product(['walk', 'fall', 'dig'], [0, 1]):
        for controls in itertools.product([0, 1], repeat=4):
            context = {'from': [target_mode, target_direction], 'controls': controls}
            # Reach a known state using only public inputs, never internal state.
            tick(0, 0, 0, 0, context)
            tick(0, 0, 1, 0, context)
            tick(0, 1, 1, 0, context)  # select left, including when already left
            if target_direction:
                tick(1, 0, 1, 0, context)
            if target_mode == 'fall':
                tick(0, 0, 0, 0, context)
            elif target_mode == 'dig':
                tick(0, 0, 1, 1, context)
            tick(*controls, context)
            tick(0, 0, 0, 0, context)
            tick(0, 0, 1, 0, context)
            tick(0, 0, 1, 0, context)  # observe remembered direction after landing
            cases += 1
    work.mkdir(parents=True, exist_ok=True)
    run = Path(tempfile.mkdtemp(prefix='directional-', dir=work))
    cp = run / 'contract.json'; cp.write_text(contract.model_dump_json(indent=1))
    replay = run / 'inputs.json'; replay.write_text(json.dumps({'inputs': inputs}))
    (run / 'request-expected.json').write_text(json.dumps({'outputs': expected, 'observations': observations}))
    data = run_reference(reference, cp, 0, len(inputs), run / 'reference.json', python=python,
                         timeout_s=timeout_s, replay=replay)
    if data.get('error') or len(data.get('outputs', [])) != len(inputs):
        return fail('Controller reference evaluation failed: ' + str(data.get('error') or 'incomplete outputs')[:600])
    mismatches = []; total = 0
    for i, (want, got) in enumerate(zip(expected, data['outputs'])):
        if want != got:
            total += 1
            if len(mismatches) < 6:
                mismatches.append({'cycle': i, **observations[i], 'inputs': inputs[i],
                                   'preceding_inputs': inputs[max(0, i-5):i],
                                   'request_says': want, 'reference_says': got})
    result.update(status='mismatch' if total else 'ok', rows=len(inputs), checked_cycles=len(inputs),
                  transition_cases=cases, mismatch_vectors=total, mismatches=mismatches,
                  reference_sha256=hashlib.sha256(reference.read_bytes()).hexdigest(),
                  detail=f'{total}/{len(inputs)} observations disagree with the public controller rules. '
                         'While walking: no ground means fall; otherwise dig wins; otherwise both bumps toggle, '
                         'left bump selects right and right bump selects left. Selecting the current direction holds it. '
                         'Fall/dig preserve direction and ignore bumps, including entry/exit edges. Outputs precede the step edge.')
    (run / 'result.json').write_text(json.dumps(result, indent=2))
    return result
