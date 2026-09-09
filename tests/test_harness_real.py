"""Real-tool integration tests: the harness must accept a correct design and reject faulty ones."""
import json
import shutil
from pathlib import Path

import pytest

from openchip.config import Config
from openchip.contracts.schema import Contract
from openchip.verification.harness import verify
from openchip.verification.testbench import generate_testbench

FIX = Path(__file__).parent / "fixtures"
pytestmark = pytest.mark.cloud


def _contract():
    return Contract.model_validate_json((FIX / "counter_contract.json").read_text())


def _run(tmp_path, rtl_name, **kw):
    rtl = tmp_path / "updown_counter.v"
    shutil.copy(FIX / rtl_name, rtl)
    return verify(_contract(), rtl, FIX / "counter_reference.py", tmp_path / "work", Config.load(), cycles=200, seeds=[1, 2], **kw)


def test_generate_testbench_mentions_ports():
    tb = generate_testbench(_contract(), 10)
    assert "updown_counter dut" in tb and "RESULT PASS" in tb and "MISMATCH" in tb


def test_good_counter_accepted(tmp_path):
    res = _run(tmp_path, "counter_good.v")
    assert res.accepted, json.dumps(res.to_dict(), indent=1)[:2000]
    assert res.stage == "done" and all(s["status"] == "pass" for s in res.sims)
    assert res.synth and res.synth["num_cells"] > 0


def test_priority_bug_detected(tmp_path):
    res = _run(tmp_path, "counter_bug_priority.v")
    assert not res.accepted and res.stage == "simulate"
    assert any(s["status"] == "fail" and s["mismatches"] > 0 for s in res.sims)
    assert "expected" in res.evidence_for_model()


def test_x_after_reset_detected(tmp_path):
    res = _run(tmp_path, "counter_bug_x.v")
    assert not res.accepted
    assert res.stage in ("simulate", "lint")


def test_syntax_error_stops_at_compile_or_lint(tmp_path):
    res = _run(tmp_path, "counter_syntax.v")
    assert not res.accepted and res.stage in ("lint", "compile")
    assert res.evidence_for_model()


def test_broken_reference_is_not_blamed_on_rtl(tmp_path):
    rtl = tmp_path / "updown_counter.v"
    shutil.copy(FIX / "counter_good.v", rtl)
    bad_ref = tmp_path / "ref.py"
    bad_ref.write_text("class Reference:\n    def __init__(self, p): pass\n    def reset(self): pass\n    def step(self, i): return {'nope': 1}\n")
    res = verify(_contract(), rtl, bad_ref, tmp_path / "w", Config.load(), cycles=10, seeds=[1])
    assert res.stage == "reference" and res.reference_error and not res.accepted


def test_formal_layer_bounded_pass_and_counterexample(tmp_path):
    """SBY BMC on the independent checker: passes on the correct counter, finds the priority bug."""
    from openchip.verification.formal import run_formal

    c = _contract()
    for name, expect in (("counter_good.v", "bounded_pass"), ("counter_bug_priority.v", "counterexample")):
        rtl = tmp_path / name
        shutil.copy(FIX / name, rtl)
        r = run_formal(c, rtl, FIX / "counter_props.v", tmp_path / f"formal_{name}", depth=12)
        assert r.extra["status"] == expect, r.tail(30)
    # integrated: formal evidence is attached without blocking acceptance
    rtl = tmp_path / "updown_counter.v"
    shutil.copy(FIX / "counter_good.v", rtl)
    res = verify(c, rtl, FIX / "counter_reference.py", tmp_path / "w2", Config.load(), cycles=100, seeds=[1], props_path=FIX / "counter_props.v")
    assert res.accepted and res.formal and res.formal["status"] == "bounded_pass"


def test_combinational_next_state_style_is_not_x_after_reset(tmp_path):
    """Regression: `always @*` designs must not fail with X outputs because of testbench initialisation."""
    res = _run(tmp_path, "counter_comb.v")
    assert res.accepted, json.dumps(res.to_dict(), indent=1)[:1500]


def test_combinational_contract_verifies(tmp_path):
    """Contracts without clock/reset use the combinational testbench; a wrong encoder is detected."""
    c = Contract.model_validate_json((FIX / "prio_enc_contract.json").read_text())
    assert c.combinational
    rtl = tmp_path / "prio_enc.v"
    shutil.copy(FIX / "prio_enc_good.v", rtl)
    res = verify(c, rtl, FIX / "prio_enc_reference.py", tmp_path / "w", Config.load(), cycles=200, seeds=[1])
    assert res.accepted, json.dumps(res.to_dict(), indent=1)[:1500]
    bad = tmp_path / "bad" / "prio_enc.v"
    bad.parent.mkdir()
    bad.write_text((FIX / "prio_enc_good.v").read_text().replace("i = 0; i < 8; i = i + 1", "i = 7; i >= 0; i = i - 1"))  # lowest-priority bug
    res2 = verify(c, bad, FIX / "prio_enc_reference.py", tmp_path / "w2", Config.load(), cycles=200, seeds=[1])
    assert not res2.accepted and res2.stage == "simulate"
