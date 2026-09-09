"""Orchestrator tests with a scripted model: checkpointing, repair loop, budget, stall, resume."""
import json
from pathlib import Path

import pytest

from openchip.config import Config
from openchip.models.adapter import ModelResponse, Usage
from openchip.runtime.run import Runner
from openchip.runtime.workspace import Workspace

FIX = Path(__file__).parent / "fixtures"
pytestmark = pytest.mark.cloud


class ScriptedAdapter:
    """Returns canned replies per role; records every call."""

    def __init__(self, replies: dict[str, list[str]]):
        self.replies = {k: list(v) for k, v in replies.items()}
        self.usage = Usage()
        self.calls: list[str] = []

    def chat(self, messages, role="generic", **kw):
        self.calls.append(role)
        q = self.replies.get(role) or ["(no reply)"]
        text = q.pop(0) if len(q) > 1 else q[0]
        r = ModelResponse(text=text, reasoning="", finish_reason="stop", prompt_tokens=10, completion_tokens=10, latency_s=0.01, model="scripted")
        self.usage.add(role, r)
        return r


def contract_reply():
    return json.dumps(json.loads((FIX / "counter_contract.json").read_text()))


def code(lang, path):
    return f"```{lang}\n{(FIX / path).read_text()}\n```"


def test_happy_path_and_resume_state(tmp_path):
    ws = Workspace(tmp_path / "ws")
    ws.init(request="8-bit up/down counter")
    adapter = ScriptedAdapter({"intake": [contract_reply()], "reference": [code("python", "counter_reference.py")], "rtl": [code("verilog", "counter_good.v")]})
    cfg = Config.load()
    cfg.verification.run_formal = False
    cfg.verification.sim_cycles = 100
    r = Runner(ws, cfg, adapter=adapter, log=lambda m: None)
    rid = r.start("8-bit up/down counter")
    out = r.execute()
    assert out["accepted"] and out["state"] == "completed" and out["attempts"] == 1
    assert adapter.calls == ["intake", "reference", "rtl", "reference"]  # second reference corroborates acceptance
    assert out["reference_consensus"]["outcome"] == "rtl_corroborated_by_two_references"
    assert (ws.root / "reports" / "report.md").is_file() and (ws.root / "rtl" / "updown_counter.v").is_file()
    run = r.store.get_run(rid)
    assert run["state"] == "completed" and run["step"] == "done"
    assert any(e["kind"] == "verification" for e in r.store.events(rid))


def test_repair_loop_fixes_bug(tmp_path):
    ws = Workspace(tmp_path / "ws")
    ws.init(request="counter")
    adapter = ScriptedAdapter({"intake": [contract_reply()], "reference": [code("python", "counter_reference.py")],
                               "rtl": [code("verilog", "counter_bug_priority.v")],
                               "repair": ["VERDICT: rtl\n" + code("verilog", "counter_good.v")]})
    cfg = Config.load()
    cfg.verification.run_formal = False
    cfg.verification.sim_cycles = 100
    r = Runner(ws, cfg, adapter=adapter, log=lambda m: None)
    r.start("counter")
    out = r.execute()
    assert out["accepted"] and out["attempts"] == 2
    assert (ws.root / "verification" / "attempts" / "attempt_0" / "evidence.json").is_file()  # failed attempt preserved
    assert (ws.root / "verification" / "attempts" / "attempt_0" / "updown_counter.v").read_text() == (FIX / "counter_bug_priority.v").read_text()


def test_stall_detection_on_identical_rtl(tmp_path):
    ws = Workspace(tmp_path / "ws")
    ws.init(request="counter")
    adapter = ScriptedAdapter({"intake": [contract_reply()], "reference": [code("python", "counter_reference.py")],
                               "rtl": [code("verilog", "counter_bug_priority.v")], "repair": [code("verilog", "counter_bug_priority.v")]})
    cfg = Config.load()
    cfg.verification.run_formal = False
    cfg.verification.sim_cycles = 50
    r = Runner(ws, cfg, adapter=adapter, log=lambda m: None)
    r.start("counter")
    out = r.execute()
    assert not out["accepted"] and out["state"] == "stalled"
    assert "identical" in out["reason"]


def test_budget_exhausted_reports(tmp_path):
    ws = Workspace(tmp_path / "ws")
    ws.init(request="counter")
    adapter = ScriptedAdapter({"intake": [contract_reply()], "reference": [code("python", "counter_reference.py")],
                               "rtl": [code("verilog", "counter_bug_priority.v")],
                               "repair": [code("verilog", "counter_bug_x.v"), code("verilog", "counter_bug_priority.v"), code("verilog", "counter_bug_x.v"), code("verilog", "counter_bug_priority.v")]})
    cfg = Config.load()
    cfg.verification.run_formal = False
    cfg.verification.sim_cycles = 50
    cfg.budget.max_repair_iterations = 1
    r = Runner(ws, cfg, adapter=adapter, log=lambda m: None)
    r.start("counter")
    out = r.execute()
    assert not out["accepted"] and out["state"] == "budget_exhausted"
    assert "NOT verified" in json.dumps(out["requirements"])


def test_invalid_contract_is_retried_then_fails(tmp_path):
    ws = Workspace(tmp_path / "ws")
    ws.init(request="counter")
    adapter = ScriptedAdapter({"intake": ["not json at all"]})
    cfg = Config.load()
    cfg.verification.run_formal = False
    r = Runner(ws, cfg, adapter=adapter, log=lambda m: None)
    r.start("counter")
    with pytest.raises(RuntimeError):
        r.execute()
    assert adapter.calls.count("intake") == 3
    assert r.store.get_run(r.run_id)["state"] == "failed"


def test_resume_from_checkpoint(tmp_path):
    ws = Workspace(tmp_path / "ws")
    ws.init(request="counter")
    adapter = ScriptedAdapter({"intake": [contract_reply()], "reference": [code("python", "counter_reference.py")], "rtl": ["garbage"]})
    cfg = Config.load()
    cfg.verification.run_formal = False
    cfg.verification.sim_cycles = 50
    r = Runner(ws, cfg, adapter=adapter, log=lambda m: None)
    rid = r.start("counter")
    with pytest.raises(RuntimeError):
        r.execute()  # rtl step fails -> run failed, checkpoint at 'rtl'
    assert r.store.get_run(rid)["step"] == "rtl"
    adapter2 = ScriptedAdapter({"rtl": [code("verilog", "counter_good.v")]})
    r2 = Runner(ws, cfg, adapter=adapter2, log=lambda m: None)
    r2.resume(rid)
    out = r2.execute()
    assert out["accepted"] and adapter2.calls[0] == "rtl" and "intake" not in adapter2.calls  # intake not redone


def test_consensus_adopts_second_reference_when_rtl_is_right(tmp_path):
    """Wrong first reference + correct RTL: a second independent reference arbitrates and the run is accepted."""
    ws = Workspace(tmp_path / "ws")
    ws.init(request="counter")
    adapter = ScriptedAdapter({"intake": [contract_reply()],
                               "reference": [code("python", "counter_reference_wrong.py"), code("python", "counter_reference.py")],
                               "rtl": [code("verilog", "counter_good.v")]})
    cfg = Config.load()
    cfg.verification.run_formal = False
    cfg.verification.sim_cycles = 100
    r = Runner(ws, cfg, adapter=adapter, log=lambda m: None)
    r.start("counter")
    out = r.execute()
    assert out["accepted"], out["status_line"]
    # The wrong reference computes `count` from same-cycle inputs: the timing lint rejects it before it can
    # mislead the loop, the retry yields the correct one, and acceptance is corroborated by a second derivation.
    events = r.store.events(r.run_id, "reference_rejected")
    assert events and events[0].get("timing_violations"), events
    assert out["reference_consensus"]["outcome"] == "rtl_corroborated_by_two_references"
    assert "repair" not in adapter.calls  # no RTL repair was needed


def test_consensus_corroborates_reference_then_repairs(tmp_path):
    """Correct references + buggy RTL: second reference agrees with the first, RTL gets repaired."""
    ws = Workspace(tmp_path / "ws")
    ws.init(request="counter")
    adapter = ScriptedAdapter({"intake": [contract_reply()],
                               "reference": [code("python", "counter_reference.py")],
                               "rtl": [code("verilog", "counter_bug_priority.v")],
                               "repair": ["VERDICT: rtl\n" + code("verilog", "counter_good.v")]})
    cfg = Config.load()
    cfg.verification.run_formal = False
    cfg.verification.sim_cycles = 100
    r = Runner(ws, cfg, adapter=adapter, log=lambda m: None)
    r.start("counter")
    out = r.execute()
    assert out["accepted"] and out["reference_consensus"]["outcome"] == "reference_corroborated"
    assert adapter.calls.count("reference") == 2 and adapter.calls.count("repair") == 1


def test_revision_creates_v2_and_reverifies(tmp_path):
    """A change request produces contract v2 with provenance and a fresh run; v1 artifacts are untouched."""
    ws = Workspace(tmp_path / "ws")
    ws.init(request="counter")
    adapter = ScriptedAdapter({"intake": [contract_reply()], "reference": [code("python", "counter_reference.py")], "rtl": [code("verilog", "counter_good.v")]})
    cfg = Config.load()
    cfg.verification.run_formal = False
    cfg.verification.sim_cycles = 50
    r = Runner(ws, cfg, adapter=adapter, log=lambda m: None)
    r.start("counter")
    assert r.execute()["accepted"]
    v1 = (ws.root / "spec" / "contract.v1.json").read_text()
    # revision: the model returns the same contract body (validator forces version/parent/authority)
    c2 = json.loads(contract_reply())
    c2["requirements"].append({"id": "R004", "text": "count saturates instead of wrapping (change)", "source": "user_text"})
    adapter2 = ScriptedAdapter({"revise": [json.dumps(c2)], "reference": [code("python", "counter_reference.py")], "rtl": [code("verilog", "counter_good.v")]})
    r2 = Runner(ws, cfg, adapter=adapter2, log=lambda m: None)
    rid2 = r2.revise("make the counter saturate instead of wrap")
    out = r2.execute()
    c = json.loads((ws.root / "spec" / "contract.v2.json").read_text())
    assert c["version"] == 2 and c["parent_version"] == 1 and c["revision_authority"] == "user"
    assert (ws.root / "spec" / "contract.v1.json").read_text() == v1
    assert out["contract_version"] == 2 and adapter2.calls[0] == "revise" and "intake" not in adapter2.calls
    assert any(e["kind"] == "contract_revised" and "R004" in e["changed_or_new"] for e in r2.store.events(rid2))
