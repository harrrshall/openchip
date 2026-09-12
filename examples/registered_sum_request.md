Create a two-module system named registered_sum. Use exactly these top ports:
clk, rst, en are one-bit inputs; a and b are unsigned 8-bit inputs; q is an
unsigned 8-bit registered output. Use a positive-edge clock and synchronous
active-high reset. At each rising edge, reset has priority and sets q to zero.
Otherwise, if en is one, q captures min(a+b, 255), treating the addition as a
9-bit unsigned operation before saturation. If en is zero, q retains its value.
There is no other state and no extra pipeline delay: the enabled edge captures
the result for the operands present immediately before that edge.

Decompose it into exactly two useful leaf modules: a purely combinational
unsigned 8-bit saturating adder, and an enabled 8-bit output register with the
reset/hold semantics above. Wire the adder's output into the register's data
input. No parameters, no backpressure, and no valid signal are needed. The
system-level requirements must cover overflow saturation, enabled capture,
disabled hold, and reset priority independently.
