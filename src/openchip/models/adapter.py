"""Model adapter: one thin client for every supported provider.

Providers
  openai-compatible  vLLM or any OpenAI-style server (default; sends vLLM extras such as chat_template_kwargs)
  openai             api.openai.com (no vLLM extras; json_schema response_format supported)
  openrouter         openrouter.ai (OpenAI-style; response_format forwarded where the model supports it)
  anthropic          api.anthropic.com Messages API; JSON output is obtained by forcing a tool call

The adapter sends messages, optionally requests a JSON schema, returns text plus usage, and never
interprets the result. All model output is validated by the caller as untrusted input.
Keys are never logged. Resolution order: the configured env var, the provider's conventional env var
(OPENAI_API_KEY / OPENROUTER_API_KEY / ANTHROPIC_API_KEY), then ~/.config/openchip/keys.env.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

import httpx

from ..config import ModelConfig

PROVIDER_DEFAULTS = {
    "openai-compatible": {"base_url": "http://127.0.0.1:8000/v1", "key_env": "OPENCHIP_MODEL_API_KEY"},
    "openai": {"base_url": "https://api.openai.com/v1", "key_env": "OPENAI_API_KEY"},
    "openrouter": {"base_url": "https://openrouter.ai/api/v1", "key_env": "OPENROUTER_API_KEY"},
    "anthropic": {"base_url": "https://api.anthropic.com", "key_env": "ANTHROPIC_API_KEY"},
}
KEYS_FILE = Path(os.environ.get("OPENCHIP_KEYS_FILE", Path.home() / ".config" / "openchip" / "keys.env"))


def read_keys_file() -> dict[str, str]:
    out: dict[str, str] = {}
    try:
        for line in KEYS_FILE.read_text().splitlines():
            try:
                tokens = shlex.split(line, comments=True)
            except ValueError:
                continue
            if tokens and tokens[0] == "export":
                tokens = tokens[1:]
            if len(tokens) != 1 or "=" not in tokens[0]:
                continue
            k, v = tokens[0].split("=", 1)
            if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", k):
                out[k] = v
    except OSError:
        pass
    return out


def write_keys_file(updates: dict[str, str]) -> None:
    """Persist keys for the UI (mode 600). Empty values delete the entry."""
    KEYS_FILE.parent.mkdir(parents=True, exist_ok=True)
    cur = read_keys_file()
    for k, v in updates.items():
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", k):
            raise ValueError("Invalid credential environment-variable name")
        if any(c in v for c in "\r\n\x00"):
            raise ValueError("Credential values must be single-line text")
        if v:
            cur[k] = v
        else:
            cur.pop(k, None)
    # Values are literal data even when the deployment sources this file in bash.
    # Restrict permissions before writing, including when replacing an existing file.
    fd = os.open(KEYS_FILE, os.O_WRONLY | os.O_CREAT, 0o600)
    with os.fdopen(fd, "w") as target:
        os.fchmod(target.fileno(), 0o600)
        target.truncate(0)
        target.write("# OpenChip API keys (written by the UI). Never commit this file.\n"
                     + "".join(f"{k}={shlex.quote(v)}\n" for k, v in cur.items()))


def resolve_api_key(cfg: ModelConfig) -> str:
    provider = cfg.provider if cfg.provider in PROVIDER_DEFAULTS else "openai-compatible"
    candidates = [cfg.api_key_env, PROVIDER_DEFAULTS[provider]["key_env"], "OPENCHIP_MODEL_API_KEY"]
    keys = read_keys_file()
    for name in candidates:
        # A key explicitly saved in Settings must survive a stale inherited
        # environment, including after the service restarts. Candidate-name
        # priority still honors a configured custom credential variable.
        val = keys.get(name) or os.environ.get(name)
        if val:
            return val
    return "EMPTY"


def resolve_base_url(cfg: ModelConfig) -> str:
    provider = cfg.provider if cfg.provider in PROVIDER_DEFAULTS else "openai-compatible"
    default = PROVIDER_DEFAULTS[provider]["base_url"]
    if cfg.base_url and (provider == "openai-compatible" or cfg.base_url != PROVIDER_DEFAULTS["openai-compatible"]["base_url"]):
        return cfg.base_url
    return default


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
        if urlparse(self.base_url).hostname == "opencode.ai":
            headers["User-Agent"] = cfg.user_agent or "openchip/0.1"
            headers["x-opencode-session"] = cfg.session_id
        if self.provider == "anthropic":
            headers.update({"x-api-key": self.api_key, "anthropic-version": "2023-06-01"})
        else:
            headers["Authorization"] = f"Bearer {self.api_key}"
            if self.provider == "openrouter":
                headers.update({"HTTP-Referer": "https://github.com/harrrshall/openchip", "X-Title": "OpenChip"})
        self.client = httpx.Client(base_url=self.base_url, timeout=cfg.timeout_s, headers=headers)
        self.usage = Usage()

    # -- capability negotiation ---------------------------------------------------------
    def health(self) -> dict:
        """Connectivity and served-model check without exposing the key."""
        try:
            if self.provider == "anthropic":
                r = self.client.get("/v1/models")
            else:
                r = self.client.get("/models")
            r.raise_for_status()
            data = r.json().get("data", [])
            ids = [m.get("id") for m in data]
            served = self.cfg.model in ids if ids else None
            return {"ok": True, "provider": self.provider, "base_url": self.base_url, "configured": self.cfg.model,
                    "configured_is_served": served, "served_models": ids[:20], "key_present": self.api_key not in ("", "EMPTY")}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "provider": self.provider, "base_url": self.base_url, "configured": self.cfg.model,
                    "key_present": self.api_key not in ("", "EMPTY"), "error": _scrub(str(e), self.api_key)}

    # -- generation ----------------------------------------------------------------------
    def chat(self, messages: list[dict], role: str = "generic", json_schema: Optional[dict] = None,
             max_tokens: Optional[int] = None, temperature: Optional[float] = None, seed: Optional[int] = None,
             thinking: Optional[bool] = None) -> ModelResponse:
        t0 = time.monotonic()
        try:
            if self.provider == "anthropic":
                resp = self._chat_anthropic(messages, json_schema, max_tokens, temperature)
            else:
                resp = self._chat_openai(messages, json_schema, max_tokens, temperature, seed, thinking)
            resp.latency_s = time.monotonic() - t0
        except Exception as e:  # noqa: BLE001
            detail = f"{type(e).__name__}: {e}"
            if isinstance(e, httpx.HTTPStatusError):
                try:
                    error = e.response.json().get("error", {})
                    message = error.get("message", "") if isinstance(error, dict) else str(error)
                    if message:
                        detail = f"Provider HTTP {e.response.status_code}: {message}"
                except (ValueError, AttributeError):
                    pass
            resp = ModelResponse(text="", reasoning="", finish_reason="error", prompt_tokens=0, completion_tokens=0,
                                 latency_s=time.monotonic() - t0, model=self.cfg.model,
                                 error=_scrub(detail, self.api_key)[:500])
        self.usage.add(role, resp)
        return resp

    def _chat_openai(self, messages, json_schema, max_tokens, temperature, seed, thinking) -> ModelResponse:
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
            body.update(extra)
        elif self.provider == "openrouter":
            body.update({k: v for k, v in self.cfg.extra_body.items() if k != "chat_template_kwargs"})
        elif self.provider == "openai":
            body.update({k: v for k, v in self.cfg.extra_body.items() if k in ("reasoning_effort",)})
        if json_schema is not None:
            body["response_format"] = {"type": "json_schema", "json_schema": {"name": "out", "schema": json_schema}}
        r = self.client.post("/chat/completions", json=body)
        if r.status_code >= 400 and json_schema is not None and self.provider in ("openrouter", "openai"):
            # Some routed models reject json_schema: retry without it and let the caller parse JSON from text.
            body.pop("response_format", None)
            body["messages"] = messages[:-1] + [{**messages[-1], "content": messages[-1]["content"] + "\n\nReply with a single JSON object only."}]
            r = self.client.post("/chat/completions", json=body)
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
        r = self.client.post("/v1/messages", json=body)
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


def extract_json(text: str) -> Optional[dict]:
    """Best-effort JSON object extraction from a model reply."""
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
            return obj if isinstance(obj, dict) else None
        except Exception:  # noqa: BLE001
            pass
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        try:
            obj = json.loads(text[start:end + 1])
            return obj if isinstance(obj, dict) else None
        except Exception:  # noqa: BLE001
            return None
    return None
