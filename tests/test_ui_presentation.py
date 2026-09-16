from openchip.ui.presentation import contract_diff, result_summary, stage_durations
import io
import json
import zipfile
import pytest
import threading
from types import SimpleNamespace
from openchip.ui import server
from openchip.config import Config


def test_provisional_and_withheld_never_sign_off():
    for outcome in [
        {"accepted": True, "provisional": True},
        {"accepted": False, "status_line": "SIGN-OFF WITHHELD: non-unanimous vote",
         "reference_consensus": {"confidence": "low"}},
        {"accepted": True, "unresolved": ["Reset priority?", "Reset priority?"]},
    ]:
        result = result_summary(outcome, "completed")
        assert result["sentence"] == "Needs your answer on 1 question"
        assert len(result["questions"]) == 1
    assert result_summary({"accepted": True}, "completed")["sentence"] == "Verified and signed off"
    withheld = result_summary({"accepted": False, "status_line": "SIGN-OFF WITHHELD"}, "completed")
    assert withheld["sentence"] == "Needs more work before sign-off"
    assert withheld["questions"] == []


def test_formal_information_requires_recorded_optional_policy():
    for required in [True, False, None]:
        result = result_summary({"formal": {"status": "error"},
                                 "verification_config": {"require_formal": required}}, "completed")
        assert result["formal"]["informational"] is (required is False)


def test_stage_repair_visits_accumulate_and_duplicate_checkpoints_do_not_double_count():
    events = [{"kind": "checkpoint", "step": s, "ts": t}
              for s, t in [("rtl", 10), ("rtl", 12), ("verify", 15), ("rtl", 19)]]
    assert stage_durations(events, 23) == [{"stage": "rtl", "seconds": 9},
                                          {"stage": "verify", "seconds": 4}]
    assert stage_durations([], 23) == []


def test_contract_diff_shows_removed_and_added_behavior(tmp_path):
    before, after = tmp_path / "contract.v1.md", tmp_path / "contract.v2.md"
    before.write_text("Synchronous reset\n")
    after.write_text("Asynchronous reset\n")
    diff = contract_diff([before, after])
    assert "-Synchronous reset" in diff and "+Asynchronous reset" in diff
    assert "No previous" in contract_diff([before])


def test_bundle_includes_evidence_and_excludes_secrets_and_symlink_escapes(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "WORKSPACES", tmp_path / "workspaces")
    monkeypatch.setattr(server, "UI_SETTINGS", tmp_path / "settings.json")
    state = server.UIState(Config())
    root = server.WORKSPACES / "counter"
    for path, content in {"rtl/counter.v": "module counter; endmodule", "reports/report.md": "Report",
                          "verification/attempt1/evidence.json": '{}', ".openchip/secrets.env": "secret"}.items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    (root / "rtl" / "escape.v").symlink_to(root / ".openchip" / "secrets.env")
    with zipfile.ZipFile(io.BytesIO(state.bundle("counter"))) as archive:
        assert set(archive.namelist()) == {"rtl/counter.v", "reports/report.md", "verification/attempt1/evidence.json",
                                          "CURRENT_WORKSPACE_STATUS.json"}
        assert archive.read("rtl/counter.v") == b"module counter; endmodule"
        assert json.loads(archive.read("CURRENT_WORKSPACE_STATUS.json")) == {}
    for path in ["../counter/rtl/counter.v", ".openchip/secrets.env", "rtl/escape.v"]:
        with pytest.raises(FileNotFoundError):
            state.artifact("counter", path)
    with pytest.raises(FileNotFoundError):
        state.workspace_path("..")


def test_revision_is_backgrounded_and_duplicate_submission_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "WORKSPACES", tmp_path)
    monkeypatch.setattr(server, "UI_SETTINGS", tmp_path / "settings.json")
    entered, release = threading.Event(), threading.Event()
    ws = server.Workspace(tmp_path / "counter")
    ws.init()
    # Runner is stubbed below; the UI only checks that a prior contract exists.
    (ws.dir("spec") / "contract.v1.json").write_text("{}")
    class SlowRevision:
        def __init__(self, *args, **kwargs):
            self.store = SimpleNamespace(close=lambda: None)
        def revise(self, change, budget_s):
            assert change == "Reset takes priority"
            assert budget_s == 60
            return "revision-run"
        def execute(self):
            entered.set()
            release.wait(5)
    monkeypatch.setattr(server, "Runner", SlowRevision)
    state = server.UIState(Config())
    try:
        assert state.start_run("counter", "", 60, change="Reset takes priority") == {
            "workspace": "counter", "run_id": "revision-run"}
        assert entered.wait(1)
        with pytest.raises(ValueError, match="current run"):
            state.start_run("counter", "", 60, change="Reset takes priority")
    finally:
        release.set()
        if thread := state.threads.get("counter"):
            thread.join(2)
