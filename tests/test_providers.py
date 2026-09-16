"""Request shaping per provider, checked against a mock transport (no network, no keys)."""
import json

import httpx

from openchip.config import ModelConfig
from openchip.models.adapter import ModelAdapter, write_keys_file, read_keys_file, KEYS_FILE


def _adapter(provider, model, handler, key="k-test"):
    cfg = ModelConfig(provider=provider, model=model, extra_body={"reasoning_effort": "low", "chat_template_kwargs": {"x": 1}})
    ad = ModelAdapter(cfg, api_key=key)
    ad.client = httpx.Client(base_url=ad.base_url, transport=httpx.MockTransport(handler), headers=ad.client.headers)
    return ad


def test_openai_body_has_no_vllm_extras():
    seen = {}
    def handler(req):
        seen["url"] = str(req.url); seen["auth"] = req.headers.get("authorization"); seen["body"] = json.loads(req.content)
        return httpx.Response(200, json={"id": "x", "model": "gpt-5", "choices": [{"message": {"content": '{"a":1}'}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 3, "completion_tokens": 2}})
    ad = _adapter("openai", "gpt-5", handler)
    r = ad.chat([{"role": "system", "content": "s"}, {"role": "user", "content": "u"}], json_schema={"type": "object"})
    assert r.ok and r.text == '{"a":1}' and r.prompt_tokens == 3
    assert seen["url"].startswith("https://api.openai.com/v1/chat/completions") and seen["auth"] == "Bearer k-test"
    assert "chat_template_kwargs" not in seen["body"] and seen["body"]["reasoning_effort"] == "low"
    assert seen["body"]["response_format"]["type"] == "json_schema"


def test_openrouter_headers_and_schema_fallback():
    calls = []
    def handler(req):
        body = json.loads(req.content); calls.append(body)
        if "response_format" in body:
            return httpx.Response(400, json={"error": "unsupported"})
        return httpx.Response(200, json={"choices": [{"message": {"content": 'here: {"b": 2}'}, "finish_reason": "stop"}], "usage": {}})
    ad = _adapter("openrouter", "openai/gpt-oss-120b", handler)
    r = ad.chat([{"role": "user", "content": "u"}], json_schema={"type": "object"})
    assert r.ok and len(calls) == 2 and "response_format" not in calls[1]
    assert ad.client.headers.get("x-title") == "OpenChip" and ad.base_url.startswith("https://openrouter.ai")


def test_anthropic_messages_api_and_forced_tool():
    seen = {}
    def handler(req):
        seen["url"] = str(req.url); seen["hdr"] = dict(req.headers); seen["body"] = json.loads(req.content)
        return httpx.Response(200, json={"id": "m", "model": "claude-sonnet-5", "stop_reason": "tool_use",
                                         "content": [{"type": "tool_use", "name": "emit", "input": {"module_name": "x"}}], "usage": {"input_tokens": 5, "output_tokens": 7}})
    ad = _adapter("anthropic", "claude-sonnet-5", handler, key="sk-ant-test")
    r = ad.chat([{"role": "system", "content": "sys"}, {"role": "user", "content": "u"}], json_schema={"type": "object", "properties": {"module_name": {"type": "string"}}})
    assert r.ok and json.loads(r.text) == {"module_name": "x"} and r.completion_tokens == 7
    assert seen["url"] == "https://api.anthropic.com/v1/messages" and seen["hdr"]["x-api-key"] == "sk-ant-test" and "authorization" not in seen["hdr"]
    assert seen["body"]["system"] == "sys" and seen["body"]["tool_choice"] == {"type": "tool", "name": "emit"} and seen["body"]["messages"][0]["role"] == "user"


def test_keys_file_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr("openchip.models.adapter.KEYS_FILE", tmp_path / "keys.env")
    write_keys_file({"OPENROUTER_API_KEY": "or-1", "OPENAI_API_KEY": "oa-1"})
    write_keys_file({"OPENAI_API_KEY": ""})
    assert read_keys_file() == {"OPENROUTER_API_KEY": "or-1"}
    cfg = ModelConfig(provider="openrouter", model="m")
    from openchip.models.adapter import resolve_api_key
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False); monkeypatch.delenv("OPENCHIP_MODEL_API_KEY", raising=False)
    assert resolve_api_key(cfg) == "or-1"
