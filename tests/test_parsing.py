from openchip.models.adapter import extract_code, extract_json, split_think
from openchip.tools.iverilog import parse_diagnostics as iv_diags
from openchip.tools.verilator import parse_diagnostics as vl_diags


def test_extract_code_prefers_last_matching_lang():
    txt = "```python\nx=1\n```\ntext\n```verilog\nmodule a; endmodule\n```\n```verilog\nmodule b; endmodule\n```"
    assert extract_code(txt, ("verilog",)).strip() == "module b; endmodule"
    assert extract_code(txt, ("python",)).strip() == "x=1"
    assert extract_code("no code", ("verilog",)) is None


def test_extract_json_variants():
    assert extract_json('{"a": 1}') == {"a": 1}
    assert extract_json('here:\n```json\n{"a": 2}\n```') == {"a": 2}
    assert extract_json('prefix {"a": 3} suffix') == {"a": 3}
    assert extract_json("nothing") is None


def test_extract_json_survives_reasoning_and_a_truncated_tail():
    """A reasoning model's reply: thinking first, the object, then a second attempt cut off by the cap."""
    txt = ('We need a module. Consider {this} and {that}.\n'
           '{"module_name": "dff", "ports": [{"name": "clk"}]}\n'
           'Wait, let me redo it:\n{"module_name": "dff", "ports": [{"name":')
    assert extract_json(txt) == {"module_name": "dff", "ports": [{"name": "clk"}]}
    assert extract_json('reasoning...\n{"a": {"b": 1}}\nthat is my answer.') == {"a": {"b": 1}}


def test_split_think():
    body, think = split_think("<think>reasoning</think>\nanswer")
    assert body == "answer" and think == "reasoning"


def test_diagnostic_parsers():
    iv = iv_diags("counter.v:4: syntax error\ncounter.v:3: error: Malformed statement\n")
    assert iv and iv[0]["line"] == 4
    vl = vl_diags("%Error-WIDTH: rtl/counter.v:7:12: Operator ASSIGN expects 8 bits\n%Warning-UNUSED: x.v:1:1: unused\n")
    assert vl[0]["kind"] == "error" and vl[0]["code"] == "WIDTH" and vl[1]["kind"] == "warning"
