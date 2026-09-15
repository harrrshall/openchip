"""OpenChip local UI: a small JSON API plus one static page. No third-party dependencies.

Run with `openchip ui` (default http://127.0.0.1:8765). Keys pasted in Settings are stored in
~/.config/openchip/keys.env (mode 600), never in the workspace or the repository.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import traceback
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Optional
from urllib.parse import parse_qs, urlparse

from ..config import Config, ModelConfig
from ..models.adapter import PROVIDER_DEFAULTS, ModelAdapter, ProviderStatus, read_keys_file, write_keys_file
from ..reporting.report import sign_off_withheld
from ..runtime.run import Runner
from ..runtime.store import RunStore
from ..runtime.workspace import Workspace
from ..tools.base import tool_version, which

STATIC = Path(__file__).with_name("static")
UI_SETTINGS = Path(os.environ.get("OPENCHIP_UI_SETTINGS", Path.home() / ".config" / "openchip" / "ui.json"))
WORKSPACES = Path(os.environ.get("OPENCHIP_WORKSPACES", Path.home() / "openchip-workspaces"))

PRESETS = {
    "opencode-go": ["kimi-k3", "glm-5.3", "qwen3.8-max", "minimax-m3", "muse-spark-1.3-contributor", "gpt-5.6-luna", "grok-4.6", "deepseek-v4-flash"],
    "openrouter": ["openai/gpt-oss-120b", "qwen/qwen3.8-27b", "anthropic/claude-sonnet-5", "openai/gpt-5-codex"],
    "openai": ["gpt-5-codex", "gpt-5", "gpt-oss-120b"],
    "anthropic": ["claude-sonnet-5", "claude-opus-5", "claude-haiku-4-5-20251001"],
    "openai-compatible": ["openai/gpt-oss-120b", "Qwen/Qwen3.8-27B", "Qwen/Qwen3-8B"],
}


# -- session and stage derivation -------------------------------------------------------------
# The six stages of the strip in docs/product/ui-redesign-2026-09-15.md section 2, and the runner
# step each one covers (`properties` is part of the RTL stage; it prepares the formal properties).
STAGE_NAMES = ("Intake", "Review", "Reference", "RTL", "Verify", "Sign-off")
STEP_STAGE = {"intake": 0, "review": 1, "reference": 2, "properties": 3, "rtl": 3, "verify": 4, "report": 5, "done": 6}
REQUIRED_TOOLS = ("iverilog", "vvp", "verilator", "yosys")
# States that mean "this run stopped part-way through and nothing is working on it now". The stage
# strip must keep the progress it had: everything before the checkpoint step is done, the checkpoint
# step is the one that broke off, and the rest is still pending.
INTERRUPTED_STATES = ("paused", "failed", "stalled", "budget_exhausted")
_WITHHELD_RE = re.compile(r"SIGN-OFF WITHHELD: (.*?)(?:; the design needs the user|$)")


def withheld_reasons(outcome: dict, checkpoint: Optional[dict] = None) -> list[str]:
    """The sign-off gate's reasons, read back from the status line (or recomputed from the checkpoint)."""
    m = _WITHHELD_RE.search((outcome or {}).get("status_line") or "")
    raw = m.group(1) if m else ""
    if not raw and outcome and checkpoint:
        try:
            raw = sign_off_withheld(checkpoint)
        except Exception:  # noqa: BLE001  a partial checkpoint must not break the view
            raw = ""
    return [x.strip() for x in raw.split("; ") if x.strip()]


def session_result(state: str, accepted: Optional[bool], alive: bool, withheld: bool) -> str:
    """One of accepted | withheld | not_accepted | interrupted | failed | running | created."""
    if state in ("", "created"):
        return "created"
    if state == "failed":
        return "failed"
    if state == "completed":
        if withheld:
            return "withheld"
        return "accepted" if accepted else "not_accepted"
    if alive:
        return "running"
    if state in ("stalled", "budget_exhausted"):
        return "not_accepted"
    return "interrupted"  # planned / running with no live thread / paused


def state_reason(store: "RunStore", run_id: str, state: str) -> str:
    """Why the run stopped, as recorded with the state change (the provider cause for a paused run)."""
    if state not in INTERRUPTED_STATES:
        return ""
    for e in reversed(store.events(run_id, "state")):
        if e.get("state") == state and e.get("reason"):
            return str(e["reason"])[:300]
    return ""


def _last(events: list[dict], kind: str) -> dict:
    for e in reversed(events):
        if e.get("kind") == kind:
            return e
    return {}


def stage_details(run: dict, events: list[dict], outcome: dict) -> list[str]:
    """The one-line detail under each stage pill."""
    ck = run.get("checkpoint") or {}
    out = [""] * 6
    version = outcome.get("contract_version") or ck.get("contract_version")
    n_req = len(outcome.get("requirements") or [])
    if version:
        out[0] = f"contract v{version}" + (f", {n_req} requirement(s)" if n_req else "")
    elif _last(events, "contract_rejected"):
        out[0] = "contract rejected by the validator: " + str(_last(events, "contract_rejected").get("error", ""))[:120]
    rv = _last(events, "review") or (outcome.get("review") or {})
    if rv:
        applied = rv.get("applied")
        n_applied = len(applied) if isinstance(applied, list) else (applied or 0)
        rejected = rv.get("rejected")
        n_rejected = len(rejected) if isinstance(rejected, list) else (rejected or 0)
        unres = rv.get("unresolved")
        n_unres = len(unres) if isinstance(unres, list) else (unres or 0)
        out[1] = f"{rv.get('verdict') or 'reviewed'}: {n_applied} correction(s) applied, {n_rejected} rejected, {n_unres} unresolved"
    elif _last(events, "review_skipped"):
        out[1] = "review skipped: " + str(_last(events, "review_skipped").get("error", ""))[:120]
    cons = outcome.get("reference_consensus") or ck.get("consensus") or {}
    n_refs = len(cons.get("references") or []) or (1 if ck.get("reference_path") else 0)
    if cons.get("outcome"):
        out[2] = f"{n_refs} reference(s), arbitration: {cons['outcome']}"
    elif n_refs:
        out[2] = f"{n_refs} reference(s) derived"
    elif _last(events, "reference_rejected"):
        out[2] = "reference rejected: " + str(_last(events, "reference_rejected").get("error", ""))[:120]
    module = outcome.get("module") or ck.get("module_name") or ""
    if ck.get("rtl_path"):
        out[3] = f"module {module}" if module else "RTL generated"
        if ck.get("properties_path"):
            out[3] += "; formal properties written"
    elif _last(events, "rtl_rejected"):
        out[3] = "RTL rejected: " + str(_last(events, "rtl_rejected").get("reason", ""))[:120]
    history = outcome.get("history") or ck.get("history") or []
    v = _last(events, "verification")
    last = history[-1] if history else v
    if last:
        total = max(len(history), int(last.get("attempt", 0)) + 1)
        out[4] = f"attempt {int(last.get('attempt', 0)) + 1} of {total}: " + str(last.get("summary") or last.get("stage") or "")[:160]
    wh = withheld_reasons(outcome, ck)
    if wh:
        out[5] = "withheld: " + wh[0]
    elif outcome.get("accepted"):
        out[5] = "signed off" + (" (provisional)" if outcome.get("provisional") else "")
    elif outcome:
        out[5] = "not accepted" + (f": {outcome.get('reason')}" if outcome.get("reason") else "")
    return out


def derive_stages(run: dict, events: list[dict], outcome: dict, alive: bool) -> list[dict]:
    """pending | running | done | withheld | failed per stage, from the checkpoint step, events and outcome."""
    state = run.get("state") or "created"
    cur = STEP_STAGE.get(run.get("step") or "intake", 0)
    details = stage_details(run, events, outcome)
    wh = bool(withheld_reasons(outcome, run.get("checkpoint") or {}))
    # An interrupted run keeps its progress: a paused/failed/stalled/exhausted run, and a run still
    # marked `running` with no live thread, broke off at its checkpoint step.
    interrupted = state in INTERRUPTED_STATES or (state == "running" and not alive)
    stages = []
    for i, name in enumerate(STAGE_NAMES):
        if state in ("created", "planned") and not alive:
            status = "pending"
        elif i < cur:
            status = "done"
        elif i == cur:
            status = "running" if (state == "running" and alive) else ("failed" if interrupted else "pending")
        else:
            status = "pending"
        if state == "completed" and i < 5:
            status = "done"
        if i == 5 and outcome:
            status = "withheld" if wh else ("done" if outcome.get("accepted") else "failed")
        stages.append({"name": name, "status": status, "detail": details[i]})
    return stages


def model_calls_summary(events: list[dict], outcome: dict) -> dict:
    calls = [e for e in events if e.get("kind") == "model_call"]
    budget = outcome.get("budget") or {}
    tokens = sum(int(e.get("prompt_tokens") or 0) + int(e.get("completion_tokens") or 0) for e in calls)
    return {"count": len(calls) or int(budget.get("model_calls") or 0),
            "tokens": tokens or int(budget.get("tokens") or 0),
            "last_latency_s": float(calls[-1].get("latency_s") or 0.0) if calls else None}


def evidence_summary(outcome: dict, checkpoint: dict) -> dict:
    esc = outcome.get("model_escalations") or (checkpoint or {}).get("model_escalations") or []
    return {"attempts": outcome.get("history") or (checkpoint or {}).get("history") or [],
            # No outcome means no decision yet, which is not the same as "not accepted".
            "signoff": {"accepted": bool(outcome.get("accepted")) if outcome else None,
                        "withheld_reasons": withheld_reasons(outcome, checkpoint),
                        "provisional": bool(outcome.get("provisional")), "status_line": outcome.get("status_line") or ""},
            "unresolved": outcome.get("unresolved") or [], "assumptions": outcome.get("assumptions") or [],
            "escalations": esc, "model_escalations": esc}


class ToolchainMissing(Exception):
    def __init__(self, missing: list[str]):
        self.missing = missing
        super().__init__("missing toolchain: " + ", ".join(missing))


class RunAlive(Exception):
    pass


class NothingToResume(Exception):
    pass


class UIState:
    def __init__(self, base_cfg: Config):
        self.base_cfg = base_cfg
        self.lock = threading.Lock()
        self.logs: dict[str, list[dict]] = {}      # workspace name -> log lines
        self.threads: dict[str, threading.Thread] = {}
        self.runners: dict[str, Runner] = {}
        self.last_status: Optional[ProviderStatus] = None
        self.settings = self._load_settings()

    # -- settings -------------------------------------------------------------------------
    def _load_settings(self) -> dict:
        try:
            data = json.loads(UI_SETTINGS.read_text())
        except OSError:
            m = self.base_cfg.model
            data = {"provider": m.provider, "model": m.model, "base_url": m.base_url}
        if not data.get("session_id"):
            # One stable session id per install: OpenCode Go groups requests by `x-opencode-session`.
            data["session_id"] = str(uuid.uuid4())
            self._write_settings(data)
        return data

    @staticmethod
    def _write_settings(data: dict) -> None:
        UI_SETTINGS.parent.mkdir(parents=True, exist_ok=True)
        UI_SETTINGS.write_text(json.dumps(data, indent=1))

    def save_settings(self, data: dict) -> dict:
        provider = data.get("provider") or self.settings.get("provider") or "openai-compatible"
        if provider not in PROVIDER_DEFAULTS:
            raise ValueError("unknown provider")
        self.settings = {"provider": provider, "model": (data.get("model") or self.settings.get("model") or "").strip(),
                         "base_url": (data.get("base_url") or "").strip() or PROVIDER_DEFAULTS[provider]["base_url"],
                         "session_id": self.settings.get("session_id") or str(uuid.uuid4())}
        self._write_settings(self.settings)
        key = (data.get("api_key") or "").strip()
        if key:
            write_keys_file({PROVIDER_DEFAULTS[provider]["key_env"]: key})
        return self.public_settings()

    def public_settings(self) -> dict:
        provider = self.settings.get("provider", "openai-compatible")
        env = PROVIDER_DEFAULTS[provider]["key_env"]
        key = os.environ.get(env) or read_keys_file().get(env) or ""
        return {**self.settings, "key_env": env, "key_present": bool(key),
                "providers": sorted(PROVIDER_DEFAULTS), "key_hint": (key[:6] + "…" + key[-4:]) if len(key) > 12 else ("set" if key else ""),
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
        if m.provider == "opencode-go":
            m.extra_headers = {**(m.extra_headers or {}), "x-opencode-session": self.settings.get("session_id", "")}
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

    def missing_tools(self) -> list[str]:
        d = self.doctor()["tools"]
        return [t for t in REQUIRED_TOOLS if not d.get(t, {}).get("ok")]

    def provider_status(self, workspace: Optional[str] = None) -> dict:
        """The last classification for the configured provider, without touching the network."""
        cfg = self.config()
        m = cfg.model
        runner = self.runners.get(workspace or "")
        for candidate in ([runner] if runner else []):
            st = getattr(candidate.adapter, "last_status", None)
            if isinstance(st, ProviderStatus) and st.provider == m.provider and st.model == m.model:
                return st.as_dict()
        st = self.last_status
        if isinstance(st, ProviderStatus) and st.provider == m.provider and st.model == m.model:
            return st.as_dict()
        env = PROVIDER_DEFAULTS[m.provider]["key_env"]
        key = os.environ.get(env) or read_keys_file().get(env) or ""
        return ProviderStatus(kind="unknown" if key else "no_key", provider=m.provider, model=m.model,
                              message="" if key else "add an API key").as_dict()

    def test_connection(self) -> dict:
        cfg = self.config()
        ad = ModelAdapter(cfg.model)
        ad.max_retries = 0   # a connection test must answer at once; the classification is the answer
        h = ad.health()
        h.setdefault("ping", None)
        if h.get("ok"):
            # reasoning models spend output tokens before answering: give the ping room
            r = ad.chat([{"role": "user", "content": "Reply with the single word OK."}], role="ping", max_tokens=256, thinking=False)
            h["ping"] = {"ok": r.ok and bool(r.text.strip()), "latency_s": round(r.latency_s, 2), "error": r.error, "reply": r.text.strip()[:40]}
            if not h["ping"]["ok"] and isinstance(ad.last_status, ProviderStatus) and not ad.last_status.ok:
                h.update(ad.last_status.as_dict())
                h["ok"] = False
        self.last_status = ad.last_status if isinstance(ad.last_status, ProviderStatus) else None
        return h

    # -- runs -----------------------------------------------------------------------------------
    def _logger(self, workspace: str):
        logs = self.logs.setdefault(workspace, [])

        def log(msg: str) -> None:
            logs.append({"t": time.time(), "msg": msg})
        return log

    def _spawn(self, workspace: str, runner: Runner, run_id: str, log) -> dict:
        def work() -> None:
            try:
                runner.execute()
            except Exception as e:  # noqa: BLE001
                log(f"[error] {type(e).__name__}: {e}")
                log(traceback.format_exc()[-800:])

        t = threading.Thread(target=work, name=f"run-{workspace}", daemon=True)
        self.runners[workspace] = runner
        self.threads[workspace] = t
        t.start()
        return {"workspace": workspace, "run_id": run_id}

    def alive(self, workspace: str) -> bool:
        t = self.threads.get(workspace)
        return bool(t and t.is_alive())

    def start_run(self, name: str, request: str, budget_s: float, change: Optional[str] = None) -> dict:
        missing = self.missing_tools()
        if missing:
            raise ToolchainMissing(missing)
        WORKSPACES.mkdir(parents=True, exist_ok=True)
        safe = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in name.strip())[:40] or time.strftime("design-%H%M%S")
        ws = Workspace(WORKSPACES / safe)
        if change is None:
            if ws.root.exists() and any(ws.root.iterdir()):
                safe = f"{safe}-{time.strftime('%H%M%S')}"
                ws = Workspace(WORKSPACES / safe)
            ws.init(request=request, name=safe)
        if self.alive(safe):
            raise RunAlive(safe)
        cfg = self.config()
        log = self._logger(safe)
        runner = Runner(ws, cfg, log=log)
        run_id = runner.start(request, budget_s=budget_s) if change is None else runner.revise(change, budget_s=budget_s)
        return self._spawn(safe, runner, run_id, log)

    def resume_run(self, name: str, budget_s: Optional[float] = None) -> dict:
        """Continue the latest run from its checkpoint, or re-verify a completed-but-not-accepted one.

        A completed and accepted run has nothing to resume; a completed but not accepted run is offered
        as a re-verify, which is a fresh run of the same request (its evidence was not good enough).
        """
        ws = Workspace(WORKSPACES / name)
        if not ws.exists():
            raise FileNotFoundError(name)
        if self.alive(name):
            raise RunAlive(name)
        missing = self.missing_tools()
        if missing:
            raise ToolchainMissing(missing)
        if not ws.db_path.is_file():
            raise NothingToResume("this session has no recorded run")
        store = RunStore(ws.db_path)
        try:
            runs = store.list_runs()
            if not runs:
                raise NothingToResume("this session has no recorded run")
            latest = store.get_run(runs[0]["run_id"]) or {}
            state = latest.get("state") or ""
            accepted = (latest.get("outcome") or {}).get("accepted")
        finally:
            store.close()
        cfg = self.config()
        log = self._logger(name)
        runner = Runner(ws, cfg, log=log)
        if state == "completed":
            if accepted:
                raise NothingToResume("the latest run completed and was accepted; request a change instead")
            log("[resume] the latest run completed without acceptance; re-verifying with a new run of the same request")
            run_id = runner.start(ws.request_text().strip(), budget_s=budget_s)
        else:
            run_id = runs[0]["run_id"]
            runner.resume(run_id)
            log(f"[resume] continuing run {run_id} from step '{latest.get('step')}'")
        return self._spawn(name, runner, run_id, log)

    def list_sessions(self) -> list[dict]:
        """Every workspace, newest first, with the state the rail and /resume palette need."""
        out: list[dict] = []
        if not WORKSPACES.exists():
            return out
        for d in sorted(WORKSPACES.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
            ws = Workspace(d)
            if not ws.exists():
                continue
            alive = self.alive(d.name)
            entry: dict[str, Any] = {"workspace": d.name, "name": d.name, "request": ws.request_text().strip()[:200],
                                     "created": d.stat().st_ctime, "updated": d.stat().st_mtime, "state": "created", "step": "-",
                                     "accepted": None, "provisional": False, "withheld_reason": "", "alive": alive,
                                     "resumable": False, "result": "created", "reason": ""}
            if ws.db_path.is_file():
                store = RunStore(ws.db_path)
                try:
                    runs = store.list_runs()
                    if runs:
                        run = store.get_run(runs[0]["run_id"]) or {}
                        outcome = run.get("outcome") or {}
                        wh = withheld_reasons(outcome, run.get("checkpoint") or {})
                        entry.update({"state": run.get("state") or "created", "step": run.get("step") or "-", "run_id": runs[0]["run_id"],
                                      "updated": runs[0].get("updated") or entry["updated"], "accepted": outcome.get("accepted"),
                                      "provisional": bool(outcome.get("provisional")), "withheld_reason": "; ".join(wh)})
                        entry["result"] = session_result(entry["state"], outcome.get("accepted"), alive, bool(wh))
                        entry["resumable"] = entry["state"] != "completed" and not alive
                        entry["reason"] = state_reason(store, runs[0]["run_id"], entry["state"])
                finally:
                    store.close()
            out.append(entry)
        return out

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
        detail["provider"] = self.provider_status(name)
        detail["stages"] = derive_stages({}, [], {}, detail["alive"])
        detail["evidence"] = evidence_summary({}, {})
        detail["model_calls"] = model_calls_summary([], {})
        if ws.db_path.is_file():
            store = RunStore(ws.db_path)
            runs = store.list_runs()
            if runs:
                run = store.get_run(runs[0]["run_id"]) or {}
                outcome = run.get("outcome") or {}
                ck = run.get("checkpoint") or {}
                events = store.events(runs[0]["run_id"])
                detail.update({"run_id": runs[0]["run_id"], "state": run.get("state"), "step": run.get("step"), "outcome": outcome,
                               "events": [{k: v for k, v in e.items() if k != "error" or v} for e in events][-60:],
                               "stages": derive_stages(run, events, outcome, detail["alive"]),
                               "evidence": evidence_summary(outcome, ck),
                               "model_calls": model_calls_summary(events, outcome),
                               "resumable": (run.get("state") != "completed") and not detail["alive"],
                               "result": session_result(run.get("state") or "created", outcome.get("accepted"), detail["alive"],
                                                        bool(withheld_reasons(outcome, ck))),
                               "started": run.get("created"),
                               "reason": state_reason(store, runs[0]["run_id"], run.get("state") or "")})
                if not outcome:
                    # A revision (or any fresh run) has no outcome yet: keep the previous verdict visible
                    # instead of blanking the pill back to "created".
                    for earlier in runs[1:]:
                        prev = store.get_run(earlier["run_id"]) or {}
                        prev_outcome = prev.get("outcome") or {}
                        if prev_outcome:
                            detail["previous_result"] = session_result(
                                prev.get("state") or "created", prev_outcome.get("accepted"), False,
                                bool(withheld_reasons(prev_outcome, prev.get("checkpoint") or {})))
                            break
                # A run parked by the provider records the cause on its checkpoint, not in an outcome.
                if outcome.get("provider_status") or ck.get("provider_status"):
                    detail["provider"] = outcome.get("provider_status") or ck["provider_status"]
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
                return self._send(200, {"settings": self.state.public_settings(), "doctor": self.state.doctor(), "workspaces": str(WORKSPACES),
                                        "runs": self.state.list_runs(), "provider": self.state.provider_status()})
            if u.path == "/api/sessions":
                return self._send(200, self.state.list_sessions())
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
            if u.path.startswith("/api/runs/") and u.path.endswith("/resume"):
                name = u.path.split("/")[3]
                budget = body.get("budget_s")
                return self._send(200, self.state.resume_run(name, float(budget) if budget else None))
            return self._send(404, {"error": "not found"})
        except ToolchainMissing as e:
            tools = ", ".join(e.missing)
            return self._send(400, {"error": f"toolchain missing: install {tools} before running a build", "missing_tools": e.missing})
        except RunAlive as e:
            return self._send(409, {"error": f"a run is already live in session {e}"})
        except NothingToResume as e:
            return self._send(400, {"error": str(e)})
        except FileNotFoundError as e:
            return self._send(404, {"error": str(e)})
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
