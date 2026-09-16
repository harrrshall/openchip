# Sticky sequence detector

Recognizes `1101` in a serial bit stream, including overlapping prefixes, and
keeps `start_shifting` high until the next synchronous active-high reset.

```sh
iverilog -g2012 -s tb -o /tmp/openchip-sequence.vvp TopModule.v tb.v
vvp /tmp/openchip-sequence.vvp
```

Expected: `SEQUENCE_RESULT mismatches=0 samples=139265 histories=4096`.
Measured on JarvisLabs run `verilogeval-v2-agent-glm-5.3-flash-20260916-190305`:
643/643 benchmark observations and139265/139265 independent observations;
three seeds ×20000 cycles each for source and synthesized netlist, generic
synthesis and bounded formal depth20 passed. Accepted nonprovisionally after
one ordinary RTL repair;9model calls,44612tokens,180.4/360active seconds.
The independent checker rejects one-cycle-late, wrong-reset and non-sticky
outputs. This is bounded functional evidence, not an unbounded proof or timing
closure. Evidence archive SHA256:
`517caa7ce81d48248e1546d74a3bc776786d17696a905d294746076cb3f419ed`.
