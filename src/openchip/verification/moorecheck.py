"""Replay shortest paths to every reachable Moore transition against the reference."""
from __future__ import annotations
import hashlib,json,tempfile,time
from collections import deque
from pathlib import Path
from ..contracts.moore import moore_scope
from ..contracts.schema import Contract
from .harness import run_reference
from .mooreformal import moore_contract_matches


def check_moore(contract: Contract, request: str, reference: Path, work: Path,
                timeout_s: float, python: str) -> dict | None:
    binding,incomplete=moore_scope(request)
    if not binding:
        return None
    result=dict(status='error',tables=0,rows=0,mismatches=[],checked_kinds=['moore_transition_table'],binding=binding)
    if incomplete:
        return {**result,'detail':'Provide the complete updated Moore table before checking this revision.'}
    if not moore_contract_matches(contract,binding):
        return {**result,'detail':'Contract ports, output timing or reset disagree with the Moore table.'}
    deadline=time.monotonic()+timeout_s
    rows=binding['rows'];initial=binding['initial'];paths={initial:[]};queue=deque([initial])
    while queue:
        state=queue.popleft()
        for bit in (0,1):
            target=rows[state][bit]
            if target not in paths:
                paths[target]=paths[state]+[bit];queue.append(target)
    work.mkdir(parents=True,exist_ok=True)
    run=Path(tempfile.mkdtemp(prefix='moore-',dir=work));cp=run/'contract.json';cp.write_text(contract.model_dump_json(indent=1))
    mismatches=[];observations=0;failed=0
    for index,(state,path) in enumerate(paths.items()):
        for bit in (0,1):
            # The final observation exposes the state reached by the tested edge.
            inputs=[{'in':x} for x in path+[bit,0]];current=initial;expected=[]
            for vector in inputs:
                expected.append({'out':rows[current][2]});current=rows[current][vector['in']]
            replay=run/f'{index}-{bit}-inputs.json';replay.write_text(json.dumps({'inputs':inputs}))
            (run/f'{index}-{bit}-expected.json').write_text(json.dumps(expected))
            remaining=deadline-time.monotonic()
            if remaining<=0:
                return {**result,'detail':'Independent Moore replay exceeded its budget.'}
            data=run_reference(reference,cp,0,len(inputs),run/f'{index}-{bit}-reference.json',python=python,timeout_s=remaining,replay=replay)
            if data.get('error') or len(data.get('outputs',[]))!=len(inputs):
                return {**result,'detail':'Moore reference replay failed: '+str(data.get('error') or 'incomplete output')[:600]}
            for cycle,(want,got) in enumerate(zip(expected,data['outputs'])):
                observations+=1
                if want!=got:
                    failed+=1
                    if len(mismatches)<6:mismatches.append(dict(target_state=state,transition_input=bit,cycle=cycle,request_says=want,reference_says=got))
    result.update(status='mismatch' if failed else 'ok',rows=observations,checked_cycles=observations,
                  reachable_states=len(paths),checked_transitions=2*len(paths),mismatch_vectors=failed,mismatches=mismatches,
                  reference_sha256=hashlib.sha256(reference.read_bytes()).hexdigest(),
                  detail=f'{failed}/{observations} observations disagree with the explicit Moore table. '
                         'Outputs decode current state; reference step observes before consuming the input.')
    (run/'result.json').write_text(json.dumps(result,indent=2))
    return result
