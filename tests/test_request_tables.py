"""The printed grid is ground truth; these tests pin that it is read exactly as printed.

Every expected value below was derived by reading the table in the test's own input string.
"""
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
