# Reloadable countdown timer

Load a ten-bit duration at any positive clock edge. Otherwise the counter
decrements to zero and stays there; `tc` reflects whether the current count is
zero. Reloading while counting replaces the remaining duration. There is no reset:
load a known value before relying on the output.

The supplied RTL passed1063935/1063935 independent observations on JarvisLabs,
including every duration0–1023, expiration, zero hold, reload and both sides of
the clock edge. It also passed three seeds ×20000 cycles, generic synthesis and
bounded formal depth20. A retained wrong registered-`tc` design failed4104/1063935.

```sh
iverilog -g2012 -s tb -o /tmp/openchip-countdown.vvp TopModule.v tb.v
vvp /tmp/openchip-countdown.vvp
```

Run from this directory. Expected `TIMER_RESULT mismatches=0 samples=1063935`;
mismatches exit nonzero. No model/API key is required to run the delivered bench.

Recovered run `20260916-172433-a1c853`, OpenCode Go `glm-5.3-flash`, revision unknown.
The original repair response was truncated. Recovery used one additional call
within its original360-second budget:126.2 active seconds,10 calls total.
Evidence SHA256:
`f6cddb092b85abdf70e6c983e853ea697a91424c419b727947588850549798b4`.
Bounded checking is not unbounded proof, timing closure, or silicon validation.
