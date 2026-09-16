# Saturating event counter

An 8-bit counter with active-low asynchronous reset, synchronous clear,
and enable. Clear has priority over enable; the count holds at 255 instead of
wrapping. Use it to count events up to a saturation threshold.

The generated RTL passed 395/395 independent observations covering saturation,
hold, clear priority and reset between clock edges. The first build was withheld
because its generated checker used incorrect clock-sampling semantics. A later
opt-in checker review recovered acceptance without changing RTL and passed
bounded formal at depth 20. The recovered checker rejected variants that increment
by two or ignore clear. These are bounded measurements, not timing closure or
unbounded proof. Formal startup reset alone does not prove arbitrary asynchronous
reset behavior; the separate bench checks selected between-edge reset cases.

Run the included bench with Icarus Verilog:

```sh
iverilog -g2012 -s tb -o /tmp/event_counter.vvp event_counter.v tb.v
vvp /tmp/event_counter.vvp
```

Expected summary: `RESET_RESULT mismatches=0 samples=395`.
`request.md` defines the interface and behavior. `verification.json` records
artifact hashes and measured provenance. Reset is required before using the count.
