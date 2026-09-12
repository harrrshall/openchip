"""A reference that contradicts a printed table is rejected at generation, not only at sign-off."""
from pathlib import Path

from openchip.config import Config, ModelConfig
from openchip.contracts.schema import Contract
from openchip.models.adapter import ModelResponse, Usage
from openchip.runtime.run import Budget, Runner
from openchip.runtime.workspace import Workspace

INTERFACE = """I would like you to implement a module named TopModule with the following
interface. All input and output ports are one bit unless otherwise
specified.

 - input  x3
 - input  x2
 - input  x1
 - output f

The module should implement a combinational circuit for the following
truth table:

  x3 | x2 | x1 | f
  0  | 0  | 0  | 0
  0  | 0  | 1  | 0
  0  | 1  | 0  | 1
  0  | 1  | 1  | 1
  1  | 0  | 0  | 0
  1  | 0  | 1  | 1
  1  | 1  | 0  | 0
  1  | 1  | 1  | 1
"""

WRONG = """```python
class Reference:
    def __init__(self, params):
        pass
    def reset(self):
        pass
    def step(self, inputs):
        return {"f": 0}
```"""

RIGHT = """```python
class Reference:
    def __init__(self, params):
        pass
    def reset(self):
        pass
    def step(self, inputs):
        x3, x2, x1 = inputs["x3"], inputs["x2"], inputs["x1"]
        return {"f": int((x3 == 0 and x2 == 1) or (x3 == 1 and x1 == 1))}
```"""


class _QueuedAdapter:
    def __init__(self, replies: list[str]):
        self.replies = list(replies)
        self.usage = Usage()
        self.cfg = ModelConfig(model="scripted", thinking=False, thinking_roles=[])

    def chat(self, messages, role="generic", **kw):
        text = self.replies.pop(0)
        r = ModelResponse(text=text, reasoning="", finish_reason="stop",
                          prompt_tokens=4, completion_tokens=4, latency_s=0.01, model="scripted")
        self.usage.add(role, r)
        return r


def _contract() -> Contract:
    return Contract.model_validate({
        "module_name": "TopModule", "purpose": "truth table",
        "behavior": "x" * 160,
        "ports": [
            {"name": "x3", "direction": "input", "width": 1, "timing": "n/a"},
            {"name": "x2", "direction": "input", "width": 1, "timing": "n/a"},
            {"name": "x1", "direction": "input", "width": 1, "timing": "n/a"},
            {"name": "f", "direction": "output", "width": 1, "timing": "combinational"},
        ],
        "clock_reset": None,
        "requirements": [{"id": "R001", "text": "Output f follows the printed truth table.", "source": "user_text"}],
    })


def test_mismatching_reference_is_rejected_then_a_matching_one_is_kept(tmp_path, monkeypatch):
    from openchip.runtime import run as run_mod
    monkeypatch.setattr(run_mod, "run_reference", lambda *a, **k: {"error": ""})
    monkeypatch.setattr(run_mod, "lint_reference_timing", lambda *a, **k: {"violations": []})

    ws = Workspace(tmp_path / "ws")
    ws.init(request=INTERFACE)
    runner = Runner(ws, Config.load(), adapter=_QueuedAdapter([WRONG, RIGHT]), log=lambda m: None)
    runner.start(INTERFACE)
    runner.budget = Budget(600, 20, 100_000, 3)
    path, err = runner._generate_reference({"request": INTERFACE}, _contract(), ws.dir("reference") / "reference.py")
    assert err == ""
    assert path is not None
    assert "x3" in path.read_text()
    rejected = list(ws.dir("reference").glob("*.rejected0.py"))
    assert rejected and 'return {"f": 0}' in rejected[0].read_text()


def _seq_contract() -> Contract:
    return Contract.model_validate({
        "module_name": "TopModule", "purpose": "seq counter",
        "behavior": "x" * 160,
        "ports": [
            {"name": "clk", "direction": "input", "width": 1, "role": "clock", "timing": "n/a"},
            {"name": "a", "direction": "input", "width": 1, "timing": "n/a"},
            {"name": "q", "direction": "output", "width": 3, "timing": "registered"},
        ],
        "clock_reset": {"clock": "clk", "reset": ""},
        "requirements": [{"id": "R001", "text": "Count when a is low, hold when a is high.", "source": "user_text"}],
    })


def test_three_combinational_table_mismatches_still_abort(tmp_path, monkeypatch):
    from openchip.runtime import run as run_mod
    monkeypatch.setattr(run_mod, "run_reference", lambda *a, **k: {"error": ""})
    monkeypatch.setattr(run_mod, "lint_reference_timing", lambda *a, **k: {"violations": []})
    ws = Workspace(tmp_path / "ws")
    ws.init(request=INTERFACE)
    runner = Runner(ws, Config.load(), adapter=_QueuedAdapter([WRONG, WRONG, WRONG]), log=lambda m: None)
    runner.start(INTERFACE)
    runner.budget = Budget(600, 20, 100_000, 3)
    path, err = runner._generate_reference({"request": INTERFACE}, _contract(), ws.dir("reference") / "reference.py")
    assert path is None
    assert "TABLE ERROR" in err


def test_clocked_waveform_mismatch_keeps_last_smoke_ok_reference(tmp_path, monkeypatch):
    from openchip.runtime import run as run_mod
    monkeypatch.setattr(run_mod, "run_reference", lambda *a, **k: {"error": ""})
    monkeypatch.setattr(run_mod, "lint_reference_timing", lambda *a, **k: {"violations": []})
    monkeypatch.setattr(run_mod, "check_reference_against_request_tables", lambda *a, **k: {
        "status": "mismatch", "mismatches": [{"kind": "clocked_waveform", "detail": "q"}], "detail": "q",
    })
    ws = Workspace(tmp_path / "ws")
    req = "clocked dump"
    ws.init(request=req)
    runner = Runner(ws, Config.load(), adapter=_QueuedAdapter([WRONG, WRONG, WRONG]), log=lambda m: None)
    runner.start(req)
    runner.budget = Budget(600, 20, 100_000, 3)
    path, err = runner._generate_reference({"request": req}, _seq_contract(), ws.dir("reference") / "reference.py")
    assert err == ""
    assert path is not None
    assert path.is_file()
