"""Model adapter for OpenAI-compatible chat endpoints (vLLM on the cloud instance by default).

The adapter is deliberately thin: it sends messages, optionally requests a JSON schema via
guided decoding, returns text plus usage, and never interprets the result. All model output
is validated by the caller as untrusted input.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx

from ..config import ModelConfig


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
    def __init__(self, cfg: ModelConfig, api_key: str = "EMPTY"):
        self.cfg = cfg
        self.client = httpx.Client(base_url=cfg.base_url, timeout=cfg.timeout_s,
                                   headers={"Authorization": f"Bearer {api_key}"})
        self.usage = Usage()

    # -- capability negotiation ---------------------------------------------------------
    def health(self) -> dict:
        """Report connectivity and served models without exposing secrets."""
        try:
            r = self.client.get("/models")
            r.raise_for_status()
            ids = [m.get("id") for m in r.json().get("data", [])]
            return {"ok": True, "base_url": self.cfg.base_url, "served_models": ids, "configured": self.cfg.model,
                    "configured_is_served": self.cfg.model in ids}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "base_url": self.cfg.base_url, "error": str(e)}

    # -- generation ----------------------------------------------------------------------
    def chat(
        self,
        messages: list[dict],
        role: str = "generic",
        json_schema: Optional[dict] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        seed: Optional[int] = None,
        thinking: Optional[bool] = None,
    ) -> ModelResponse:
        body: dict[str, Any] = {
            "model": self.cfg.model,
            "messages": messages,
            "max_tokens": max_tokens or self.cfg.max_tokens,
            "temperature": self.cfg.temperature if temperature is None else temperature,
            "top_p": self.cfg.top_p,
        }
        s = self.cfg.seed if seed is None else seed
        if s is not None:
            body["seed"] = s
        think = self.cfg.thinking if thinking is None else thinking
        extra = dict(self.cfg.extra_body)
        # Qwen3-style thinking switch (ignored by models that do not support it).
        extra.setdefault("chat_template_kwargs", {})["enable_thinking"] = bool(think)
        if json_schema is not None:
            body["response_format"] = {"type": "json_schema", "json_schema": {"name": "out", "schema": json_schema}}
        body.update(extra)
        t0 = time.monotonic()
        try:
            r = self.client.post("/chat/completions", json=body)
            r.raise_for_status()
            data = r.json()
            choice = data["choices"][0]
            msg = choice.get("message", {})
            text = msg.get("content") or ""
            reasoning = msg.get("reasoning_content") or msg.get("reasoning") or ""
            if not reasoning:
                text, reasoning = split_think(text)
            usage = data.get("usage", {})
            resp = ModelResponse(text=text, reasoning=reasoning, finish_reason=choice.get("finish_reason", ""),
                                 prompt_tokens=usage.get("prompt_tokens", 0), completion_tokens=usage.get("completion_tokens", 0),
                                 latency_s=time.monotonic() - t0, model=data.get("model", self.cfg.model), raw_id=data.get("id", ""))
        except Exception as e:  # noqa: BLE001
            resp = ModelResponse(text="", reasoning="", finish_reason="error", prompt_tokens=0, completion_tokens=0,
                                 latency_s=time.monotonic() - t0, model=self.cfg.model, error=f"{type(e).__name__}: {e}"[:500])
        self.usage.add(role, resp)
        return resp


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
                start = text.find(ms[0][: ms[0].find("\n")] if "\n" in ms[0] else ms[0])
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
        return json.loads(text)
    except Exception:  # noqa: BLE001
        pass
    blk = extract_code(text, ("json",))
    if blk:
        try:
            return json.loads(blk)
        except Exception:  # noqa: BLE001
            pass
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except Exception:  # noqa: BLE001
            return None
    return None
