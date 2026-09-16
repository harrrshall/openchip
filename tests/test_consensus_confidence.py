"""Reference-vote confidence: a missing confidence on an arbitration outcome is low, never silently high."""
from pathlib import Path
from types import SimpleNamespace

import pytest

from openchip.reporting.report import consensus_confidence, sign_off_withheld
from openchip.runtime import run as run_mod
from openchip.config import Config


def test_no_consensus_block_is_high():
    assert consensus_confidence({}) == "high"


def test_split_acceptance_without_confidence_is_low():
    # Regression: rtl_corroborated_by_alt1 is a 1-1 reference split with no tiebreak;
    # it must never fall through to "high".
    ck = {"consensus": {"outcome": "rtl_corroborated_by_alt1"}}
    assert consensus_confidence(ck) == "low"
    assert consensus_confidence(ck) != "high"


def test_explicit_confidence_returned_unchanged():
    for conf in ("high", "medium", "low"):
        assert consensus_confidence({"consensus": {"outcome": "x", "confidence": conf}}) == conf


def test_none_confidence_is_low():
    assert consensus_confidence({"consensus": {"outcome": "x", "confidence": None}}) == "low"


def _drive_consensus(tmp_path, monkeypatch, generated, comparisons, rtl_accepts):
    """Run Runner._reference_consensus against stubs and return its consensus block.

    `generated` are the (path, error) pairs the reference generator yields in order,
    `comparisons` maps a comparison working-directory name to its result, and
    `rtl_accepts` are the verdicts of verifying the RTL against each alternate.
    """
    gen = iter(generated)
    verdicts = iter(rtl_accepts)
    monkeypatch.setattr(run_mod, "compare_references",
                        lambda contract, a, b, work, seeds, cycles: comparisons[Path(work).name])
    monkeypatch.setattr(run_mod, "verify",
                        lambda *a, **k: SimpleNamespace(accepted=next(verdicts)))
    runner = SimpleNamespace(
        ws=SimpleNamespace(dir=lambda name: tmp_path / name),
        cfg=Config(),
        store=SimpleNamespace(event=lambda *a, **k: None),
        log=lambda *a, **k: None,
        run_id="test-run",
        _generate_reference=lambda ck, contract, path, seed_offset, attempts: next(gen),
        _adopt_reference=lambda ck, old, new: ck.__setitem__("reference_path", str(new)),
    )
    runner.cfg.verification.seeds = [1]
    runner.cfg.verification.sim_cycles = 10
    runner._reference_comparison_config = lambda: run_mod.Runner._reference_comparison_config(runner)
    ck: dict = {}
    run_mod.Runner._reference_consensus(
        runner, ck, None, tmp_path / "rtl.v", tmp_path / "reference.py")
    return ck["consensus"]


AGREE = {"mismatches": 0, "cycles": 10}
DISAGREE = {"mismatches": 3, "cycles": 10}


@pytest.mark.parametrize("outcome,confidence,generated,comparisons,rtl_accepts", [
    # The second reference could not be derived at all, so nothing arbitrated.
    ("alt1_failed", "low", [(None, "boom")], {}, []),
    # The comparison itself failed, so the split was never resolved.
    ("compare_error", "low", [("alt1.py", "")], {"r1_vs_r2": {"error": "boom"}}, []),
    # Both references agree; the RTL is the culprit and gets repaired to match them.
    ("reference_corroborated", "high", [("alt1.py", "")], {"r1_vs_r2": AGREE}, []),
    # 1-1 split, RTL matches the second reference, no tiebreak run: the reported bug.
    ("rtl_corroborated_by_alt1", "low", [("alt1.py", "")], {"r1_vs_r2": DISAGREE}, [True]),
    # 1-1 split and the tiebreaking third reference could not be derived.
    ("alt2_failed", "low", [("alt1.py", ""), (None, "boom")], {"r1_vs_r2": DISAGREE}, [False]),
    # References 2 and 3 agree against the initial one: a 2-of-3 majority.
    ("majority_alt1", "low", [("alt1.py", ""), ("alt2.py", "")],
     {"r1_vs_r2": DISAGREE, "r1_vs_r3": DISAGREE, "r2_vs_r3": AGREE}, [False]),
    # References 1 and 3 agree: the initial reference holds the majority.
    ("majority_initial", "low", [("alt1.py", ""), ("alt2.py", "")],
     {"r1_vs_r2": DISAGREE, "r1_vs_r3": AGREE, "r2_vs_r3": DISAGREE}, [False]),
    # All three references disagree; the contract is probably ambiguous.
    ("no_majority", "low", [("alt1.py", ""), ("alt2.py", "")],
     {"r1_vs_r2": DISAGREE, "r1_vs_r3": DISAGREE, "r2_vs_r3": DISAGREE}, [False]),
])
def test_every_consensus_branch_records_its_confidence(
        tmp_path, monkeypatch, outcome, confidence, generated, comparisons, rtl_accepts):
    """Every exit from _reference_consensus must label itself, so none can default to high."""
    consensus = _drive_consensus(tmp_path, monkeypatch, generated, comparisons, rtl_accepts)
    assert consensus["outcome"].startswith(outcome)
    assert consensus["confidence"] == confidence
    assert consensus_confidence({"consensus": consensus}) == confidence
    assert bool(sign_off_withheld({"consensus": consensus})) is (confidence != "high")


def test_no_consensus_block_is_not_withheld():
    # No arbitration happened: an ordinary acceptance is signed off normally.
    assert sign_off_withheld({}) == ""


@pytest.mark.parametrize("outcome", ["no_majority", "majority_initial", "majority_alt1"])
def test_non_unanimous_outcomes_withhold_sign_off(outcome):
    reason = sign_off_withheld({"consensus": {"outcome": outcome, "confidence": "low"}})
    assert reason
    assert outcome in reason


def test_missing_outcome_withholds_sign_off():
    # An arbitration block that recorded no outcome must not be signed off either.
    assert sign_off_withheld({"consensus": {"outcome": ""}})


@pytest.mark.parametrize("outcome", [
    "rtl_corroborated_by_two_references",
    "rtl_corroborated_2_of_3",
    "reference_corroborated",
    "rtl_corroborated_by_alt1",
    "alt1_failed",
    "split_1_1_alt2_failed",
])
def test_outcome_without_confidence_withholds_sign_off(outcome):
    # An outcome label alone cannot establish unanimous corroboration.
    assert sign_off_withheld({"consensus": {"outcome": outcome}})


@pytest.mark.parametrize("outcome,confidence", [
    ("rtl_corroborated_by_two_references", "high"),
    ("reference_corroborated", "high"),
    ("rtl_corroborated_2_of_3", "medium"),
    ("rtl_corroborated_by_alt1", "low"),
    ("alt1_failed", "low"),
    ("split_1_1_alt2_failed", "low"),
])
def test_only_high_confidence_agreement_allows_sign_off(outcome, confidence):
    reason = sign_off_withheld({"consensus": {"outcome": outcome, "confidence": confidence}})
    assert bool(reason) is (confidence != "high")
