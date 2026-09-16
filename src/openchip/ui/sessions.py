"""Capability-isolated hosted sessions; provider credentials never enter saved config."""
from __future__ import annotations

import hashlib
import json
import math
import secrets
import sqlite3
import threading
import time
from http.cookies import SimpleCookie, CookieError
from pathlib import Path
from urllib.parse import urlparse

from ..config import Config
from ..models.adapter import ModelAdapter, PROVIDER_DEFAULTS
from .server import UIState, PRESETS

# Exact public endpoints prevent user-controlled requests to host/private services.
HOSTED_ENDPOINTS = {
    "openrouter": {"https://openrouter.ai/api/v1"},
    "openai": {"https://api.openai.com/v1", "https://opencode.ai/zen/go/v1"},
    "openai-responses": {"https://api.openai.com/v1"},
    "anthropic": {"https://api.anthropic.com"},
    "openai-compatible": {"https://opencode.ai/zen/go/v1"},
}
COOKIE = "__Host-openchip-session"


class HostedState(UIState):
    def __init__(self, base_cfg: Config, root: Path, manager):
        self.manager = manager
        self.provider_session_id = secrets.token_hex(16)
        self.root = root
        self.keys: dict[tuple[str, str], str] = {}
        self.last_used = time.monotonic()
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        super().__init__(base_cfg, workspaces=root / "projects", settings_path=root / "settings.json")

    def _load_settings(self):
        try:
            return json.loads(self.settings_path.read_text())
        except FileNotFoundError:
            return {"provider": "openai", "model": "", "base_url": "https://api.openai.com/v1",
                    "usd_per_million_tokens": None}

    def save_settings(self, data):
        with self.lock:
            provider = data.get("provider") or self.settings["provider"]
            url = (data.get("base_url") or PROVIDER_DEFAULTS.get(provider, {}).get("base_url", "")).rstrip("/")
            if url not in HOSTED_ENDPOINTS.get(provider, set()):
                raise ValueError("Unsupported hosted provider endpoint")
            model = (data.get("model") or self.settings.get("model") or "").strip()
            rate = data.get("usd_per_million_tokens")
            rate = None if rate in (None, "") else float(rate)
            if rate is not None and (not math.isfinite(rate) or rate < 0):
                raise ValueError("Invalid token rate")
            key = (data.get("api_key") or "").strip()
            if len(key) > 4096 or any(c in key for c in "\r\n\x00"):
                raise ValueError("Invalid API key")
            self.settings = dict(provider=provider, model=model, base_url=url, usd_per_million_tokens=rate)
            if key:
                self.keys[(provider, url)] = key
            self.settings_path.write_text(json.dumps(self.settings))
            return self.public_settings()

    def config(self):
        with self.lock:
            cfg = self.base_cfg.model_copy(deep=True)
            cfg.model.provider = self.settings["provider"]
            cfg.model.model = self.settings["model"]
            cfg.model.base_url = self.settings["base_url"]
            cfg.model.revision = "unknown"
            cfg.model.session_id = self.provider_session_id
            cfg.model.alt = cfg.model.review = None
            cfg.model.extra_body = {}
            cfg.model.user_agent = None
            cfg.model.thinking = False
            cfg.model.thinking_roles = []
            return cfg

    def public_settings(self):
        with self.lock:
            provider = self.settings["provider"]
            return {**self.settings, "key_present": bool(self.keys.get((provider, self.settings["base_url"]))),
                    "key_hint": "set for this session", "key_env": "", "presets": PRESETS.get(provider, []),
                    "providers": {name: {"base_url": sorted(urls)[0], "key_env": "",
                                         "presets": PRESETS.get(name, []), "allowed_urls": sorted(urls)}
                                  for name, urls in HOSTED_ENDPOINTS.items()}}

    def model_adapter(self, cfg):
        with self.lock:
            key = self.keys.get((cfg.model.provider, cfg.model.base_url))
            if not key or not cfg.model.model:
                raise ValueError("Add your model and API key in Settings")
            if cfg.model.base_url not in HOSTED_ENDPOINTS.get(cfg.model.provider, set()):
                raise ValueError("Unsupported hosted provider endpoint")
            # A nonempty explicit key bypasses every owner/env credential fallback.
            cfg.model.alt = cfg.model.review = None
            return ModelAdapter(cfg.model, api_key=key)

    def start_run(self, name, request, budget_s, change=None):
        with self.manager.lock, self.lock:
            if change is not None and not self.workspace_path(name).is_dir():
                raise FileNotFoundError("Unknown workspace")
            self.check_capacity()
            if any(t.is_alive() for t in self.threads.values()):
                raise ValueError("Wait for your active build to finish")
            self.model_adapter(self.config())  # reject before creating a workspace
            return super().start_run(name, request, min(budget_s, 1200), change)

    def check_capacity(self):
        active = sum(t.is_alive() for state in self.manager.states.values() for t in state.threads.values())
        if active >= 2:
            raise ValueError("Build capacity is busy. Please try again later")

    def resume_run(self, name):
        with self.manager.lock:
            self.check_capacity()
            if any(t.is_alive() for t in self.threads.values()):
                raise ValueError("Wait for your active build to finish")
            return super().resume_run(name)

    def record_http(self, method, path, code):
        # No request bodies, headers, cookie values, query strings or API keys.
        # Full submitted designs and tool evidence live in this session's projects.
        route = path if path in {"/", "/index.html", "/api/settings", "/api/status", "/api/test", "/api/runs"} else "/api/project" if path.startswith("/api/runs/") else "/other"
        with self.lock, sqlite3.connect(self.root / "activity.sqlite3") as db:
            db.execute("CREATE TABLE IF NOT EXISTS activity (at REAL, method TEXT, route TEXT, status INTEGER)")
            db.execute("INSERT INTO activity VALUES (?, ?, ?, ?)", (time.time(), method, route, code))


class HostedSessions:
    def __init__(self, cfg, root, origin):
        parsed = urlparse(origin)
        if parsed.scheme != "https" or not parsed.netloc or parsed.path or parsed.query or parsed.fragment:
            raise ValueError("OPENCHIP_HOSTED_ORIGIN must be an HTTPS origin")
        self.cfg, self.root, self.origin = cfg, root, origin
        self.states = {}
        self.lock = threading.RLock()
        root.mkdir(parents=True, exist_ok=True, mode=0o700)

    def select(self, cookie_header):
        cookies = SimpleCookie()
        try:
            cookies.load(cookie_header)
        except CookieError:
            pass
        token = cookies[COOKIE].value if COOKIE in cookies else ""
        if len(token) != 64 or any(c not in "0123456789abcdef" for c in token):
            token = secrets.token_hex(32)
        identity = hashlib.sha256(token.encode()).hexdigest()
        with self.lock:
            now = time.monotonic()
            for old_id, state in list(self.states.items()):
                if now - state.last_used > 3600 and not any(t.is_alive() for t in state.threads.values()):
                    del self.states[old_id]  # forget in-memory keys; retain user evidence
            if identity not in self.states:
                if len(self.states) >= 256:
                    raise ValueError("Session capacity is busy")
                self.states[identity] = HostedState(self.cfg, self.root / identity, self)
            state = self.states[identity]
            state.last_used = now
        return state, f"{COOKIE}={token}; Path=/; Secure; HttpOnly; SameSite=Strict; Max-Age=2592000"
