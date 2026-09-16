"""Human delivery report for the recorded outcome of a composed design."""
from pathlib import Path


def render_composition_report(outcome: dict) -> str:
    """Render recorded evidence only; never reinterpret it as new verification."""
    accepted = outcome.get('accepted') is True
    lines = ['# Composed design', '',
             f"State: **{outcome.get('state', 'unknown')}**.",
             f"Recorded system acceptance: **{'accepted' if accepted else 'not accepted'}**.", '']
    if outcome.get('reason'):
        lines += [f"Reason: {outcome['reason']}", '']
    lines += ['This report summarizes saved evidence; it does not run new checks.',
              'Simulation and bounded formal results apply only to their recorded scope.', '',
              '[Original request](request.md) · [Machine-readable outcome](outcome.json)', '']
    original_root = Path(outcome.get('request') or 'request.md').parent

    def stage(label: str, data: dict | None):
        lines.extend([f'## {label}', ''])
        if not data:
            lines.extend(['No stage outcome was recorded. This stage has no recorded acceptance.', ''])
            return
        verdict = 'accepted' if data.get('accepted') is True else 'not accepted'
        if data.get('provisional'):
            verdict += '; **provisional**'
        lines.extend([f'Recorded stage result: {verdict}.', '',
                      data.get('status_line') or f"State: {data.get('state', 'unknown')}", ''])
        if data.get('reason'):
            lines.extend([f"Reason: {data['reason']}", ''])
        vote = data.get('reference_consensus') or {}
        if vote:
            lines.extend([f"Reference vote: `{vote.get('outcome', 'unknown')}`; "
                          f"confidence: {vote.get('confidence', 'not recorded')}.", ''])
        for key in ('unresolved', 'unsupported'):
            if data.get(key):
                lines.extend([f"{key.capitalize()}: " + '; '.join(map(str, data[key])), ''])
        links = []
        for key, title in [('contract', 'Contract'), ('rtl', 'RTL'),
                           ('reference', 'Reference'), ('properties', 'Formal properties'),
                           ('final_evidence', 'Tool evidence')]:
            value = (data.get('artifacts') or {}).get(key)
            if not value:
                continue
            try:
                path = Path(value).relative_to(original_root).as_posix()
            except ValueError:
                # Do not fabricate a portable link to an artifact outside the package.
                lines.extend([f'{title} was recorded outside this package: `{value}`', ''])
            else:
                links.append(f'[{title}](<{path}>)')
        if links:
            lines.extend([' · '.join(links), ''])
        for key in ('rtl_sha256', 'reference_sha256', 'contract_sha256'):
            value = (data.get('artifacts') or {}).get(key)
            if value:
                lines.append(f'- {key}: `{value}`')
        lines.append('')

    for name, leaf in (outcome.get('leaves') or {}).items():
        stage(f'Leaf: {name}', leaf)
    stage('Integration', outcome.get('integration'))
    lines.extend(['## Run scope', '',
                  f"Model: `{outcome.get('model', 'not recorded')}`; "
                  f"revision: `{outcome.get('model_revision', 'not recorded')}`.", ''])
    for key, label in [('elapsed_s', 'Elapsed seconds'), ('primary_model_calls', 'Primary model calls'),
                       ('primary_model_tokens', 'Primary model tokens')]:
        if key in outcome:
            lines.append(f"- {label}: {outcome[key]}")
    lines.extend(['', outcome.get('scope') or 'See the individual stage evidence for verification scope.', '',
                  'Independent development-oracle results, when present, are separate evidence and do not '
                  'override the recorded system acceptance.', ''])
    return '\n'.join(lines)
