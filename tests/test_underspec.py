"""Request underspecification is a question for the user, not a default the model may invent."""
from openchip.contracts.underspec import underspec_questions
from openchip.reporting.report import sign_off_withheld

PROB093 = """
 - output mux_in (4 bits)
Consider a block diagram with inputs 'c' and 'd' going into a module
called "TopModule". This "TopModule" has four outputs, mux_in[3:0], that
connect to a four input mux. The mux takes as input {a,b} and ab = 00 is
connected to mux_in[0], ab=01 is connected to mux_in[1], and so in.
"""

PROB133 = """
Once in state B the FSM examines the value of the input w in the next three clock cycles.
If w = 1 in exactly two of these clock cycles, then the FSM has to set an output z to 1
in the following clock cycle. The FSM continues checking w for the next three clock
cycles, and so on.
"""

PROB137 = """
If the stop bit does not appear when expected, the FSM must wait
until it finds a stop bit before attempting to receive the next byte.
"""

PROB141 = """
Create a set of counters suitable for use as a 12-hour clock (with am/pm
indicator). The signal "pm" is asserted if the clock is PM, or is otherwise AM.
Reset is the active high synchronous signal that resets the clock to "12:00 AM."
"""

PROB141_NAMED = PROB141 + "\npm toggles at 11:59:59 → 12:00:00.\n"

PROB149 = """
If the sensor change indicates that the previous level was lower
than the current level, the flow rate should be increased by opening the
Supplemental flow valve (controlled by dfr).
"""

PROB153 = """
This index accesses a 128-entry table of two-bit saturating counters.
Reset is asynchronous active-high.
"""

PROB153_STATED = PROB153 + "\nThe saturating counters reset to 1 (weakly not taken).\n"

PROB113 = """
The module should implement the function f shown in the Karnaugh map below.
             x[0]x[1]
x[2]x[3]  00  01  11  10
  00     | 1 | 0 | 0 | 1 |
"""

HELD_OUT = """
Build a sequence detector for 1011 on `data`, output `match` registered, sync active-high reset.
"""


def test_incomplete_index_continuation_fires():
    qs = underspec_questions(PROB093)
    assert len(qs) == 1
    assert "mux_in" in qs[0]


def test_well_specified_and_so_on_is_silent():
    assert underspec_questions(PROB133) == []


def test_stop_bit_recovery_fires():
    qs = underspec_questions(PROB137)
    assert len(qs) == 1
    assert "done" in qs[0]


def test_twelve_hour_pm_without_named_instant_fires():
    qs = underspec_questions(PROB141)
    assert len(qs) == 1
    assert "pm" in qs[0]


def test_named_pm_instant_is_silent():
    assert underspec_questions(PROB141_NAMED) == []


def test_clear_dfr_polarity_is_not_underspec():
    assert underspec_questions(PROB149) == []


def test_saturating_counters_without_reset_value_fire():
    qs = underspec_questions(PROB153)
    assert len(qs) == 1
    assert "reset value" in qs[0]


def test_stated_counter_reset_is_silent():
    assert underspec_questions(PROB153_STATED) == []


def test_kmap_and_ordinary_request_are_silent():
    assert underspec_questions(PROB113) == []
    assert underspec_questions(HELD_OUT) == []
    assert underspec_questions("") == []


def test_sign_off_withheld_uses_the_request():
    reason = sign_off_withheld({"request": PROB093})
    assert reason
    assert "does not determine" in reason
    assert sign_off_withheld({"request": PROB149}) == ""
    assert sign_off_withheld({}) == ""
