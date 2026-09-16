# Counter with nonzero packed indices

`RangeCounter` adds the unsigned four-bit `step` when enabled, wraps modulo256,
and gives synchronous reset then clear priority. Its descending port ranges are
`step[4:1]` and `count[8:1]`; the lowest label has integer weight1.

The supplied RTL and independent bench were executed on JarvisLabs on2026-09-16:
0 mismatches /4161 observations, including every step value, wrap, hold, reset and
clear. OpenChip also passed three20000-cycle simulations, generic synthesis and
bounded formal depth20. The checker rejected controls that ignored clear or
shifted the step value incorrectly. Bounded checking is not an unbounded proof;
no timing closure or silicon validation is claimed.

Run with Icarus Verilog:

```sh
iverilog -g2012 -s tb -o sim.vvp RangeCounter.v tb.v
vvp sim.vvp
```

Generated using OpenCode Go `glm-5.3-flash` (provider revision unknown), source
`d6137ccbc`. Original run `20260916-151724-1bf382`. Internal archive SHA256 is
recorded in project status. No API key is needed to run the delivered RTL bench.
