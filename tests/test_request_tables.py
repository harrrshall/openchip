"""The printed grid is ground truth; these tests pin that it is read exactly as printed.

Every expected value below was derived by reading the table in the test's own input string.
"""
import re

from openchip.contracts.tables import parse_request_tables, render_table

INTERFACE = """I would like you to implement a module named TopModule with the following
interface. All input and output ports are one bit unless otherwise
specified.

"""

# Column axis is x[0]x[1], so the column code "01" means x[0]=0, x[1]=1 — not the other way round.
KMAP_LSB_FIRST = INTERFACE + """ - input  x (4 bits)
 - output f

The module should implement the function f shown in the Karnaugh map
below.

             x[0]x[1]
x[2]x[3]  00  01  11  10
  00     | 1 | 0 | 0 | 1 |
  01     | 0 | 0 | 0 | 0 |
  11     | 1 | 1 | 1 | 0 |
  10     | 1 | 1 | 0 | 1 |
"""

# Column codes are printed 01 00 10 11, which is not Gray order.
KMAP_UNUSUAL_COLUMN_ORDER = INTERFACE + """ - input  a
 - input  b
 - input  c
 - input  d
 - output out

The module should implement the Karnaugh map below. d is don't-care,
which means you may choose to output whatever value is convenient.

              ab
   cd   01  00  10  11
   00 | d | 0 | 1 | 1 |
   01 | 0 | 0 | d | d |
   11 | 0 | 1 | 1 | 1 |
   10 | 0 | 1 | 1 | 1 |
"""

TRUTH_TABLE = INTERFACE + """ - input  x3
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

WAVEFORM = INTERFACE + """ - input  a
 - input  b
 - output q

The module should implement a combinational circuit. Read the simulation
waveforms to determine what the circuit does, then implement it.

  time  a  b  q
  0ns   0  0  0
  5ns   0  0  0
  10ns  0  1  1
  15ns  1  0  1
  20ns  1  1  0
"""


def _as_dict(table):
    return {values: out for values, out in table.rows}


def test_kmap_column_code_binds_to_the_printed_axis_order():
    (t,) = parse_request_tables(KMAP_LSB_FIRST)
    assert t.kind == "kmap"
    assert [v.name for v in t.inputs] == ["x[2]", "x[3]", "x[0]", "x[1]"]
    assert [(v.port, v.bit) for v in t.inputs] == [("x", 2), ("x", 3), ("x", 0), ("x", 1)]
    assert t.output.name == "f"
    rows = _as_dict(t)
    assert len(rows) == 16 and t.dont_care == 0
    # Row "00", column "01": x[2]=0 x[3]=0 x[0]=0 x[1]=1, and the printed cell there is 0.
    # A parser applying MSB-first would bind that cell to x[0]=1 x[1]=0 and report 1 here.
    assert rows[(0, 0, 0, 1)] == 0
    assert rows[(0, 0, 1, 0)] == 1
    # Row "11", column "10": the printed cell is 0; MSB-first would report 1.
    assert rows[(1, 1, 1, 0)] == 0
    assert rows[(1, 1, 0, 1)] == 1


def test_kmap_uses_the_printed_column_order_and_drops_dont_care_cells():
    (t,) = parse_request_tables(KMAP_UNUSUAL_COLUMN_ORDER)
    assert [v.name for v in t.inputs] == ["c", "d", "a", "b"]
    assert t.output.name == "out"
    rows = _as_dict(t)
    assert t.dont_care == 3
    assert len(rows) == 13
    # Row "00" is | d | 0 | 1 | 1 | against columns 01 00 10 11:
    assert (0, 0, 0, 1) not in rows        # the don't-care cell
    assert rows[(0, 0, 0, 0)] == 0
    assert rows[(0, 0, 1, 0)] == 1
    assert rows[(0, 0, 1, 1)] == 1
    # Row "01" is | 0 | 0 | d | d |:
    assert rows[(0, 1, 0, 1)] == 0
    assert (0, 1, 1, 0) not in rows
    assert (0, 1, 1, 1) not in rows


def test_truth_table():
    (t,) = parse_request_tables(TRUTH_TABLE)
    assert t.kind == "truth_table"
    assert [v.name for v in t.inputs] == ["x3", "x2", "x1"]
    assert t.output.name == "f"
    rows = _as_dict(t)
    assert len(rows) == 8
    assert rows[(0, 1, 0)] == 1
    assert rows[(1, 0, 0)] == 0
    assert rows[(1, 0, 1)] == 1


def test_waveform_collapses_duplicate_agreeing_rows():
    (t,) = parse_request_tables(WAVEFORM)
    assert t.kind == "waveform"
    assert [v.name for v in t.inputs] == ["a", "b"]
    assert t.output.name == "q"
    assert _as_dict(t) == {(0, 0): 0, (0, 1): 1, (1, 0): 1, (1, 1): 0}


def test_waveform_with_a_clock_declines():
    assert parse_request_tables(WAVEFORM.replace("  a  b  q", "  clk  b  q")) == []


def test_waveform_with_an_undefined_cell_declines():
    assert parse_request_tables(WAVEFORM.replace("  0ns   0  0  0", "  0ns   0  0  x")) == []


def test_waveform_with_a_contradictory_row_declines():
    # 5ns repeats a=0 b=0 but now says q=1, which means the circuit has state.
    assert parse_request_tables(WAVEFORM.replace("  5ns   0  0  0", "  5ns   0  0  1")) == []


def test_kmap_with_a_short_row_declines():
    assert parse_request_tables(KMAP_LSB_FIRST.replace("  01     | 0 | 0 | 0 | 0 |",
                                                       "  01     | 0 | 0 | 0 |")) == []


def test_incomplete_kmap_declines():
    assert parse_request_tables(KMAP_LSB_FIRST.replace("  10     | 1 | 1 | 0 | 1 |\n", "")) == []


def test_kmap_without_a_single_declared_output_declines():
    assert parse_request_tables(KMAP_LSB_FIRST.replace(" - output f", " - output f\n - output g")) == []


def test_request_without_a_table():
    request = INTERFACE + " - input  clk\n - output q\n\nBuild an 8-bit counter that increments every cycle.\n"
    assert parse_request_tables(request) == []


def test_render_table_lists_every_row_and_names_every_variable():
    (t,) = parse_request_tables(KMAP_UNUSUAL_COLUMN_ORDER)
    text = render_table(t)
    assert sum(1 for line in text.splitlines() if "->" in line) == len(t.rows)
    for name in ("c", "d", "a", "b", "out"):
        assert f"{name}=" in text
    assert "3 cell(s)" in text
    assert "x[0]=0 x[1]=0" not in text  # variables from a different request must not leak in


def test_kmap_naming_the_same_bit_twice_declines():
    # Two columns headed by the same bit assign it conflicting values, so no row is determined.
    assert parse_request_tables(KMAP_LSB_FIRST.replace("             x[0]x[1]",
                                                       "             x[0]x[0]")) == []


def test_rendered_bit_vector_is_listed_msb_first_and_carries_its_packed_value():
    # The measured failure this pins (ADR 0010): the grid's axis order x[2]x[3]x[0]x[1] was
    # transcribed correctly and then read as a bit ordering, packing x[2]=0 x[3]=0 x[0]=1 x[1]=0
    # as 0b0010 = 2 instead of 0b0001 = 1.
    (t,) = parse_request_tables(KMAP_LSB_FIRST)
    text = render_table(t)
    assert "Inputs: x[3] x[2] x[1] x[0]." in text
    row = next(line for line in text.splitlines() if "[x[3:0] = 1]" in line)
    assert "x[3]=0 x[2]=0 x[1]=0 x[0]=1" in row
    assert row.endswith("f=1")
    # every row must carry its packed value, not just the one inspected above
    assert sum(1 for line in text.splitlines() if "[x[3:0] = " in line) == len(t.rows)


def test_rendering_states_the_bit_convention_and_disowns_the_listing_order():
    (t,) = parse_request_tables(KMAP_LSB_FIRST)
    text = render_table(t)
    assert "bit k of the value of `s`, contributing 2**k" in text
    assert "not a significance order" in text
    # The claim that got skimmed past before was about the *listing* order of the whole row; the
    # bits within a port really are ordered here, so the text must not deny that.
    assert "in this order" not in text


def test_rendered_function_is_stated_as_decimal_values_before_the_rows():
    """The decimal set needs no bit-packing decision, and a wrong packing decision was the failure."""
    (t,) = parse_request_tables(KMAP_LSB_FIRST)
    lines = render_table(t).splitlines()
    ones = next(i for i, line in enumerate(lines) if line.strip().startswith("f = 1 for"))
    zeros = next(i for i, line in enumerate(lines) if line.strip().startswith("f = 0 for"))
    first_row = next(i for i, line in enumerate(lines) if "->" in line)
    assert ones < first_row and zeros < first_row
    assert lines[ones].strip() == "f = 1 for exactly these values of x[3:0]: 0, 1, 4, 5, 6, 12, 14, 15"
    assert lines[zeros].strip() == "f = 0 for exactly these values of x[3:0]: 2, 3, 7, 8, 9, 10, 11, 13"


def test_rendered_packing_equals_the_packing_the_sign_off_gate_checks():
    """A rendering that packed differently from the gate would teach a function the gate rejects."""
    from openchip.contracts.schema import Contract
    from openchip.verification.tablecheck import bind

    contract = Contract.model_validate({
        "module_name": "TopModule", "purpose": "Combinational function of a 4-bit vector.",
        "ports": [{"name": "x", "direction": "input", "width": 4, "timing": "combinational"},
                  {"name": "f", "direction": "output", "width": 1, "timing": "combinational"}],
        "clock_reset": None,
        "behavior": ("The module is purely combinational. The output f is a single bit driven directly by "
                     "the 4-bit input vector x with no clocked storage of any kind, so f settles to its new "
                     "value whenever any bit of x changes. The function of x is given by the Karnaugh map "
                     "printed in the request and by nothing else."),
        "requirements": [{"id": "R001", "text": "f follows the printed Karnaugh map.", "source": "user_text"}],
    })
    (t,) = parse_request_tables(KMAP_LSB_FIRST)
    bound = bind(t, contract)
    assert bound is not None
    text = render_table(t)
    rendered = [int(m) for m in re.findall(r"\[x\[3:0\] = (\d+)\]", text)]
    assert rendered == [vec["x"] for vec, _ in bound.rows]
    assert sorted(rendered) == list(range(16))
    # and the decimal summary must agree with the same source of truth
    ones = sorted(vec["x"] for vec, expected in bound.rows if expected == 1)
    assert f"f = 1 for exactly these values of x[3:0]: {', '.join(str(n) for n in ones)}" in text


def test_single_bit_ports_are_rendered_without_a_packed_value():
    (t,) = parse_request_tables(KMAP_UNUSUAL_COLUMN_ORDER)
    text = render_table(t)
    assert "[" not in text          # no packed-value brackets, and no bit subscripts to explain
    assert "2**k" not in text
    assert "for exactly these values" not in text   # no single vector carries this table


def test_a_partially_pinned_vector_is_labelled_by_the_bits_it_pins():
    """The renderer has no contract, so it must not present two bits as a whole 4-bit port."""
    request = INTERFACE + """ - input  x (4 bits)
 - output f

The module should implement the function f shown in the Karnaugh map
below.

          x[0]
x[1]   0   1
  0  | 1 | 0 |
  1  | 0 | 1 |
"""
    (t,) = parse_request_tables(request)
    text = render_table(t)
    assert "[x[1:0] = " in text
    assert "[x = " not in text
    assert "values of x[1:0]:" in text


def test_a_dont_care_table_does_not_claim_to_be_exhaustive():
    # One cell of the bit-vector map printed as a don't-care: the value set is then not "exactly",
    # and the omitted value must not be quietly filed under either output.
    (t,) = parse_request_tables(KMAP_LSB_FIRST.replace("  01     | 0 | 0 | 0 | 0 |",
                                                       "  01     | d | 0 | 0 | 0 |"))
    text = render_table(t)
    assert t.dont_care == 1
    assert "for these values of x[3:0]" in text
    assert "exactly these values" not in text
    # Row "01" (x[2]=0 x[3]=1), column "00" (x[0]=0 x[1]=0) is the don't-care cell, i.e. x = 8.
    sets = {int(v) for line in text.splitlines()
            for m in re.findall(r"for these values of x\[3:0\]: (.*)$", line)
            for v in m.split(",")}
    assert 8 not in sets
    assert sets == set(range(16)) - {8}
