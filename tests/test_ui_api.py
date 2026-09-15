"""UI API contract end to end: a real ThreadingHTTPServer, http.client, and a scripted model.

Covers docs/product/ui-redesign-2026-09-15.md section 3: /api/status provider, /api/sessions,
/api/runs/<ws> stages and evidence, and /api/runs/<ws>/resume for an interrupted run.
"""
import http.client
import json
import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from openchip.config import Config
from openchip.runtime.run import Runner
from openchip.runtime.store import RunStore
from openchip.runtime.workspace import Workspace
from openchip.ui import server as S
from test_runner_mock import ScriptedAdapter, code, contract_reply

pytestmark = pytest.mark.cloud


def _replies():
    return {"intake": [contract_reply()], "reference": [code("python", "counter_reference.py")],
            "rtl": [code("verilog", "counter_good.v")]}


class _State(S.UIState):
    """The real UIState with the model replaced by the scripted adapter and formal turned off."""

    def config(self):
        cfg = super().config()
        cfg.verification.run_formal = False
        cfg.verification.sim_cycles = 100
        return cfg


class Client:
    def __init__(self, port: int):
        self.port = port

    def request(self, method: str, path: str, body=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=60)
        payload = json.dumps(body).encode() if body is not None else None
        c.request(method, path, body=payload, headers={"Content-Type": "application/json"} if payload else {})
        r = c.getresponse()
        data = r.read()
        c.close()
        return r.status, (json.loads(data) if data and r.getheader("Content-Type", "").startswith("application/json") else data)

    def get(self, path):
        return self.request("GET", path)

    def post(self, path, body=None):
        return self.request("POST", path, body or {})


@pytest.fixture()
def api(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "WORKSPACES", tmp_path / "workspaces")
    monkeypatch.setattr(S, "UI_SETTINGS", tmp_path / "ui.json")
    monkeypatch.setattr("openchip.models.adapter.KEYS_FILE", tmp_path / "keys.env")
    monkeypatch.setenv("OPENCODE_GO_API_KEY", "go-test-key")
    real_runner = S.Runner

    def scripted(ws, cfg, log=print, **kw):
        return real_runner(ws, cfg, adapter=ScriptedAdapter(_replies()), log=log)

    monkeypatch.setattr(S, "Runner", scripted)
    S.Handler.state = _State(Config.load())
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), S.Handler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        yield Client(httpd.server_port)
    finally:
        httpd.shutdown()
        httpd.server_close()


def _poll(api, ws, want=("completed", "failed", "stalled", "budget_exhausted"), timeout=180):
    deadline = time.time() + timeout
    detail = {}
    while time.time() < deadline:
        code_, detail = api.get(f"/api/runs/{ws}")
        assert code_ == 200, detail
        if detail.get("state") in want and not detail["alive"]:
            return detail
        time.sleep(0.5)
    raise AssertionError(f"run did not finish: state={detail.get('state')} alive={detail.get('alive')}")


def test_status_carries_provider_and_settings_accept_opencode_go(api):
    code_, st = api.get("/api/status")
    assert code_ == 200
    assert set(st) >= {"settings", "doctor", "workspaces", "runs", "provider"}
    assert set(st["provider"]) == {"kind", "message", "retry_after_s", "until", "provider", "model", "checked_at"}
    code_, s2 = api.post("/api/settings", {"provider": "opencode-go", "model": "kimi-k3"})
    assert code_ == 200 and s2["provider"] == "opencode-go" and s2["base_url"] == "https://opencode.ai/zen/go/v1"
    assert s2["key_env"] == "OPENCODE_GO_API_KEY" and s2["key_present"] is True
    assert "kimi-k3" in s2["presets"] and len(s2["session_id"]) == 36
    # the session id is stable across a reload and is what the adapter would send
    assert json.loads((S.UI_SETTINGS).read_text())["session_id"] == s2["session_id"]
    assert S.Handler.state.config().model.extra_headers["x-opencode-session"] == s2["session_id"]
    code_, st2 = api.get("/api/status")
    assert st2["provider"]["provider"] == "opencode-go" and st2["provider"]["model"] == "kimi-k3"
    assert st2["provider"]["kind"] == "unknown"  # a key is present, but nothing has called the provider yet


def test_run_to_acceptance_then_sessions_and_resume_rules(api):
    code_, r = api.post("/api/runs", {"name": "counter-ui", "request": "an 8-bit up/down counter with synchronous reset"})
    assert code_ == 200, r
    ws = r["workspace"]
    detail = _poll(api, ws)
    assert detail["state"] == "completed" and detail["outcome"]["accepted"] is True, detail["outcome"].get("status_line")

    stages = detail["stages"]
    assert [s["name"] for s in stages] == ["Intake", "Review", "Reference", "RTL", "Verify", "Sign-off"]
    assert all(s["status"] == "done" for s in stages), stages
    assert all(s["detail"] for s in stages), stages
    assert stages[0]["detail"].startswith("contract v")
    assert "reference(s)" in stages[2]["detail"] and stages[4]["detail"].startswith("attempt 1 of 1")
    assert stages[5]["detail"] == "signed off"

    ev = detail["evidence"]
    assert set(ev) >= {"attempts", "signoff", "unresolved", "assumptions", "escalations"}
    assert ev["signoff"]["accepted"] is True and ev["signoff"]["withheld_reasons"] == []
    assert len(ev["attempts"]) == 1 and ev["attempts"][0]["accepted"] is True
    assert detail["model_calls"]["count"] >= 4 and detail["model_calls"]["tokens"] > 0
    assert set(detail["provider"]) >= {"kind", "provider", "model"}
    assert detail["result"] == "accepted" and detail["resumable"] is False
    assert detail["contract_md"] and detail["report_md"] and detail["rtl"]
    assert detail["contract"]["module_name"] == "updown_counter" and detail["contract"]["ports"]
    assert detail["module"] == "updown_counter" and detail["intent"]

    code_, sessions = api.get("/api/sessions")
    assert code_ == 200 and len(sessions) == 1
    s0 = sessions[0]
    assert set(s0) >= {"workspace", "name", "request", "created", "updated", "state", "step", "accepted",
                       "provisional", "withheld_reason", "alive", "resumable", "result"}
    assert s0["workspace"] == ws and s0["result"] == "accepted" and s0["accepted"] is True
    assert s0["state"] == "completed" and s0["step"] == "done" and s0["alive"] is False and s0["resumable"] is False
    assert s0["module"] == "updown_counter" and s0["intent"] == detail["intent"]
    assert s0["needs_input"] is False

    # a completed and accepted run has nothing to resume
    code_, err = api.post(f"/api/runs/{ws}/resume")
    assert code_ == 400 and "accepted" in err["error"]
    code_, err = api.post("/api/runs/no-such-session/resume")
    assert code_ == 404


def test_resume_continues_an_interrupted_run(api, tmp_path):
    """Simulate an interruption: a run checkpointed at `rtl`, no live thread, then resume it."""
    ws_dir = S.WORKSPACES / "interrupted"
    ws_dir.parent.mkdir(parents=True, exist_ok=True)
    ws = Workspace(ws_dir)
    ws.init(request="an 8-bit up/down counter with synchronous reset", name="interrupted")
    cfg = S.Handler.state.config()
    runner = Runner(ws, cfg, adapter=ScriptedAdapter(_replies()), log=lambda m: None)
    # Drive the run up to the RTL step, then stop: exactly the state a killed process leaves behind.
    rid = runner.start(ws.request_text().strip())
    runner.budget = None
    store = RunStore(ws.db_path)
    from openchip.runtime.run import Budget
    runner.budget = Budget(600, 40, 400000, 4)
    ck = runner._step_intake({"request": ws.request_text().strip()})
    ck = runner._step_review(ck)
    ck = runner._step_reference(ck)
    ck = runner._step_properties(ck)
    store.checkpoint(rid, "rtl", ck)
    store.set_state(rid, "running", resumed_from="rtl")
    store.release_lock(rid)
    store.close()

    code_, sessions = api.get("/api/sessions")
    s0 = next(s for s in sessions if s["workspace"] == "interrupted")
    assert s0["state"] == "running" and s0["alive"] is False
    assert s0["result"] == "interrupted" and s0["resumable"] is True
    code_, detail = api.get("/api/runs/interrupted")
    assert [s["status"] for s in detail["stages"]][:3] == ["done", "done", "done"]
    # RTL is where it broke off: the strip keeps the progress it had and marks that step failed.
    assert detail["stages"][3]["status"] == "failed"
    assert [s["status"] for s in detail["stages"]][4:] == ["pending", "pending"]
    assert isinstance(detail["started"], (int, float)) and detail["started"] > 0

    code_, res = api.post("/api/runs/interrupted/resume")
    assert code_ == 200 and res["run_id"] == rid, res
    detail = _poll(api, "interrupted")
    assert detail["state"] == "completed" and detail["outcome"]["accepted"] is True, detail["outcome"].get("status_line")
    assert all(s["status"] == "done" for s in detail["stages"])
    assert any("[resume] continuing run" in line["msg"] for line in detail["logs"])
    code_, sessions = api.get("/api/sessions")
    assert next(s for s in sessions if s["workspace"] == "interrupted")["result"] == "accepted"


def test_run_refused_when_the_toolchain_is_missing(api, monkeypatch):
    monkeypatch.setattr(_State, "missing_tools", lambda self: ["yosys"])
    code_, err = api.post("/api/runs", {"name": "x", "request": "an 8-bit up/down counter with reset"})
    assert code_ == 400 and err["missing_tools"] == ["yosys"] and "yosys" in err["error"]


def test_a_second_run_in_a_live_session_is_refused(api, monkeypatch):
    class _Live:
        def is_alive(self):
            return True
    S.Handler.state.threads["busy"] = _Live()
    (S.WORKSPACES / "busy").mkdir(parents=True, exist_ok=True)
    Workspace(S.WORKSPACES / "busy").init(request="an 8-bit up/down counter with reset", name="busy")
    code_, err = api.post("/api/runs/busy/resume")
    assert code_ == 409 and "live" in err["error"]


def test_test_connection_reports_provider_status_and_ping(api):
    api.post("/api/settings", {"provider": "opencode-go", "model": "kimi-k3"})
    code_, h = api.post("/api/test")
    assert code_ == 200
    assert set(h) >= {"kind", "message", "retry_after_s", "until", "provider", "model", "checked_at", "ok", "ping"}
    assert h["provider"] == "opencode-go" and h["model"] == "kimi-k3"
    assert h["ok"] is False and h["kind"] in ("unreachable", "invalid_key", "server_error", "unknown")  # no real gateway here
    code_, st = api.get("/api/status")
    assert st["provider"]["kind"] == h["kind"]  # the last classification is what the rail pill shows


def test_completed_but_not_accepted_run_is_resumed_as_a_reverify(api):
    """A completed run without acceptance is re-verified: a new run of the same request, same session."""
    ws_dir = S.WORKSPACES / "reverify"
    ws_dir.parent.mkdir(parents=True, exist_ok=True)
    ws = Workspace(ws_dir)
    ws.init(request="an 8-bit up/down counter with synchronous reset", name="reverify")
    store = RunStore(ws.db_path)
    rid = store.create_run(str(ws.root), ws.request_text().strip(), Config.load().model_dump(mode="json"))
    store.checkpoint(rid, "done", {"request": ws.request_text().strip()})
    store.set_outcome(rid, {"run_id": rid, "state": "completed", "accepted": False, "status_line": "[completed] simulation FAILED"})
    store.set_state(rid, "completed", accepted=False)
    store.close()

    code_, sessions = api.get("/api/sessions")
    s0 = next(s for s in sessions if s["workspace"] == "reverify")
    assert s0["result"] == "not_accepted" and s0["resumable"] is False  # completed: offered as a re-verify, not a resume

    code_, res = api.post("/api/runs/reverify/resume")
    assert code_ == 200 and res["run_id"] != rid, res
    detail = _poll(api, "reverify")
    assert detail["state"] == "completed" and detail["outcome"]["accepted"] is True
    assert any("re-verifying" in line["msg"] for line in detail["logs"])


def _interrupt_at_rtl(name: str, state: str, reason: str = "") -> str:
    """The state a killed or provider-blocked process leaves behind: a checkpoint at `rtl`, no thread."""
    ws_dir = S.WORKSPACES / name
    ws_dir.parent.mkdir(parents=True, exist_ok=True)
    ws = Workspace(ws_dir)
    ws.init(request="an 8-bit up/down counter with synchronous reset", name=name)
    cfg = S.Handler.state.config()
    runner = Runner(ws, cfg, adapter=ScriptedAdapter(_replies()), log=lambda m: None)
    rid = runner.start(ws.request_text().strip())
    from openchip.runtime.run import Budget
    runner.budget = Budget(600, 40, 400000, 4)
    ck = runner._step_intake({"request": ws.request_text().strip()})
    ck = runner._step_review(ck)
    ck = runner._step_reference(ck)
    ck = runner._step_properties(ck)
    store = RunStore(ws.db_path)
    store.checkpoint(rid, "rtl", ck)
    store.set_state(rid, state, **({"reason": reason} if reason else {}))
    store.release_lock(rid)
    store.close()
    return rid


@pytest.mark.parametrize("state", ["paused", "failed", "stalled", "budget_exhausted"])
def test_an_interrupted_run_keeps_its_stage_progress(api, state):
    """Defect: the stage strip reset to all-pending after an interruption, losing the work done."""
    name = "stopped-" + state
    _interrupt_at_rtl(name, state, reason="provider quota: GoUsageLimitError https://opencode.ai/auth")

    code_, detail = api.get(f"/api/runs/{name}")
    assert code_ == 200, detail
    assert [s["status"] for s in detail["stages"]] == ["done", "done", "done", "failed", "pending", "pending"]
    assert detail["stages"][2]["detail"], detail["stages"]          # the detail lines survive too
    # the provider cause travels with the session so the rail pill can show it in its title
    assert "GoUsageLimitError" in detail["reason"]
    code_, sessions = api.get("/api/sessions")
    s0 = next(s for s in sessions if s["workspace"] == name)
    assert "GoUsageLimitError" in s0["reason"]
    assert s0["result"] == ("interrupted" if state == "paused" else
                            ("failed" if state == "failed" else "not_accepted"))


def test_a_fresh_run_in_a_session_reports_the_previous_result(api):
    """Defect: a revision blanked the pill to `created`; the previous verdict must stay visible."""
    ws_dir = S.WORKSPACES / "revised"
    ws_dir.parent.mkdir(parents=True, exist_ok=True)
    ws = Workspace(ws_dir)
    ws.init(request="an 8-bit up/down counter with synchronous reset", name="revised")
    store = RunStore(ws.db_path)
    old = store.create_run(str(ws.root), ws.request_text().strip(), Config.load().model_dump(mode="json"))
    store.checkpoint(old, "done", {"request": ws.request_text().strip()})
    store.set_outcome(old, {"run_id": old, "state": "completed", "accepted": True})
    store.set_state(old, "completed", accepted=True)
    time.sleep(1.1)                      # run ids are second-resolution; the new run must sort first
    new = store.create_run(str(ws.root), ws.request_text().strip(), Config.load().model_dump(mode="json"))
    store.set_state(new, "planned")
    store.close()

    code_, detail = api.get("/api/runs/revised")
    assert code_ == 200 and detail["run_id"] == new
    assert not detail["outcome"] and detail["previous_result"] == "accepted"


VERILOGEVAL_PROMPT = """I would like you to implement a module named TopModule with the following
interface. All input and output ports are one bit unless otherwise
specified.

 - input  clk
 - input  areset
 - input  in
 - output out

The module should implement a Moore machine with the diagram described
below:

  B (1) --0--> A
  A (0) --1--> A
"""


def test_sessions_and_detail_carry_module_intent_and_contract(api):
    """Rows name the module and its intent, never the folder or the prompt boilerplate."""
    root = S.WORKSPACES
    root.mkdir(parents=True, exist_ok=True)
    Workspace(root / "fsm-plain").init(request=VERILOGEVAL_PROMPT, name="fsm-plain")
    Workspace(root / "named-system").init(
        request="Create a two-module system named registered_sum. Use exactly these top ports: clk, rst.", name="named-system")
    Workspace(root / "no-name").init(request="counter that wraps. More text follows here.", name="no-name")
    with_contract = Workspace(root / "with-contract")
    with_contract.init(request=VERILOGEVAL_PROMPT, name="with-contract")
    spec = with_contract.dir("spec")
    (spec / "contract.v1.json").write_text(json.dumps({"module_name": "old_name", "purpose": "Old purpose.", "ports": []}))
    (spec / "contract.v2.json").write_text(json.dumps({
        "module_name": "fsm1", "ports": [{"name": "clk", "direction": "input", "width": 1}],
        "purpose": "Moore machine that outputs 1 in state B. It resets asynchronously to B and holds otherwise for as long as needed."}))

    code_, sessions = api.get("/api/sessions")
    assert code_ == 200
    rows = {s["workspace"]: s for s in sessions}
    assert rows["fsm-plain"]["module"] == "TopModule"
    intent = rows["fsm-plain"]["intent"]
    assert intent == "Moore machine with the diagram described below", intent
    assert "would like" not in intent and "one bit" not in intent
    assert rows["named-system"]["module"] == "registered_sum" and rows["named-system"]["intent"] == "two-module system"
    assert rows["no-name"]["module"] == "no-name" and rows["no-name"]["intent"] == "counter that wraps"
    # the latest contract wins: module_name, and the first sentence of its purpose
    assert rows["with-contract"]["module"] == "fsm1"
    assert rows["with-contract"]["intent"] == "Moore machine that outputs 1 in state B"
    assert all(len(s["intent"]) <= 90 for s in sessions)

    code_, detail = api.get("/api/runs/with-contract")
    assert code_ == 200 and detail["contract"]["module_name"] == "fsm1" and detail["contract"]["ports"][0]["name"] == "clk"
    assert detail["module"] == "fsm1"
    code_, detail = api.get("/api/runs/fsm-plain")
    assert code_ == 200 and detail["contract"] is None and detail["module"] == "TopModule"
