"""Model adapter: one thin client for every supported provider.

Providers
  openai-compatible  vLLM or any OpenAI-style server (default; sends vLLM extras such as chat_template_kwargs)
  openai             api.openai.com (no vLLM extras; json_schema response_format supported)
  openrouter         openrouter.ai (OpenAI-style; response_format forwarded where the model supports it)
  opencode-go        opencode.ai/zen/go (OpenAI-style chat completions; same body as openrouter, no vLLM
                     extras; requires an x-opencode-session header, generated per adapter when absent)
  anthropic          api.anthropic.com Messages API; JSON output is obtained by forcing a tool call
  openai-responses   OpenAI Responses API (POST /responses); default base URL is OpenCode Go, whose
                     newest models are served there only. No guided decoding: a JSON-schema request
                     becomes an instruction in the prompt and the caller parses the object from text.

The adapter sends messages, optionally requests a JSON schema, returns text plus usage, and never
interprets the result. All model output is validated by the caller as untrusted input.
Keys are never logged. Resolution order: the configured env var, the provider's conventional env var
(OPENAI_API_KEY / OPENROUTER_API_KEY / ANTHROPIC_API_KEY), then ~/.config/openchip/keys.env.
"""
from __future__ import annotations

import json
import os
import re
import time
import uuid
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import httpx

from ..config import ModelConfig

# OpenCode Go serves these only through the Responses API (/responses), not chat completions.
GO_RESPONSES_ONLY = {"muse-spark-1.3-contributor", "muse-spark-1.2-contributor", "gpt-5.6-luna", "grok-4.6", "grok-4.5"}

PROVIDER_DEFAULTS = {
    "openai-compatible": {"base_url": "http://127.0.0.1:8000/v1", "key_env": "OPENCHIP_MODEL_API_KEY"},
    "openai": {"base_url": "https://api.openai.com/v1", "key_env": "OPENAI_API_KEY"},
    "openrouter": {"base_url": "https://openrouter.ai/api/v1", "key_env": "OPENROUTER_API_KEY"},
    "opencode-go": {"base_url": "https://opencode.ai/zen/go/v1", "key_env": "OPENCODE_GO_API_KEY"},
    "anthropic": {"base_url": "https://api.anthropic.com", "key_env": "ANTHROPIC_API_KEY"},
    "openai-responses": {"base_url": "https://opencode.ai/zen/go/v1", "key_env": "OPENCODE_GO_API_KEY"},
}
KEYS_FILE = Path(os.environ.get("OPENCHIP_KEYS_FILE", Path.home() / ".config" / "openchip" / "keys.env"))


def read_keys_file() -> dict[str, str]:
    out: dict[str, str] = {}
    try:
        for line in KEYS_FILE.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            out[k.strip().removeprefix("export ").strip()] = v.strip().strip('"').strip("'")
    except OSError:
        pass
    return out


def write_keys_file(updates: dict[str, str]) -> None:
    """Persist keys for the UI (mode 600). Empty values delete the entry."""
    KEYS_FILE.parent.mkdir(parents=True, exist_ok=True)
    cur = read_keys_file()
    for k, v in updates.items():
        if v:
            cur[k] = v
        else:
            cur.pop(k, None)
    KEYS_FILE.write_text("# OpenChip API keys (written by the UI). Never commit this file.\n" + "".join(f'{k}="{v}"\n' for k, v in cur.items()))
    try:
        KEYS_FILE.chmod(0o600)
    except OSError:
        pass


def resolve_api_key(cfg: ModelConfig) -> str:
    provider = cfg.provider if cfg.provider in PROVIDER_DEFAULTS else "openai-compatible"
    candidates = [cfg.api_key_env, PROVIDER_DEFAULTS[provider]["key_env"], "OPENCHIP_MODEL_API_KEY"]
    keys = read_keys_file()
    for name in candidates:
        val = os.environ.get(name) or keys.get(name)
        if val:
            return val
    return "EMPTY"


def resolve_base_url(cfg: ModelConfig) -> str:
    provider = cfg.provider if cfg.provider in PROVIDER_DEFAULTS else "openai-compatible"
    default = PROVIDER_DEFAULTS[provider]["base_url"]
    if cfg.base_url and (provider == "openai-compatible" or cfg.base_url != PROVIDER_DEFAULTS["openai-compatible"]["base_url"]):
        return cfg.base_url
    return default


# -- provider status -----------------------------------------------------------------------
PROVIDER_STATUS_KINDS = ("ok", "no_key", "invalid_key", "rate_limited", "quota", "unreachable", "server_error", "unknown")

_INVALID_KEY_WORDS = ("unauthorized", "invalid", "token", "authentication", "forbidden key", "api key")
_QUOTA_WORDS = ("quota", "budget", "balance", "usage limit", "credit", "insufficient_quota", "payment")
# OpenCode Go answers a 429 with a GoUsageLimitError body such as "Resets in 4hr 23min".
_RESETS_IN_RE = re.compile(r"resets?\s+in\s+((?:\d+\s*(?:hours?|hrs?|hr|h|minutes?|mins?|min|m|seconds?|secs?|sec|s)\b\s*)+)", re.I)
_DURATION_PART_RE = re.compile(r"(\d+)\s*(hours?|hrs?|hr|h|minutes?|mins?|min|m|seconds?|secs?|sec|s)\b", re.I)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_resets_in(text: str) -> Optional[float]:
    """Seconds from a human "Resets in 4hr 23min" phrase, or None when there is no such phrase."""
    m = _RESETS_IN_RE.search(text or "")
    if not m:
        return None
    total = 0.0
    for value, unit in _DURATION_PART_RE.findall(m.group(1)):
        u = unit.lower()
        total += int(value) * (3600.0 if u.startswith("h") else 60.0 if u.startswith("m") else 1.0)
    return total or None


@dataclass
class ProviderStatus:
    """One classified answer from the provider, shaped for the UI (see docs/product/ui-redesign-2026-09-15.md)."""
    kind: str = "unknown"
    message: str = ""
    retry_after_s: Optional[float] = None
    until: str = ""
    provider: str = ""
    model: str = ""
    checked_at: str = field(default_factory=_utc_now_iso)

    def as_dict(self) -> dict:
        return {"kind": self.kind, "message": self.message, "retry_after_s": self.retry_after_s, "until": self.until,
                "provider": self.provider, "model": self.model, "checked_at": self.checked_at}

    @property
    def ok(self) -> bool:
        return self.kind == "ok"


def _with_deadline(st: ProviderStatus) -> ProviderStatus:
    if st.retry_after_s and not st.until:
        st.until = (datetime.now(timezone.utc).replace(microsecond=0) + timedelta(seconds=st.retry_after_s)).isoformat().replace("+00:00", "Z")
    return st


def _body_message(text: str) -> str:
    """The provider's own message, taken from the usual JSON envelopes or the raw body."""
    text = (text or "").strip()
    if not text:
        return ""
    try:
        data = json.loads(text)
    except ValueError:
        return text[:300]
    if isinstance(data, str):
        return data[:300]
    if isinstance(data, dict):
        err = data.get("error")
        if isinstance(err, dict):
            for key in ("message", "detail", "reason", "type", "name"):
                v = err.get(key)
                if isinstance(v, str) and v.strip():
                    parts = [str(err.get(k)) for k in ("name", "type") if isinstance(err.get(k), str) and err.get(k) != v]
                    return (": ".join(parts + [v]) if key == "message" else v)[:300]
        if isinstance(err, str) and err.strip():
            return err[:300]
        for key in ("message", "detail", "name"):
            v = data.get(key)
            if isinstance(v, str) and v.strip():
                return v[:300]
    return text[:300]


def _retry_after_seconds(headers, body: str) -> Optional[float]:
    raw = None
    try:
        raw = headers.get("retry-after")
    except AttributeError:
        raw = None
    if raw:
        try:
            return max(float(raw), 0.0)
        except ValueError:
            pass  # a HTTP-date Retry-After is not parsed; the body phrase is tried next
    return parse_resets_in(body)


def classify_http(status_code: int, headers, body: str, provider: str = "", model: str = "") -> ProviderStatus:
    """Map one HTTP answer onto a ProviderStatus. Never raises; unknown shapes stay `unknown`."""
    msg = _body_message(body)
    low = (body or "").lower()
    st = ProviderStatus(provider=provider, model=model, message=msg)
    if status_code < 400:
        st.kind, st.message = "ok", ""
        return st
    if status_code == 429:
        st.kind = "rate_limited"
        st.retry_after_s = _retry_after_seconds(headers, body)
        return _with_deadline(st)
    if status_code == 402:
        st.kind = "quota"
        st.retry_after_s = parse_resets_in(body)
        return _with_deadline(st)
    if status_code == 403:
        if any(w in low for w in _QUOTA_WORDS):
            st.kind = "quota"
            st.retry_after_s = parse_resets_in(body)
            return _with_deadline(st)
        st.kind = "invalid_key" if any(w in low for w in _INVALID_KEY_WORDS) else "unknown"
        return st
    if status_code == 401:
        st.kind = "invalid_key"
        return st
    if 500 <= status_code < 600:
        st.kind = "server_error"
        st.retry_after_s = _retry_after_seconds(headers, body)
        return _with_deadline(st)
    st.kind = "unknown"
    return st


_UNREACHABLE_ERRORS = (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout, httpx.WriteTimeout,
                       httpx.PoolTimeout, httpx.TimeoutException, httpx.NetworkError)


def classify_exception(exc: BaseException, provider: str = "", model: str = "", api_key: str = "") -> ProviderStatus:
    """Map an exception raised by a call onto a ProviderStatus."""
    if isinstance(exc, httpx.HTTPStatusError):
        r = exc.response
        return classify_http(r.status_code, r.headers, r.text, provider, model)
    kind = "unreachable" if isinstance(exc, _UNREACHABLE_ERRORS) else "unknown"
    return ProviderStatus(kind=kind, provider=provider, model=model,
                          message=_scrub(f"{type(exc).__name__}: {exc}", api_key)[:300])


@dataclass
class ModelResponse:
    text: str
    reasoning: str
    finish_reason: str
    prompt_tokens: int
    completion_tokens: int
    latency_s: float
    model: str
    raw_id: str = ""
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error


@dataclass
class Usage:
    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_s: float = 0.0
    errors: int = 0
    history: list[dict] = field(default_factory=list)

    def add(self, role: str, r: ModelResponse) -> None:
        self.calls += 1
        self.prompt_tokens += r.prompt_tokens
        self.completion_tokens += r.completion_tokens
        self.latency_s += r.latency_s
        if r.error:
            self.errors += 1
        self.history.append({"role": role, "prompt_tokens": r.prompt_tokens, "completion_tokens": r.completion_tokens,
                             "latency_s": round(r.latency_s, 2), "finish": r.finish_reason, "error": r.error})

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


class ModelAdapter:
    def __init__(self, cfg: ModelConfig, api_key: Optional[str] = None):
        self.cfg = cfg
        self.provider = cfg.provider if cfg.provider in PROVIDER_DEFAULTS else "openai-compatible"
        self.base_url = resolve_base_url(cfg)
        self.api_key = api_key or resolve_api_key(cfg)
        headers = {"Content-Type": "application/json"}
        if cfg.user_agent:
            headers["User-Agent"] = cfg.user_agent
        for k, v in (cfg.extra_headers or {}).items():
            headers[str(k)] = str(v)
        if self.provider == "opencode-go" and not any(k.lower() == "x-opencode-session" for k in headers):
            # The gateway groups requests by session; a stable id per adapter instance is the minimum it accepts.
            headers["x-opencode-session"] = str(uuid.uuid4())
        self.session_id = next((v for k, v in headers.items() if k.lower() == "x-opencode-session"), "")
        if self.provider == "anthropic":
            headers.update({"x-api-key": self.api_key, "anthropic-version": "2023-06-01"})
        else:
            headers["Authorization"] = f"Bearer {self.api_key}"
            if self.provider == "openrouter":
                headers.update({"HTTP-Referer": "https://github.com/harrrshall/openchip", "X-Title": "OpenChip"})
        self.client = httpx.Client(base_url=self.base_url, timeout=cfg.timeout_s, headers=headers)
        self.usage = Usage()
        # Optional feed hook: called with {"kind": "provider", "status": dict, "attempt": n, "attempts": N, "sleep_s": s}
        self.on_event = None
        self.last_status = ProviderStatus(kind="no_key" if self.api_key in ("", "EMPTY") else "unknown",
                                          provider=self.provider, model=self.cfg.model,
                                          message="no API key found" if self.api_key in ("", "EMPTY") else "")


    _RETRY_STATUS = (429, 502, 503, 529)

    def _status(self, status_code: int, headers, body: str) -> ProviderStatus:
        st = classify_http(status_code, headers, body, self.provider, self.cfg.model)
        self.last_status = st
        return st

    def _emit(self, payload: dict) -> None:
        cb = self.on_event
        if cb is None:
            return
        try:
            cb(payload)
        except Exception:  # noqa: BLE001  a broken feed hook must never fail a model call
            pass

    def _post(self, path: str, body: dict):
        """POST with bounded backoff on rate limits and gateway hiccups (429/502/503/529).

        Every retry is classified and reported through `on_event` so the run feed can say why it waits.
        """
        delays = (5, 15, 45, 90)[: max(0, int(getattr(self, "max_retries", 4)))]   # max_retries=0 -> one attempt, no wait
        attempts = len(delays) + 1
        for attempt in range(attempts):
            try:
                r = self.client.post(path, json=body)
            except Exception as e:  # noqa: BLE001
                self.last_status = classify_exception(e, self.provider, self.cfg.model, self.api_key)
                raise
            st = self._status(r.status_code, r.headers, r.text if r.status_code >= 400 else "")
            if r.status_code not in self._RETRY_STATUS or attempt == len(delays):
                return r
            # A quota exhaustion, or a rate limit whose reset is minutes away, is not worth waiting for:
            # return at once so the run stops at its checkpoint with the cause visible and can be resumed later.
            if st.kind == "quota" or (st.retry_after_s or 0) > 300:
                return r
            wait = st.retry_after_s if st.retry_after_s else float(delays[attempt])
            wait = min(max(wait, 1.0), 120.0)
            self._emit({"kind": "provider", "status": st.as_dict(), "attempt": attempt + 1, "attempts": attempts, "sleep_s": wait})
            time.sleep(wait)
        return r

    # -- capability negotiation ---------------------------------------------------------
    def health(self) -> dict:
        """Connectivity and served-model check without exposing the key.

        The result is a ProviderStatus (kind/message/retry_after_s/until/provider/model/checked_at) plus the
        served-model detail the doctor command and the Settings modal show.
        """
        key_present = self.api_key not in ("", "EMPTY")
        base = {"provider": self.provider, "base_url": self.base_url, "configured": self.cfg.model, "key_present": key_present}
        if not key_present:
            st = ProviderStatus(kind="no_key", message="no API key found", provider=self.provider, model=self.cfg.model)
            self.last_status = st
            return {**base, **st.as_dict(), "ok": False, "error": st.message, "served_models": []}
        try:
            r = self.client.get("/v1/models" if self.provider == "anthropic" else "/models")
            self._status(r.status_code, r.headers, r.text if r.status_code >= 400 else "")
            r.raise_for_status()
            data = r.json().get("data", [])
            ids = [m.get("id") for m in data]
            served = self.cfg.model in ids if ids else None
            st = ProviderStatus(kind="ok", provider=self.provider, model=self.cfg.model)
            self.last_status = st
            return {**base, **st.as_dict(), "ok": True, "configured_is_served": served, "served_models": ids[:20], "error": ""}
        except Exception as e:  # noqa: BLE001
            st = classify_exception(e, self.provider, self.cfg.model, self.api_key)
            self.last_status = st
            return {**base, **st.as_dict(), "ok": False, "error": st.message or _scrub(str(e), self.api_key), "served_models": []}

    # -- generation ----------------------------------------------------------------------
    def chat(self, messages: list[dict], role: str = "generic", json_schema: Optional[dict] = None,
             max_tokens: Optional[int] = None, temperature: Optional[float] = None, seed: Optional[int] = None,
             thinking: Optional[bool] = None, reasoning_off: bool = False) -> ModelResponse:
        """`reasoning_off` turns the provider's reasoning effort down for this one call (escalation
        after a reply that spent the whole budget reasoning and returned no usable payload)."""
        t0 = time.monotonic()
        try:
            if self.provider == "anthropic":
                resp = self._chat_anthropic(messages, json_schema, max_tokens, temperature)
            elif self.provider == "openai-responses" or (self.provider == "opencode-go" and self.cfg.model in GO_RESPONSES_ONLY):
                resp = self._chat_responses(messages, json_schema, max_tokens, temperature, reasoning_off)
            else:
                resp = self._chat_openai(messages, json_schema, max_tokens, temperature, seed, thinking, reasoning_off)
            resp.latency_s = time.monotonic() - t0
            self.last_status = ProviderStatus(kind="ok", provider=self.provider, model=self.cfg.model)
        except Exception as e:  # noqa: BLE001
            st = classify_exception(e, self.provider, self.cfg.model, self.api_key)
            self.last_status = st
            resp = ModelResponse(text="", reasoning="", finish_reason="error", prompt_tokens=0, completion_tokens=0,
                                 latency_s=time.monotonic() - t0, model=self.cfg.model,
                                 error=_scrub(f"{type(e).__name__}: {e}", self.api_key)[:500])
            self._emit({"kind": "provider", "status": st.as_dict(), "attempt": 0, "attempts": 0, "sleep_s": 0.0})
        self.usage.add(role, resp)
        return resp

    def _chat_openai(self, messages, json_schema, max_tokens, temperature, seed, thinking, reasoning_off: bool = False) -> ModelResponse:
        body: dict[str, Any] = {
            "model": self.cfg.model,
            "messages": messages,
            "max_tokens": max_tokens or self.cfg.max_tokens,
            "temperature": self.cfg.temperature if temperature is None else temperature,
        }
        if self.provider == "openai-compatible":
            body["top_p"] = self.cfg.top_p
            s = self.cfg.seed if seed is None else seed
            if s is not None:
                body["seed"] = s
            think = self.cfg.thinking if thinking is None else thinking
            extra = dict(self.cfg.extra_body)
            extra.setdefault("chat_template_kwargs", {})["enable_thinking"] = bool(think)  # Qwen3-style switch
            if reasoning_off:
                extra.pop("reasoning_effort", None)
                extra.pop("reasoning", None)
            body.update(extra)
        elif self.provider in ("openrouter", "opencode-go"):
            extra = {k: v for k, v in self.cfg.extra_body.items() if k != "chat_template_kwargs"}
            if reasoning_off:
                extra.pop("reasoning", None)
                extra["reasoning_effort"] = "none"
            body.update(extra)
        elif self.provider == "openai":
            extra = {k: v for k, v in self.cfg.extra_body.items() if k in ("reasoning_effort",)}
            if reasoning_off:
                extra["reasoning_effort"] = "minimal"  # openai's lowest accepted value
            body.update(extra)
        if json_schema is not None:
            body["response_format"] = {"type": "json_schema", "json_schema": {"name": "out", "schema": json_schema}}
        r = self._post("/chat/completions", body)
        if r.status_code >= 400 and json_schema is not None and self.provider in ("openrouter", "opencode-go", "openai"):
            # Some routed models reject json_schema: retry without it and let the caller parse JSON from text.
            body.pop("response_format", None)
            body["messages"] = messages[:-1] + [{**messages[-1], "content": messages[-1]["content"] + "\n\nReply with a single JSON object only."}]
            r = self._post("/chat/completions", body)
        if r.status_code >= 400 and reasoning_off and "reasoning_effort" in body:
            # The provider does not accept the turned-down reasoning value: drop the key instead.
            body.pop("reasoning_effort", None)
            r = self._post("/chat/completions", body)
        r.raise_for_status()
        data = r.json()
        choice = data["choices"][0]
        msg = choice.get("message", {})
        text = msg.get("content") or ""
        reasoning = msg.get("reasoning_content") or msg.get("reasoning") or ""
        if not reasoning:
            text, reasoning = split_think(text)
        usage = data.get("usage", {}) or {}
        finish = choice.get("finish_reason") or "stop"
        if finish in ("max_tokens", "max_output_tokens"):  # gateways relaying Anthropic/Gemini stop reasons
            finish = "length"
        return ModelResponse(text=text, reasoning=reasoning, finish_reason=finish,
                             prompt_tokens=usage.get("prompt_tokens", 0) or 0, completion_tokens=usage.get("completion_tokens", 0) or 0,
                             latency_s=0.0, model=data.get("model", self.cfg.model), raw_id=data.get("id", ""))

    def _chat_responses(self, messages, json_schema, max_tokens, temperature, reasoning_off: bool = False) -> ModelResponse:
        """OpenAI Responses API. The endpoint accepts the chat messages unchanged as `input` (a system-role
        item is honoured) but has no `response_format`, so a schema request is asked for in the prompt."""
        convo = [{"role": m["role"], "content": m["content"]} for m in messages]
        if json_schema is not None:
            convo[-1] = {**convo[-1], "content": convo[-1]["content"] + "\n\nReply with a single JSON object only."}
        body: dict[str, Any] = {
            "model": self.cfg.model,
            "input": convo,
            "max_output_tokens": max_tokens or self.cfg.max_tokens,
            "temperature": self.cfg.temperature if temperature is None else temperature,
        }
        extra = dict(self.cfg.extra_body)
        extra.pop("chat_template_kwargs", None)  # vLLM-only switch
        effort = extra.pop("reasoning_effort", None) or (extra.pop("reasoning", None) or {}).get("effort")
        body.update(extra)
        if reasoning_off:
            effort = "low"  # the lowest effort every model on this endpoint accepts
        if effort:
            body["reasoning"] = {"effort": effort}
        r = self._post("/responses", body)
        if r.status_code >= 400 and "temperature" in body and "temperature" in r.text:
            body.pop("temperature")  # reasoning models such as gpt-5.x reject it outright
            r = self._post("/responses", body)
        if r.status_code >= 400 and "reasoning" in body and "reasoning" in r.text:
            body.pop("reasoning")  # the model does not accept this effort value
            r = self._post("/responses", body)
        r.raise_for_status()
        data = r.json()
        text_parts, summary = [], []
        for item in data.get("output", []) or []:
            if item.get("type") == "reasoning":
                summary += [s.get("text") or "" for s in (item.get("summary") or [])]
                continue
            for c in item.get("content") or []:
                if c.get("type") == "output_text":
                    text_parts.append(c.get("text") or "")
        text = "".join(text_parts) or (data.get("output_text") or "")
        reasoning = "".join(summary)
        if not reasoning:
            text, reasoning = split_think(text)
        usage = data.get("usage", {}) or {}
        finish = "stop"
        if data.get("status") == "incomplete":
            finish = "length" if (data.get("incomplete_details") or {}).get("reason") == "max_output_tokens" else "incomplete"
        return ModelResponse(text=text, reasoning=reasoning, finish_reason=finish,
                             prompt_tokens=usage.get("input_tokens", 0) or 0, completion_tokens=usage.get("output_tokens", 0) or 0,
                             latency_s=0.0, model=data.get("model", self.cfg.model), raw_id=data.get("id", ""))

    def _chat_anthropic(self, messages, json_schema, max_tokens, temperature) -> ModelResponse:
        system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
        convo = [{"role": m["role"], "content": m["content"]} for m in messages if m["role"] != "system"]
        body: dict[str, Any] = {
            "model": self.cfg.model,
            "max_tokens": max_tokens or self.cfg.max_tokens,
            "temperature": self.cfg.temperature if temperature is None else temperature,
            "messages": convo,
        }
        if system:
            body["system"] = system
        if json_schema is not None:
            body["tools"] = [{"name": "emit", "description": "Return the requested object.", "input_schema": json_schema}]
            body["tool_choice"] = {"type": "tool", "name": "emit"}
        r = self._post("/v1/messages", body)
        r.raise_for_status()
        data = r.json()
        text_parts, tool_json, reasoning = [], None, ""
        for block in data.get("content", []):
            if block.get("type") == "text":
                text_parts.append(block.get("text", ""))
            elif block.get("type") == "tool_use":
                tool_json = block.get("input")
            elif block.get("type") == "thinking":
                reasoning += block.get("thinking", "")
        text = json.dumps(tool_json) if tool_json is not None else "".join(text_parts)
        usage = data.get("usage", {}) or {}
        stop = data.get("stop_reason") or "end_turn"
        return ModelResponse(text=text, reasoning=reasoning, finish_reason="length" if stop == "max_tokens" else "stop",
                             prompt_tokens=usage.get("input_tokens", 0) or 0, completion_tokens=usage.get("output_tokens", 0) or 0,
                             latency_s=0.0, model=data.get("model", self.cfg.model), raw_id=data.get("id", ""))


def _scrub(text: str, key: str) -> str:
    return text.replace(key, "***") if key and len(key) > 6 else text


THINK_RE = re.compile(r"<think>(.*?)</think>", re.S)


def split_think(text: str) -> tuple[str, str]:
    m = THINK_RE.search(text)
    if not m:
        return text, ""
    return (text[: m.start()] + text[m.end():]).strip(), m.group(1).strip()


FENCE_RE = re.compile(r"```(?P<lang>[\w+-]*)\s*\n(?P<body>.*?)```", re.S)
MODULE_RE = re.compile(r"(?ms)^\s*(module\s+[A-Za-z_]\w*\b.*?^\s*endmodule\b)")
PY_START_RE = re.compile(r"(?m)^(?:import |from \w+ import |class Reference\b|def \w+\()")


def extract_code(text: str, langs: tuple[str, ...]) -> Optional[str]:
    """Return the last fenced block whose language tag is in `langs` (or untagged if none match).

    Fallback for models that answer with bare code (no fences): for Verilog, the span from the first
    `module` to the last `endmodule`; for Python, everything from the first import/class/def line.
    """
    blocks = list(FENCE_RE.finditer(text))
    for m in reversed(blocks):
        if m.group("lang").lower() in langs:
            return m.group("body").strip("\n") + "\n"
    for m in reversed(blocks):
        if not m.group("lang"):
            return m.group("body").strip("\n") + "\n"
    if not blocks:
        if {"verilog", "v", "sv", "systemverilog"} & set(langs):
            ms = MODULE_RE.findall(text)
            if ms:
                first = ms[0].split("\n", 1)[0]
                start = text.find(first)
                end = text.rfind("endmodule") + len("endmodule")
                if start != -1 and end > start:
                    return text[start:end].strip("\n") + "\n"
        if {"python", "py"} & set(langs):
            m = PY_START_RE.search(text)
            if m and "class Reference" in text:
                return text[m.start():].strip("\n") + "\n"
    return None


def _scan_objects(text: str, start: int) -> Optional[dict]:
    """Decode the first complete JSON object at or after `start`, ignoring whatever follows it.

    `json.JSONDecoder.raw_decode` stops at the end of the object, so trailing prose — or a truncated
    second object after a complete one — cannot defeat a complete object that appears earlier.
    """
    dec = json.JSONDecoder()
    i = text.find("{", start)
    while i != -1:
        try:
            obj, _ = dec.raw_decode(text, i)
        except ValueError:
            i = text.find("{", i + 1)
            continue
        if isinstance(obj, dict):
            return obj
        i = text.find("{", i + 1)
    return None


def extract_json(text: str) -> Optional[dict]:
    """Best-effort JSON object extraction from a model reply.

    Handles the shapes reasoning models produce: a bare object, a fenced block, an object preceded by
    reasoning text, an object followed by prose, and an object followed by a truncated second attempt.
    """
    text = text.strip()
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else None
    except Exception:  # noqa: BLE001
        pass
    blk = extract_code(text, ("json",))
    if blk:
        try:
            obj = json.loads(blk)
            if isinstance(obj, dict):
                return obj
        except Exception:  # noqa: BLE001
            pass
        obj = _scan_objects(blk, 0)
        if obj is not None:
            return obj
    # Greedy span first (an object containing prose-like braces stays intact), then the first
    # complete object anywhere in the text.
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        try:
            obj = json.loads(text[start:end + 1])
            if isinstance(obj, dict):
                return obj
        except Exception:  # noqa: BLE001
            pass
    return _scan_objects(text, 0)
