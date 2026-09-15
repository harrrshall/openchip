"""Provider error classification and the retry feed, against a mock transport (no network, no keys)."""
import json
import time

import httpx
import pytest

from openchip.config import ModelConfig
from openchip.models.adapter import (PROVIDER_DEFAULTS, ModelAdapter, ProviderStatus, classify_http,
                                     parse_resets_in)


def _adapter(handler, provider="opencode-go", model="kimi-k3", key="k-test", **cfg_kw):
    cfg = ModelConfig(provider=provider, model=model, **cfg_kw)
    ad = ModelAdapter(cfg, api_key=key)
    ad.client = httpx.Client(base_url=ad.base_url, transport=httpx.MockTransport(handler), headers=ad.client.headers)
    return ad


def test_opencode_go_defaults_and_session_header():
    ad = _adapter(lambda req: httpx.Response(200, json={}))
    assert PROVIDER_DEFAULTS["opencode-go"] == {"base_url": "https://opencode.ai/zen/go/v1", "key_env": "OPENCODE_GO_API_KEY"}
    assert ad.base_url == "https://opencode.ai/zen/go/v1"
    assert len(ad.client.headers["x-opencode-session"]) == 36  # generated uuid4 when the caller supplied none
    supplied = _adapter(lambda req: httpx.Response(200, json={}), extra_headers={"x-opencode-session": "sess-1"})
    assert supplied.client.headers["x-opencode-session"] == "sess-1" and supplied.session_id == "sess-1"


def test_opencode_go_uses_the_openrouter_body(monkeypatch):
    seen = {}

    def handler(req):
        seen["url"] = str(req.url)
        seen["body"] = json.loads(req.content)
        seen["session"] = req.headers.get("x-opencode-session")
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}], "usage": {}})

    ad = _adapter(handler, extra_headers={"x-opencode-session": "sess-1"},
                  extra_body={"reasoning_effort": "low", "chat_template_kwargs": {"x": 1}})
    assert ad.chat([{"role": "user", "content": "u"}]).ok
    assert seen["url"] == "https://opencode.ai/zen/go/v1/chat/completions" and seen["session"] == "sess-1"
    assert "chat_template_kwargs" not in seen["body"] and "top_p" not in seen["body"] and "seed" not in seen["body"]
    assert seen["body"]["reasoning_effort"] == "low"  # the openrouter branch forwards extra_body as-is
    assert ad.last_status.kind == "ok"


def test_rate_limit_retries_and_reports_retry_after(monkeypatch):
    slept, events, calls = [], [], []
    monkeypatch.setattr(time, "sleep", slept.append)

    def handler(req):
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(429, headers={"Retry-After": "15"},
                                  json={"error": {"name": "GoUsageLimitError", "message": "Rate limit exceeded"}})
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}], "usage": {}})

    ad = _adapter(handler)
    ad.on_event = events.append
    r = ad.chat([{"role": "user", "content": "u"}])
    assert r.ok and len(calls) == 2 and slept == [15.0]
    assert len(events) == 1
    ev = events[0]
    assert ev["kind"] == "provider" and ev["attempt"] == 1 and ev["attempts"] == 5 and ev["sleep_s"] == 15.0
    st = ev["status"]
    assert st["kind"] == "rate_limited" and st["retry_after_s"] == 15.0 and st["provider"] == "opencode-go" and st["model"] == "kimi-k3"
    assert "GoUsageLimitError" in st["message"] and st["until"].endswith("Z")
    assert ad.last_status.kind == "ok"  # the retry succeeded, so the adapter's last word is ok


def test_rate_limit_exhausts_retries_and_stays_rate_limited(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda s: None)
    events = []
    ad = _adapter(lambda req: httpx.Response(429, json={"error": {"name": "GoUsageLimitError", "message": "Usage limit reached. Resets in 4hr 23min"}}))
    ad.on_event = events.append
    r = ad.chat([{"role": "user", "content": "u"}])
    assert not r.ok
    # A reset hours away is not worth waiting for: one attempt, no sleep, the failure reported at once.
    assert len(events) == 1 and events[0]["attempt"] == 0 and events[0]["status"]["kind"] == "rate_limited"
    st = ad.last_status
    assert st.kind == "rate_limited" and st.retry_after_s == 4 * 3600 + 23 * 60  # parsed from the body, no Retry-After header


def test_quota_403_body_classifies_as_quota():
    ad = _adapter(lambda req: httpx.Response(403, json={"error": {"message": "You have exceeded your monthly quota; add credit to continue."}}))
    r = ad.chat([{"role": "user", "content": "u"}])
    assert not r.ok
    st = ad.last_status
    assert st.kind == "quota" and "quota" in st.message and st.provider == "opencode-go"


def test_other_http_classifications():
    def st(code, body="", headers=None):
        return classify_http(code, httpx.Headers(headers or {}), body, "opencode-go", "kimi-k3").kind

    assert st(401, '{"error":"unauthorized"}') == "invalid_key"
    assert st(403, '{"error":{"message":"invalid token"}}') == "invalid_key"
    assert st(402, '{"error":"payment required"}') == "quota"
    assert st(503, "upstream down") == "server_error"
    assert st(418, "teapot") == "unknown"
    assert st(200) == "ok"
    assert parse_resets_in("Resets in 4hr 23min") == 4 * 3600 + 23 * 60
    assert parse_resets_in("no phrase here") is None


def test_connect_error_is_unreachable():
    def handler(req):
        raise httpx.ConnectError("name resolution failed")

    ad = _adapter(handler)
    r = ad.chat([{"role": "user", "content": "u"}])
    assert not r.ok and ad.last_status.kind == "unreachable"


def test_missing_key_is_no_key_before_any_call(monkeypatch, tmp_path):
    monkeypatch.setattr("openchip.models.adapter.KEYS_FILE", tmp_path / "keys.env")
    monkeypatch.delenv("OPENCODE_GO_API_KEY", raising=False)
    monkeypatch.delenv("OPENCHIP_MODEL_API_KEY", raising=False)
    ad = ModelAdapter(ModelConfig(provider="opencode-go", model="kimi-k3"))
    assert ad.last_status.kind == "no_key"
    h = ad.health()
    assert h["kind"] == "no_key" and h["ok"] is False and h["provider"] == "opencode-go"


def test_health_returns_provider_status_shape():
    ad = _adapter(lambda req: httpx.Response(200, json={"data": [{"id": "kimi-k3"}]}))
    h = ad.health()
    assert h["ok"] and h["kind"] == "ok" and h["configured_is_served"] is True
    assert set(ProviderStatus().as_dict()) <= set(h)
    bad = _adapter(lambda req: httpx.Response(401, json={"error": "invalid api key"}))
    hb = bad.health()
    assert hb["ok"] is False and hb["kind"] == "invalid_key" and "invalid" in hb["message"]


# -- the run feed and the outcome ---------------------------------------------------------------

def test_runner_logs_retries_as_provider_events(tmp_path, monkeypatch):
    """A retry inside a run reaches the run log and is stored as a `provider` event."""
    from openchip.config import Config
    from openchip.runtime.run import Runner
    from openchip.runtime.workspace import Workspace

    monkeypatch.setattr(time, "sleep", lambda s: None)
    calls = []

    def handler(req):
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(429, headers={"Retry-After": "15"}, json={"error": {"message": "slow down"}})
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}], "usage": {}})

    ws = Workspace(tmp_path / "ws")
    ws.init(request="an 8-bit counter")
    lines = []
    ad = _adapter(handler)
    r = Runner(ws, Config.load(), adapter=ad, log=lines.append)
    assert ad.on_event is not None  # the runner wired itself in
    rid = r.start("an 8-bit counter")
    ad.chat([{"role": "user", "content": "u"}], role="intake")
    assert "[provider] rate limited by opencode-go: retrying in 15 s (attempt 1 of 5)" in lines
    events = r.store.events(rid, "provider")
    assert len(events) == 1 and events[0]["status"]["kind"] == "rate_limited" and events[0]["sleep_s"] == 15.0


def test_run_that_dies_on_an_invalid_key_records_provider_status(tmp_path):
    """The outcome of a run killed by the provider carries the classification the UI shows."""
    from openchip.config import Config
    from openchip.runtime.run import Runner
    from openchip.runtime.workspace import Workspace

    ad = _adapter(lambda req: httpx.Response(401, json={"error": {"message": "invalid api key"}}))
    ws = Workspace(tmp_path / "ws")
    ws.init(request="an 8-bit counter")
    cfg = Config.load()
    cfg.verification.run_formal = False
    r = Runner(ws, cfg, adapter=ad, log=lambda m: None)
    rid = r.start("an 8-bit counter")
    out = r.execute()  # intake cannot parse a contract out of a failed call: the run parks at its checkpoint
    run = r.store.get_run(rid)
    assert out["state"] == "paused" and run["state"] == "paused" and run["step"] == "intake"
    ps = out["provider_status"]
    assert ps["kind"] == "invalid_key" and ps["provider"] == "opencode-go" and "invalid" in ps["message"]
    assert run["checkpoint"]["provider_status"]["kind"] == "invalid_key"  # the cause travels with the checkpoint
