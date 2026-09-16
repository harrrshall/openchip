"""OpenChip local UI: a small JSON API plus one static page. No third-party dependencies.

Run with `openchip ui` (default http://127.0.0.1:8765). Keys pasted in Settings are stored in
~/.config/openchip/keys.env (mode 600), never in the workspace or the repository.
"""
from __future__ import annotations

import json
import base64
import binascii
import hmac
import ipaddress
import io
import math
import re
import zipfile
import os
import threading
import time
import traceback
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Optional
from urllib.parse import parse_qs, urlparse, unquote
from .presentation import result_summary, stage_durations, contract_diff

from ..reporting.integrity import workspace_outcome, integrity_warning
from ..config import Config, ModelConfig
from ..models.adapter import PROVIDER_DEFAULTS, ModelAdapter, resolve_api_key, write_keys_file
from ..runtime.run import Runner
from ..runtime.store import RunStore
from ..runtime.workspace import Workspace
from ..tools.base import tool_version, which
from ..verification.sandbox import sandbox_status

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
        self.lock = threading.RLock()
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
        # One Settings transaction includes the provider identity and saved key.
        with self.lock:
            return self._save_settings(data)

    def _save_settings(self, data: dict) -> dict:
        provider = data.get("provider") or self.settings.get("provider") or "openai-compatible"
        if provider not in PROVIDER_DEFAULTS:
            raise ValueError("unknown provider")
        rate = data.get("usd_per_million_tokens", self.settings.get("usd_per_million_tokens"))
        rate = None if rate in (None, "") else float(rate)
        if rate is not None and (not math.isfinite(rate) or rate < 0):
            raise ValueError("Enter a nonnegative finite token rate.")
        self.settings = {"provider": provider, "model": (data.get("model") or self.settings.get("model") or "").strip(),
                         "base_url": (data.get("base_url") or "").strip() or PROVIDER_DEFAULTS[provider]["base_url"]}
        self.settings["usd_per_million_tokens"] = rate
        UI_SETTINGS.parent.mkdir(parents=True, exist_ok=True)
        UI_SETTINGS.write_text(json.dumps(self.settings, indent=1))
        key = (data.get("api_key") or "").strip()
        if key:
            write_keys_file({PROVIDER_DEFAULTS[provider]["key_env"]: key})
        return self.public_settings()

    def public_settings(self) -> dict:
        with self.lock:
            return self._public_settings()

    def _public_settings(self) -> dict:
        provider = self.settings.get("provider", "openai-compatible")
        env = PROVIDER_DEFAULTS[provider]["key_env"]
        key = resolve_api_key(self.config().model)
        if key == "EMPTY":
            key = ""
        return {**self.settings, "key_env": env, "key_present": bool(key), "key_hint": (key[:6] + "…" + key[-4:]) if len(key) > 12 else ("set" if key else ""),
                "presets": PRESETS.get(provider, [])}

    def config(self) -> Config:
        with self.lock:
            return self._config()

    def _config(self) -> Config:
        cfg = Config.load()
        m = cfg.model
        identity = (m.provider, m.model, m.base_url)
        m.provider = self.settings.get("provider", m.provider)  # type: ignore[assignment]
        m.model = self.settings.get("model") or m.model
        m.base_url = self.settings.get("base_url") or PROVIDER_DEFAULTS[m.provider]["base_url"]
        m.api_key_env = PROVIDER_DEFAULTS[m.provider]["key_env"]
        if identity != (m.provider, m.model, m.base_url):
            m.revision = "unknown"
        if m.provider != "openai-compatible":
            m.thinking = False
            m.thinking_roles = []
            if identity != (m.provider, m.model, m.base_url):
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
        tools["reference_sandbox"] = sandbox_status()
        return {"tools": tools, "tools_ok": all(tools[t]["ok"] for t in ("iverilog", "vvp", "verilator", "yosys", "reference_sandbox"))}

    def test_connection(self) -> dict:
        cfg = self.config()
        ad = ModelAdapter(cfg.model)
        h = ad.health()
        if h.get("ok"):
            # reasoning models spend output tokens before answering: give the ping room
            r = ad.chat([{"role": "user", "content": "Reply with the single word OK."}], role="ping", max_tokens=256, thinking=False)
            h["ping"] = {"ok": r.ok and bool(r.text.strip()), "latency_s": round(r.latency_s, 2), "error": r.error, "reply": r.text.strip()[:40]}
            h["ok"] = h["ping"]["ok"]
        return h

    # -- runs -----------------------------------------------------------------------------------
    def start_run(self, name: str, request: str, budget_s: float, change: Optional[str] = None) -> dict:
        if not math.isfinite(budget_s) or not 0 < budget_s <= 86400:
            raise ValueError("Budget must be positive and at most one day.")
        with self.lock:
            if change is not None:
                ws = Workspace(self.workspace_path(name))
                if not ws.exists():
                    raise FileNotFoundError("Unknown workspace")
                if not list((ws.root / "spec").glob("contract.v*.json")):
                    raise ValueError("This project has no contract to revise.")
                if self.threads.get(name) and self.threads[name].is_alive():
                    raise ValueError("Wait for the current run to finish before revising.")
            return self._start_run(name, request, budget_s, change)

    def _start_run(self, name: str, request: str, budget_s: float, change: Optional[str] = None) -> dict:
        WORKSPACES.mkdir(parents=True, exist_ok=True)
        safe = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in name.strip())[:40] or time.strftime("design-%H%M%S")
        ws = Workspace(WORKSPACES / safe)
        if change is None:
            base_name = safe
            while True:
                try:
                    ws.root.mkdir()
                    break
                except FileExistsError:
                    safe = f"{base_name}-{uuid.uuid4().hex[:12]}"
                ws = Workspace(WORKSPACES / safe)
            ws.init(request=request, name=safe)
        cfg = self.config()
        logs = self.logs[safe] = []

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
                if runner.run_id:
                    runner.store.set_state(runner.run_id, "failed", reason=str(e))
            finally:
                runner.store.close()

        t = threading.Thread(target=work, name=f"run-{safe}", daemon=True)
        self.threads[safe] = t
        t.start()
        return {"workspace": safe, "run_id": run_id}

    def _recovery_state(self, name: str, run: dict, store: RunStore) -> dict:
        alive = bool(self.threads.get(name) and self.threads[name].is_alive()) or store.lock_is_live(run["run_id"])
        interrupted = not alive and run.get("state") in {"created", "planned", "running", "paused"}
        retry_provider = False
        if not alive and run.get("state") in {"stalled", "failed"}:
            calls = store.events(run["run_id"], "model_call")
            last = calls[-1] if calls else {}
            error = str(last.get("error", ""))
            retryable = not last.get("ok", True) and bool(re.match(
                r"(?:Provider HTTP (?:408|429|5\d{2})(?::|$)|"
                r"(?:TimeoutError|ReadTimeout|ConnectTimeout|WriteTimeout|PoolTimeout|"
                r"ConnectError|ReadError|WriteError|RemoteProtocolError|ConnectionResetError):)", error))
            limits = run.get("config", {}).get("budget", {})
            elapsed = (run.get("outcome", {}).get("budget") or {}).get("elapsed_s")
            tokens = sum(call.get("prompt_tokens", 0) + call.get("completion_tokens", 0) for call in calls)
            # Fail closed without recorded accounting. Runner.resume independently
            # restores active time and all calls; offering retry never grants a new budget.
            remaining = (isinstance(elapsed, (int, float)) and math.isfinite(elapsed)
                         and 0 <= elapsed < limits.get("wall_time_s", 0)
                         and len(calls) < limits.get("max_model_calls", 0)
                         and tokens < limits.get("max_total_tokens", 0))
            retry_provider = retryable and remaining
        can_resume = (interrupted or retry_provider) and bool(run.get("checkpoint", {}).get("request")) and run.get("step") in {
            "intake", "review", "revise", "reference", "properties", "rtl", "verify", "report"}
        return {"alive": alive, "can_resume": can_resume,
                "retry_provider": bool(retry_provider and can_resume),
                "recovery_message": ("Provider request failed. Retry from the saved checkpoint using the remaining budget."
                                     if retry_provider and can_resume else
                                     "Build interrupted. Resume from the last saved checkpoint." if can_resume else ""),
                "state": "paused" if interrupted else run.get("state")}

    def resume_run(self, name: str) -> dict:
        with self.lock:
            ws = Workspace(self.workspace_path(name))
            if not ws.db_path.is_file():
                raise FileNotFoundError(name)
            store = RunStore(ws.db_path)
            try:
                run_id = store.latest_run_id()
                run = store.get_run(run_id) if run_id else None
                if not run or not self._recovery_state(name, run, store)["can_resume"]:
                    raise ValueError("This run has no recoverable checkpoint with remaining budget.")
                cfg = Config.model_validate(run["config"])
            finally:
                store.close()
            logs = self.logs.setdefault(name, [])
            runner = Runner(ws, cfg, log=lambda msg: logs.append({"t": time.time(), "msg": msg}))
            runner.resume(run_id)
            def work():
                try:
                    runner.execute()
                except Exception as e:
                    logs.append({"t": time.time(), "msg": f"[error] {type(e).__name__}: {e}"})
                finally:
                    runner.store.close()
            thread = threading.Thread(target=work, name=f"resume-{name}", daemon=True)
            self.threads[name] = thread
            thread.start()
            return {"workspace": name, "run_id": run_id}

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
                    entry["accepted"] = workspace_outcome(ws.root, (full or {}).get("outcome", {})).get("accepted")
                    if full:
                        entry.update(self._recovery_state(d.name, full, store))
                store.close()
            out.append(entry)
        return out

    def run_detail(self, name: str, since: int = 0) -> dict:
        ws = Workspace(self.workspace_path(name))
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
                detail.update(self._recovery_state(name, run, store))
                detail["stages"] = stage_durations(store.events(runs[0]["run_id"]), time.time() if detail["alive"] else run["updated"])
            store.close()
        spec = sorted(ws.dir("spec").glob("contract.v*.md"), key=lambda p: int(p.stem.split(".v")[1]))
        detail["contract_md"] = spec[-1].read_text() if spec else ""
        detail["contract_version"] = int(spec[-1].stem.split(".v")[1]) if spec else 0
        detail["contract_diff"] = contract_diff(spec)
        detail["outcome"] = workspace_outcome(ws.root, detail.get("outcome", {}))
        detail["result"] = result_summary(detail.get("outcome", {}), "running" if detail["alive"] else detail.get("state"))
        rate = self.settings.get("usd_per_million_tokens")
        tokens = (detail.get("outcome", {}).get("budget") or {}).get("tokens")
        detail["cost_estimate_usd"] = tokens * rate / 1_000_000 if tokens is not None and rate is not None else None
        rep = ws.root / "reports" / "report.md"
        detail["report_md"] = integrity_warning(detail["outcome"]) + (rep.read_text() if rep.is_file() else "")
        rtl = sorted((ws.root / "rtl").glob("*.v"))
        detail["rtl"] = {p.name: p.read_text() for p in rtl if not p.is_symlink() and p.resolve().is_relative_to(ws.root.resolve())}
        detail["files"] = self.deliverable_files(name)
        return detail

    def workspace_path(self, name: str) -> Path:
        root = WORKSPACES.resolve()
        path = (root / name).resolve()
        if path.parent != root or not name or name in {".", ".."}:
            raise FileNotFoundError("Unknown workspace")
        return path

    def deliverable_files(self, name: str) -> list[str]:
        root = self.workspace_path(name)
        return sorted(str(p.relative_to(root)) for folder in ("rtl", "spec", "reports", "verification", "reference", "properties", "retained")
                      for p in (root / folder).rglob("*")
                      if p.is_file() and not p.is_symlink() and p.resolve().is_relative_to(root)
                      and p.suffix in {".v", ".sv", ".md", ".json", ".txt", ".log", ".py", ".sby", ".ys", ".vcd"})

    def artifact(self, name: str, path: str) -> bytes:
        if path not in self.deliverable_files(name):
            raise FileNotFoundError("Unknown evidence file")
        return (self.workspace_path(name) / path).read_bytes()

    def bundle(self, name: str) -> bytes:
        buffer = io.BytesIO()
        contents = {path: self.artifact(name, path) for path in self.deliverable_files(name)}
        try:
            recorded = json.loads(contents.get("reports/outcome.json", b"{}"))
        except (ValueError, UnicodeDecodeError):
            recorded = {}
        current = workspace_outcome(self.workspace_path(name), recorded, contents)
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            for path, data in contents.items():
                archive.writestr(path, data)
            archive.writestr("CURRENT_WORKSPACE_STATUS.json", json.dumps(current, indent=2))
            warning = integrity_warning(current)
            if warning:
                archive.writestr("CURRENT_WORKSPACE_WARNING.md", warning)
        return buffer.getvalue()


class Handler(BaseHTTPRequestHandler):
    state: UIState
    auth_token: str = ""

    def _authorized(self) -> bool:
        host = self.headers.get("Host", "")
        if not self.auth_token:
            try:
                hostname = urlparse("http://" + host).hostname or ""
                local = hostname == "localhost" or ipaddress.ip_address(hostname).is_loopback
            except ValueError:
                local = False
            if not local:
                self._send(403, {"error": "Invalid host"})
                return False
        else:
            authorization = self.headers.get("Authorization", "")
            supplied = ""
            if authorization.startswith("Bearer "):
                supplied = authorization[7:]
            elif authorization.startswith("Basic "):
                try:
                    credentials = base64.b64decode(authorization[6:], validate=True).decode()
                    user, supplied = credentials.split(":", 1)
                    if user != "openchip":
                        supplied = ""
                except (ValueError, UnicodeDecodeError, binascii.Error):
                    pass
            if not hmac.compare_digest(supplied.encode(), self.auth_token.encode()):
                self.send_response(401)
                self.send_header("WWW-Authenticate", 'Basic realm="OpenChip", charset="UTF-8"')
                self.send_header("Content-Length", "0")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                return False
        origin = self.headers.get("Origin")
        if origin:
            parsed = urlparse(origin)
            if parsed.scheme not in {"http", "https"} or parsed.netloc.lower() != host.lower():
                self._send(403, {"error": "Cross-origin requests are not allowed"})
                return False
        return True

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
        if n < 0 or n > 1024 * 1024:
            raise ValueError("Request body exceeds the allowed size.")
        body = json.loads(self.rfile.read(n) or b"{}") if n else {}
        if not isinstance(body, dict):
            raise ValueError("Request body must be a JSON object.")
        for key in ("request", "name", "change", "provider", "model", "base_url", "api_key"):
            if key in body and not isinstance(body[key], str):
                raise ValueError(f"{key} must be a string.")
        return body

    def do_GET(self):
        if not self._authorized():
            return
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
                name = unquote(u.path.split("/")[3])
                if u.path.endswith("/bundle.zip"):
                    return self._send(200, self.state.bundle(name), "application/zip")
                if u.path.endswith("/artifact"):
                    return self._send(200, self.state.artifact(name, q.get("path", [""])[0]), "text/plain; charset=utf-8")
                return self._send(200, self.state.run_detail(name, int(q.get("since", ["0"])[0])))
            return self._send(404, {"error": "not found"})
        except FileNotFoundError as e:
            return self._send(404, {"error": str(e)})
        except Exception as e:  # noqa: BLE001
            return self._send(500, {"error": f"{type(e).__name__}: {e}"})

    def do_POST(self):
        if not self._authorized():
            return
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
                return self._send(200, self.state.start_run(body.get("name") or "", req, float(body.get("budget_s", 1200))))
            if u.path.startswith("/api/runs/") and u.path.endswith("/resume"):
                name = unquote(u.path.split("/")[3])
                return self._send(200, self.state.resume_run(name))
            if u.path.startswith("/api/runs/") and u.path.endswith("/revise"):
                name = u.path.split("/")[3]
                change = (body.get("change") or "").strip()
                if len(change) < 10:
                    return self._send(400, {"error": "Describe the change."})
                return self._send(200, self.state.start_run(name, "", float(body.get("budget_s", 1200)), change=change))
            return self._send(404, {"error": "not found"})
        except FileNotFoundError:
            return self._send(404, {"error": "Unknown workspace"})
        except (ValueError, TypeError):
            return self._send(400, {"error": "Invalid request. Check the fields and budget."})
        except Exception as e:  # noqa: BLE001
            return self._send(500, {"error": f"{type(e).__name__}: {e}"})


class UIHTTPServer(ThreadingHTTPServer):
    # Browser tabs can issue bursts while other requests are completing.
    request_queue_size = 64
    max_connection_workers = 64
    connection_idle_timeout_s = 15

    def __init__(self, *args, **kwargs):
        self._connection_slots = threading.BoundedSemaphore(self.max_connection_workers)
        super().__init__(*args, **kwargs)

    def get_request(self):
        request, address = super().get_request()
        # Authentication happens after headers are read. Even unauthenticated
        # peers must not retain a worker forever with an incomplete request.
        request.settimeout(self.connection_idle_timeout_s)
        return request, address

    def process_request(self, request, client_address):
        if not self._connection_slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._connection_slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._connection_slots.release()


def serve(host: str = "127.0.0.1", port: int = 8765, open_browser: bool = False) -> None:
    token = os.environ.get("OPENCHIP_UI_TOKEN", "")
    try:
        loopback = host == "localhost" or ipaddress.ip_address(host).is_loopback
    except ValueError:
        loopback = False
    if (not loopback or token) and len(token) < 32:
        raise ValueError("Set OPENCHIP_UI_TOKEN to a secret of at least 32 characters before exposing the UI.")
    Handler.auth_token = token
    Handler.state = UIState(Config.load())
    httpd = UIHTTPServer((host, port), Handler)
    url = f"http://{host}:{port}"
    print(f"OpenChip UI at {url}  (workspaces: {WORKSPACES})")
    if open_browser:
        import webbrowser
        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
