Build a fixed-width Verilog-2001 module named event_counter with inputs clk, rst,
clear, enable, event_i (each one unsigned bit) and output count (8-bit unsigned,
registered). All state updates on the rising edge of clk. rst is synchronous,
active high and has highest priority.

Track the previous sampled value of event_i in a one-bit history register. Reset
sets that history to zero. At every other rising edge, update history to event_i,
even when enable is low or clear is high. At an edge, a rising event means the
current event_i is one and the history BEFORE that edge is zero.

Reset or clear sets count to zero. Otherwise, if enable is one and a rising event
occurs, increment count unless it is already 255; at 255 it stays 255. Otherwise
count holds. Clear has priority over enabled events and does not reset event
history. Thus an event that occurs while disabled is consumed and must not be
counted later just because enable becomes one. Holding event_i high counts once.

Use exactly two meaningful leaf modules: an edge detector containing the history
register and a combinational rise output (event_i AND NOT history), and a saturating
counter taking that rise signal as an input. Both share clk and rst directly.
The edge detector's rise output must be combinational so the counter sees the
current edge's event; a registered pulse would add an incorrect cycle of latency.
No parameters, asynchronous reset, output pulse port, or extra latency.
