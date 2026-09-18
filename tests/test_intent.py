"""Intent review transport failures must never become reassuring judgments."""
import pytest
import httpx
from openchip import intent


def test_invalid_contracts_never_reach_provider(monkeypatch):
    def no_network(*args, **kwargs):
        pytest.fail('Invalid input reached provider')
    monkeypatch.setattr(httpx.Client, 'post', no_network)
    for contract in (False, 0, '', [], 'text'):
        with pytest.raises(ValueError):
            intent.analyze('Build a hardware counter.', contract=contract, api_key='test')


def test_upstream_error_body_never_exposes_credentials(monkeypatch):
    monkeypatch.setattr(httpx.Client, 'post', lambda *a, **k: httpx.Response(401, text='secret-provider-value'))
    with pytest.raises(intent.IntentError, match='HTTP 401') as error:
        intent.analyze('Build a hardware counter.', api_key='secret-provider-value')
    assert 'secret-provider-value' not in str(error.value)


def test_incomplete_review_is_not_success(monkeypatch):
    monkeypatch.setattr(httpx.Client, 'post', lambda *a, **k: httpx.Response(200, json={
        'model': intent.MODEL, 'answers': {}, 'usage': {'input_tokens': 1, 'output_tokens': 1}}))
    with pytest.raises(intent.IntentError, match='invalid or incomplete'):
        intent.analyze('Build a hardware counter.', api_key='test')


def test_cli_rejects_null_contract(tmp_path, monkeypatch, capsys):
    from openchip.cli.main import main
    path = tmp_path / 'contract.json'
    path.write_text('null')
    monkeypatch.setattr(intent, 'analyze', lambda *a, **k: pytest.fail('Null contract reached provider'))
    assert main(['intent', '--request', 'Build a hardware counter.', '--contract', str(path)]) == 2
    assert 'JSON object' in capsys.readouterr().err
