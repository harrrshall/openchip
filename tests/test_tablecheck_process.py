"""A request-table verdict must come from the current reference subprocess."""
import pytest

from openchip.contracts.schema import Contract
from openchip.verification.tablecheck import check_reference_against_request_tables


@pytest.mark.parametrize("exit_code", [0, 7])
def test_abrupt_reference_exit_cannot_reuse_previous_pass(tmp_path, exit_code):
    contract = identity_contract()
    request = " - input a\n - output f\n\n  a | f\n  0 | 0\n  1 | 1\n"
    reference = tmp_path / "reference.py"
    reference.write_text(IDENTITY_REFERENCE)
    work = tmp_path / "check"
    first = check_reference_against_request_tables(contract, request, reference, work)
    assert first["status"] == "ok" and first["rows"] == 2
    reference.write_text(f"import os\nos._exit({exit_code})\n")
    second = check_reference_against_request_tables(contract, request, reference, work)
    assert second["status"] == "error", second
    assert second["rows"] == 0


IDENTITY_REFERENCE = (
    "class Reference:\n"
    "    def __init__(self, params): pass\n"
    "    def reset(self): pass\n"
    "    def step(self, inputs): return {'f': inputs['a']}\n"
)


def identity_contract():
    return Contract.model_validate({
        "module_name": "identity", "purpose": "Combinational identity function.",
        "ports": [
            {"name": "a", "direction": "input", "width": 1, "timing": "combinational"},
            {"name": "f", "direction": "output", "width": 1, "timing": "combinational"},
        ],
        "clock_reset": None,
        "behavior": ("The output f continuously equals the input a. There is no clock or storage. "
                     "When a is zero, f is zero; when a is one, f is one. Changes propagate "
                     "combinationally without waiting for a clock edge."),
        "requirements": [{"id": "R001", "text": "Output f equals input a.", "source": "user_text"}],
    })


@pytest.mark.cloud
@pytest.mark.parametrize("exit_code", [0, 7])
def test_reverify_rejects_dead_reference_and_recovers(tmp_path, exit_code):
    from openchip.config import Config
    from openchip.verification.harness import verify

    contract = identity_contract()
    reference = tmp_path / "reference.py"
    reference.write_text(IDENTITY_REFERENCE)
    rtl = tmp_path / "identity.v"
    rtl.write_text("module identity(input a, output f); assign f = a; endmodule\n")
    work = tmp_path / "reverify"
    cfg = Config()
    first = verify(contract, rtl, reference, work, cfg, cycles=20, seeds=[1])
    assert first.accepted and first.synth["ok"]
    prior = (work / "vectors_1.json").read_bytes()
    reference.write_text(f"import os\nos._exit({exit_code})\n")
    second = verify(contract, rtl, reference, work, cfg, cycles=20, seeds=[1])
    assert not second.accepted and second.stage == "reference", second.to_dict()
    assert second.reference_error
    assert any(p.read_bytes() == prior for p in work.rglob("vectors_1.json"))
    reference.write_text(IDENTITY_REFERENCE)
    third = verify(contract, rtl, reference, work, cfg, cycles=20, seeds=[1])
    assert third.accepted


@pytest.mark.parametrize("exit_code", [0, 7])
def test_timing_lint_does_not_reuse_previous_result(tmp_path, exit_code):
    from openchip.verification.harness import lint_reference_timing

    contract = tmp_path / "contract.json"
    data = identity_contract().model_dump(mode="json")
    data["clock_reset"] = {"clock": "clk", "reset": "rst"}
    data["ports"][1]["timing"] = "registered"
    data["ports"].extend([
        {"name": name, "direction": "input", "width": 1, "timing": "n/a"}
        for name in ("clk", "rst")
    ])
    contract.write_text(Contract.model_validate(data).model_dump_json())
    reference = tmp_path / "reference.py"
    reference.write_text(IDENTITY_REFERENCE.replace("inputs['a']", "0"))
    output = tmp_path / "timing.json"
    first = lint_reference_timing(reference, contract, output)
    assert not first["error"] and first["checked_steps"] == 40
    reference.write_text(f"import os\nos._exit({exit_code})\n")
    second = lint_reference_timing(reference, contract, output)
    assert second["error"], second
