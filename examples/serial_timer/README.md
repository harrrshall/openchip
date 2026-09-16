# Serially programmed timer

`TopModule.v` detects `1101`, captures the next four bits MSB first, counts for
exactly `(delay + 1) * 1000` clock periods, then holds `done` until acknowledgment.
It ignores serial data while counting or waiting for acknowledgment. Reset is
synchronous and active high. The module name is `TopModule`, as in the request.

These are the exact generated RTL and independent bench executed on JarvisLabs.
The bench checked all 16 delay values, full countdowns, remaining-count boundaries,
ignored inputs while counting, held completion, acknowledgment and restart:
**0 mismatches across 136193 observations**. It detects the earlier acknowledgment
bug (16 mismatches). The pipeline additionally passed three seeds of 20000 cycles,
generic synthesis and bounded formal depth 20. The generated checker rejected a
retained design that captured the wrong payload. These are bounded measurements,
not exhaustive correctness, timing closure or silicon validation.

The initial build stalled on a provider HTTP 500. An explicit `openchip resume`
completed the delivery within the original 600-second accumulated budget; the
initial failed attempt is retained. `provenance.json` records hashes and the model
configuration. Production model settings were not changed by this experiment.

With Icarus Verilog installed:

```sh
iverilog -g2012 -s tb -o sim.vvp TopModule.v tb.v
vvp sim.vvp
```

The final line reports `SERIAL_TIMER_RESULT mismatches=0 samples=136193 ack_mismatches=0`.
For a new OpenChip build of this request, configure enough simulation cycles to
exercise full transactions: `[verification] sim_cycles = 20000` was used here.
