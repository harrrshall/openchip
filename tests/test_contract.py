import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from openchip.contracts.coerce import coerce_contract
from openchip.contracts.schema import Contract, eval_width

FIX = Path(__file__).parent / "fixtures"


def load():
    return json.loads((FIX / "counter_contract.json").read_text())


def test_valid_contract_roundtrip():
    c = Contract.model_validate(load())
    assert c.module_name == "updown_counter"
    assert [p.name for p in c.data_inputs()] == ["en", "up", "load", "load_val"]
    assert [p.name for p in c.outputs()] == ["count"]
    assert "| `count` | output | 8 |" in c.summary_md()
    assert c.digest() == Contract.model_validate_json(c.model_dump_json()).digest()


def test_rejects_duplicate_port():
    d = load()
    d["ports"].append({"name": "count", "direction": "input", "width": 1})
    with pytest.raises(ValidationError):
        Contract.model_validate(d)


def test_rejects_missing_clock():
    d = load()
    d["ports"] = [p for p in d["ports"] if p["name"] != "clk"]
    with pytest.raises(ValidationError):
        Contract.model_validate(d)


def test_rejects_width_expr_mismatch():
    d = load()
    d["parameters"] = [{"name": "WIDTH", "default": 8}]
    d["ports"][-1]["width_expr"] = "WIDTH+1"
    with pytest.raises(ValidationError):
        Contract.model_validate(d)
    d["ports"][-1]["width_expr"] = "WIDTH"
    assert Contract.model_validate(d).ports[-1].width == 8


def test_rejects_revision_without_parent():
    d = load()
    d["version"] = 2
    with pytest.raises(ValidationError):
        Contract.model_validate(d)


def test_rejects_bad_identifier_and_empty_requirements():
    d = load()
    d["module_name"] = "bad name"
    with pytest.raises(ValidationError):
        Contract.model_validate(d)
    d = load()
    d["requirements"] = []
    with pytest.raises(ValidationError):
        Contract.model_validate(d)


def test_eval_width_restricted():
    assert eval_width("clog2(DEPTH)+1", {"DEPTH": 16}) == 5
    with pytest.raises(ValueError):
        eval_width("__import__('os')", {})
    with pytest.raises(ValueError):
        eval_width("FOO", {})


def test_clocked_without_reset_is_valid():
    d = load()
    d["ports"] = [p for p in d["ports"] if p["name"] != "rst"]
    d["clock_reset"] = {"clock": "clk", "reset": ""}
    c = Contract.model_validate(d)
    assert c.clock_reset is not None and c.clock_reset.reset == ""
    assert "No reset port" in c.summary_md()


def test_coerce_strips_bogus_reset_name():
    d = load()
    d["ports"] = [p for p in d["ports"] if p["name"] != "rst"]
    d["clock_reset"] = {"clock": "clk", "reset": "null"}
    out, notes = coerce_contract(d, "")
    assert out["clock_reset"]["reset"] == ""
    assert any("reset" in n.lower() for n in notes)
    Contract.model_validate(out)


def test_testbench_omits_undeclared_reset():
    from openchip.verification.testbench import generate_testbench
    d = load()
    d["ports"] = [p for p in d["ports"] if p["name"] != "rst"]
    d["clock_reset"] = {"clock": "clk", "reset": ""}
    tb = generate_testbench(Contract.model_validate(d), 8)
    assert "reg rst" not in tb and ".rst(" not in tb
    assert ".clk(clk)" in tb
