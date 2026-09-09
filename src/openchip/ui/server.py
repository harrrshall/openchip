"""OpenChip local UI: a small JSON API plus one static page. No third-party dependencies.

Run with `openchip ui` (default http://127.0.0.1:8765). Keys pasted in Settings are stored in
~/.config/openchip/keys.env (mode 600), never in the workspace or the repository.
"""
from __future__ import annotations

import json
import os
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Optional
from urllib.parse import parse_qs, urlparse

from ..config import Config, ModelConfig
from ..models.adapter import PROVIDER_DEFAULTS, ModelAdapter, read_keys_file, write_keys_file
from ..runtime.run import Runner
from ..runtime.store import RunStore
from ..runtime.workspace import Workspace
from ..tools.base import tool_version, which

STATIC = Path(__file__).with_name("static")
UI_SETTINGS = Path(os.environ.get("OPENCHIP_UI_SETTINGS", Path.home() / ".config" / "openchip" / "ui.json"))
WORKSPACES = Path(os.environ.get("OPENCHIP_WORKSPACES", Path.home() / "openchip-workspaces"))

PRESETS = {
    "openrouter": ["openai/gpt-oss-120b", "qwen/qwen3.8-27b", "anthropic/claude-sonnet-5", "openai/gpt-5-codex"],
    "openai": ["gpt-5-codex", "gpt-5", "gpt-oss-120b"],
    "anthropic": ["claude-sonnet-5", "claude-opus-5", "claude-haiku-4-5-20251001"],
    "openai-compatible": ["openai/gpt-oss-120b", "Qwen/Qwen3.8-27B", "Qwen/Qwen3-8B"],
}


class UIState:
    def __init__(self, base_cfg: Config):
        self.base_cfg = base_cfg
        self.lock = threading.Lock()
        self.logs: dict[str, list[dict]] = {}      # workspace name -> log lines
        self.threads: dict[str, threading.Thread] = {}
        self.settings = self._load_settings()

    # -- settings -------------------------------------------------------------------------
    def _load_settings(self) -> dict:
        try:
            return json.loads(UI_SETTINGS.read_text())
        except OSError:
            m = self.base_cfg.model
            return {"provider": m.provider, "model": m.model, "base_url": m.base_url}

    def save_settings(self, data: dict) -> dict:
        provider = data.get("provider") or self.settings.get("provider") or "openai-compatible"
        if provider not in PROVIDER_DEFAULTS:
            raise ValueError("unknown provider")
        self.settings = {"provider": provider, "model": (data.get("model") or self.settings.get("model") or "").strip(),
                         "base_url": (data.get("base_url") or "").strip() or PROVIDER_DEFAULTS[provider]["base_url"]}
        UI_SETTINGS.parent.mkdir(parents=True, exist_ok=True)
        UI_SETTINGS.write_text(json.dumps(self.settings, indent=1))
        key = (data.get("api_key") or "").strip()
        if key:
            write_keys_file({PROVIDER_DEFAULTS[provider]["key_env"]: key})
        return self.public_settings()

    def public_settings(self) -> dict:
        provider = self.settings.get("provider", "openai-compatible")
        env = PROVIDER_DEFAULTS[provider]["key_env"]
        key = os.environ.get(env) or read_keys_file().get(env) or ""
        return {**self.settings, "key_env": env, "key_present": bool(key), "key_hint": (key[:6] + "…" + key[-4:]) if len(key) > 12 else ("set" if key else ""),
                "presets": PRESETS.get(provider, [])}

    def config(self) -> Config:
        cfg = Config.load()
        m = cfg.model
        m.provider = self.settings.get("provider", m.provider)  # type: ignore[assignment]
        m.model = self.settings.get("model") or m.model
        m.base_url = self.settings.get("base_url") or PROVIDER_DEFAULTS[m.provider]["base_url"]
        m.api_key_env = PROVIDER_DEFAULTS[m.provider]["key_env"]
        if m.provider != "openai-compatible":
            m.thinking = False
            m.thinking_roles = []
            m.extra_body = {}
        return cfg

    # -- toolchain / connectivity ------------------------------------------------------------
    def doctor(self) -> dict:
        cfg = self.config()
        tools = {}
        for name in ("iverilog", "vvp", "verilator", "yosys", "sby"):
            exe = getattr(cfg.tools, name)
            path = which(exe)
            tools[name] = {"ok": bool(path), "version": tool_version(exe, ("-V",) if name in ("iverilog", "vvp", "yosys") else ("--version",)) if path else ""}
        return {"tools": tools, "tools_ok": all(tools[t]["ok"] for t in ("iverilog", "vvp", "verilator", "yosys"))}

    def test_connection(self) -> dict:
        cfg = self.config()
        ad = ModelAdapter(cfg.model)
        h = ad.health()
        if h.get("ok"):
            r = ad.chat([{"role": "user", "content": "Reply with the single word OK."}], role="ping", max_tokens=8, thinking=False)
            h["ping"] = {"ok": r.ok and "OK" in r.text.upper(), "latency_s": round(r.latency_s, 2), "error": r.error, "reply": r.text[:40]}
        return h

    # -- runs -----------------------------------------------------------------------------------
    def start_run(self, name: str, request: str, budget_s: float, change: Optional[str] = None) -> dict:
        WORKSPACES.mkdir(parents=True, exist_ok=True)
        safe = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in name.strip())[:40] or time.strftime("design-%H%M%S")
        ws = Workspace(WORKSPACES / safe)
        if change is None:
            if ws.root.exists() and any(ws.root.iterdir()):
                safe = f"{safe}-{time.strftime('%H%M%S')}"
                ws = Workspace(WORKSPACES / safe)
            ws.init(request=request, name=safe)
        cfg = self.config()
        logs = self.logs.setdefault(safe, [])

        def log(msg: str) -> None:
            logs.append({"t": time.time(), "msg": msg})

        runner = Runner(ws, cfg, log=log)
        if change is None:
            run_id = runner.start(request, budget_s=budget_s)
        else:
            run_id = runner.revise(change, budget_s=budget_s)

        def work() -> None:
            try:
                runner.execute()
            except Exception as e:  # noqa: BLE001
                log(f"[error] {type(e).__name__}: {e}")
                log(traceback.format_exc()[-800:])

        t = threading.Thread(target=work, name=f"run-{safe}", daemon=True)
        self.threads[safe] = t
        t.start()
        return {"workspace": safe, "run_id": run_id}

    def list_runs(self) -> list[dict]:
        out = []
        if not WORKSPACES.exists():
            return out
        for d in sorted(WORKSPACES.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
            ws = Workspace(d)
            if not ws.exists():
                continue
            entry: dict[str, Any] = {"workspace": d.name, "request": ws.request_text().strip()[:120], "state": "created", "step": "-", "accepted": None}
            if ws.db_path.is_file():
                store = RunStore(ws.db_path)
                runs = store.list_runs()
                if runs:
                    entry.update({"state": runs[0]["state"], "step": runs[0]["step"], "run_id": runs[0]["run_id"], "updated": runs[0]["updated"]})
                    full = store.get_run(runs[0]["run_id"])
                    entry["accepted"] = (full or {}).get("outcome", {}).get("accepted")
                store.close()
            out.append(entry)
        return out

    def run_detail(self, name: str, since: int = 0) -> dict:
        ws = Workspace(WORKSPACES / name)
        if not ws.exists():
            raise FileNotFoundError(name)
        detail: dict[str, Any] = {"workspace": name, "request": ws.request_text(), "logs": self.logs.get(name, [])[since:], "log_total": len(self.logs.get(name, [])),
                                  "alive": self.threads.get(name) is not None and self.threads[name].is_alive()}
        if ws.db_path.is_file():
            store = RunStore(ws.db_path)
            runs = store.list_runs()
            if runs:
                run = store.get_run(runs[0]["run_id"]) or {}
                detail.update({"run_id": runs[0]["run_id"], "state": run.get("state"), "step": run.get("step"), "outcome": run.get("outcome") or {},
                               "events": [{k: v for k, v in e.items() if k != "error" or v} for e in store.events(runs[0]["run_id"])][-60:]})
            store.close()
        spec = sorted(ws.dir("spec").glob("contract.v*.md"), key=lambda p: int(p.stem.split(".v")[1]))
        detail["contract_md"] = spec[-1].read_text() if spec else ""
        detail["contract_version"] = int(spec[-1].stem.split(".v")[1]) if spec else 0
        rep = ws.root / "reports" / "report.md"
        detail["report_md"] = rep.read_text() if rep.is_file() else ""
        rtl = sorted((ws.root / "rtl").glob("*.v"))
        detail["rtl"] = {p.name: p.read_text() for p in rtl[:3]}
        return detail


class Handler(BaseHTTPRequestHandler):
    state: UIState

    def log_message(self, fmt, *args):  # quiet
        pass

    def _send(self, code: int, body: Any, ctype: str = "application/json") -> None:
        data = body if isinstance(body, bytes) else json.dumps(body, default=str).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _json(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}") if n else {}

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        try:
            if u.path in ("/", "/index.html"):
                return self._send(200, (STATIC / "index.html").read_bytes(), "text/html; charset=utf-8")
            if u.path == "/api/status":
                return self._send(200, {"settings": self.state.public_settings(), "doctor": self.state.doctor(), "workspaces": str(WORKSPACES), "runs": self.state.list_runs()})
            if u.path == "/api/runs":
                return self._send(200, self.state.list_runs())
            if u.path.startswith("/api/runs/"):
                name = u.path.split("/")[3]
                return self._send(200, self.state.run_detail(name, int(q.get("since", ["0"])[0])))
            return self._send(404, {"error": "not found"})
        except FileNotFoundError as e:
            return self._send(404, {"error": str(e)})
        except Exception as e:  # noqa: BLE001
            return self._send(500, {"error": f"{type(e).__name__}: {e}"})

    def do_POST(self):
        u = urlparse(self.path)
        try:
            body = self._json()
            if u.path == "/api/settings":
                return self._send(200, self.state.save_settings(body))
            if u.path == "/api/test":
                return self._send(200, self.state.test_connection())
            if u.path == "/api/runs":
                req = (body.get("request") or "").strip()
                if len(req) < 20:
                    return self._send(400, {"error": "Describe the module in at least a sentence."})
                return self._send(200, self.state.start_run(body.get("name") or "", req, float(body.get("budget_s") or 1200)))
            if u.path.startswith("/api/runs/") and u.path.endswith("/revise"):
                name = u.path.split("/")[3]
                change = (body.get("change") or "").strip()
                if len(change) < 10:
                    return self._send(400, {"error": "Describe the change."})
                return self._send(200, self.state.start_run(name, "", float(body.get("budget_s") or 1200), change=change))
            return self._send(404, {"error": "not found"})
        except Exception as e:  # noqa: BLE001
            return self._send(500, {"error": f"{type(e).__name__}: {e}"})


def serve(host: str = "127.0.0.1", port: int = 8765, open_browser: bool = False) -> None:
    Handler.state = UIState(Config.load())
    httpd = ThreadingHTTPServer((host, port), Handler)
    url = f"http://{host}:{port}"
    print(f"OpenChip UI at {url}  (workspaces: {WORKSPACES})")
    if open_browser:
        import webbrowser
        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
