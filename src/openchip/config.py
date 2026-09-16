"""Validated configuration. No credentials live here; secrets come from the environment."""
from __future__ import annotations

import os
import re
import sys
import uuid
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, Field

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib


class ModelConfig(BaseModel):
    provider: Literal["openai-compatible", "openai", "openrouter", "anthropic"] = "openai-compatible"
    base_url: str = "http://127.0.0.1:8000/v1"
    model: str = "Qwen/Qwen3-8B"
    revision: str = "main"
    api_key_env: str = "OPENCHIP_MODEL_API_KEY"
    max_tokens: int = 10000
    temperature: float = 0.2
    top_p: float = 0.95
    seed: Optional[int] = 1234
    context_window: int = 32768
    timeout_s: float = 600.0
    thinking: bool = True
    thinking_roles: Optional[list[str]] = None  # None -> `thinking` applies to all roles; else only these roles think
    thinking_budget: int = 12000
    extra_body: dict = Field(default_factory=dict)
    user_agent: Optional[str] = None   # some gateways allow-list clients by User-Agent; set per provider if required
    session_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    # Optional second model for cross-family reference corroboration and an optional independent spec reviewer.
    alt: Optional["ModelConfig"] = None
    review: Optional["ModelConfig"] = None


class ToolsConfig(BaseModel):
    iverilog: str = "iverilog"
    vvp: str = "vvp"
    verilator: str = "verilator"
    yosys: str = "yosys"
    sby: str = "sby"
    timeout_s: float = 300.0


class BudgetConfig(BaseModel):
    wall_time_s: float = 3600.0
    max_repair_iterations: int = 4
    max_model_calls: int = 40
    max_total_tokens: int = 2_000_000
    max_candidates: int = 1


class ReviewConfig(BaseModel):
    enabled: bool = True          # independent spec review of the contract before any code is written
    apply_corrections: bool = True
    max_corrections: int = 8


class VerificationConfig(BaseModel):
    sim_cycles: int = 400
    seeds: list[int] = Field(default_factory=lambda: [1, 2, 3])
    require_lint: bool = True
    require_synth: bool = True
    corroborate: bool = True      # acceptance needs agreement with a second independent reference (or 2 of 3)
    run_formal: bool = True       # run SBY BMC when a property checker exists (extra evidence)
    require_formal: bool = False  # formal counterexample blocks acceptance
    formal_depth: int = 20
    formal_timeout_s: float = 300.0


def model_slug(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9.]+", "-", name.split("/")[-1]).strip("-")


class Config(BaseModel):
    model: ModelConfig = Field(default_factory=ModelConfig)
    tools: ToolsConfig = Field(default_factory=ToolsConfig)
    budget: BudgetConfig = Field(default_factory=BudgetConfig)
    review: ReviewConfig = Field(default_factory=ReviewConfig)
    verification: VerificationConfig = Field(default_factory=VerificationConfig)
    runs_dir: str = "runs"

    @classmethod
    def load(cls, path: Optional[str | Path] = None) -> "Config":
        data: dict = {}
        candidates = [Path(path)] if path else []
        env_path = os.environ.get("OPENCHIP_CONFIG")
        if env_path:
            candidates.append(Path(env_path))
        candidates += [Path("openchip.toml"), Path(__file__).resolve().parents[2] / "configs" / "default.toml"]
        for c in candidates:
            if c.is_file():
                data = tomllib.loads(c.read_text())
                break
        cfg = cls.model_validate(data)
        identity = (cfg.model.provider, cfg.model.model, cfg.model.base_url)
        # environment overrides for cloud/local switching
        if os.environ.get("OPENCHIP_MODEL_BASE_URL"):
            cfg.model.base_url = os.environ["OPENCHIP_MODEL_BASE_URL"]
        if os.environ.get("OPENCHIP_MODEL"):
            cfg.model.model = os.environ["OPENCHIP_MODEL"]
        if os.environ.get("OPENCHIP_MODEL_REVISION"):
            cfg.model.revision = os.environ["OPENCHIP_MODEL_REVISION"]
        if os.environ.get("OPENCHIP_EXTRA_BODY"):
            import json
            cfg.model.extra_body = json.loads(os.environ["OPENCHIP_EXTRA_BODY"])
        if os.environ.get("OPENCHIP_THINKING_ROLES") is not None:
            roles = [r for r in os.environ["OPENCHIP_THINKING_ROLES"].split(",") if r]
            cfg.model.thinking_roles = roles
        if os.environ.get("OPENCHIP_RUNS_DIR"):
            cfg.runs_dir = os.environ["OPENCHIP_RUNS_DIR"]
        if os.environ.get("OPENCHIP_PROVIDER"):
            cfg.model.provider = os.environ["OPENCHIP_PROVIDER"]  # type: ignore[assignment]
        if identity != (cfg.model.provider, cfg.model.model, cfg.model.base_url) and not os.environ.get("OPENCHIP_MODEL_REVISION"):
            cfg.model.revision = "unknown"
        if os.environ.get("OPENCHIP_MAX_TOKENS"):
            cfg.model.max_tokens = int(os.environ["OPENCHIP_MAX_TOKENS"])
        if os.environ.get("OPENCHIP_USER_AGENT"):
            cfg.model.user_agent = os.environ["OPENCHIP_USER_AGENT"]
        if os.environ.get("OPENCHIP_MODEL_API_KEY_ENV"):
            cfg.model.api_key_env = os.environ["OPENCHIP_MODEL_API_KEY_ENV"]
        if os.environ.get("OPENCHIP_REVIEW") in ("0", "false", "off"):
            cfg.review.enabled = False
        # second model (cross-family corroboration) from env: OPENCHIP_ALT_MODEL [+ _BASE_URL, _PROVIDER, _API_KEY_ENV]
        if os.environ.get("OPENCHIP_ALT_MODEL"):
            alt = cfg.model.alt or ModelConfig(model=os.environ["OPENCHIP_ALT_MODEL"])
            alt.model = os.environ["OPENCHIP_ALT_MODEL"]
            alt.base_url = os.environ.get("OPENCHIP_ALT_BASE_URL", alt.base_url)
            alt.provider = os.environ.get("OPENCHIP_ALT_PROVIDER", alt.provider)  # type: ignore[assignment]
            alt.api_key_env = os.environ.get("OPENCHIP_ALT_API_KEY_ENV", "OPENCHIP_ALT_API_KEY")
            alt.thinking_roles = alt.thinking_roles if alt.thinking_roles is not None else ["intake"]
            alt.alt = None
            cfg.model.alt = alt
        if os.environ.get("OPENCHIP_REVIEW_MODEL"):
            rv = cfg.model.review or ModelConfig(model=os.environ["OPENCHIP_REVIEW_MODEL"])
            rv.model = os.environ["OPENCHIP_REVIEW_MODEL"]
            rv.base_url = os.environ.get("OPENCHIP_REVIEW_BASE_URL", rv.base_url)
            rv.provider = os.environ.get("OPENCHIP_REVIEW_PROVIDER", rv.provider)  # type: ignore[assignment]
            rv.api_key_env = os.environ.get("OPENCHIP_REVIEW_API_KEY_ENV", "OPENCHIP_REVIEW_API_KEY")
            rv.review = None
            cfg.model.review = rv
        return cfg

    def api_key(self) -> str:
        from .models.adapter import resolve_api_key  # lazy: adapter imports this module
        return resolve_api_key(self.model)
