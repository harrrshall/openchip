# Four-stage shift register

One input bit advances on each positive clock edge and reaches `out` after the
fourth edge. `resetn` is an active-low synchronous reset to zero; asserting it
between edges does not immediately change the output.

Run from this directory:

```sh
iverilog -g2012 -s tb -o /tmp/openchip-shift.vvp TopModule.v tb.v
vvp /tmp/openchip-shift.vvp
```

Expected `SHIFT_RESULT mismatches=0 samples=6144`; mismatches exit nonzero.
Measured on JarvisLabs, run `verilogeval-v2-agent-glm-5.3-flash-20260916-174151`:
accepted nonprovisionally,299/299 benchmark observations,6144/6144 independent
observations, three seeds ×20000 simulation cycles, synthesis, bounded formal20.
Wrong-polarity, wrong-depth and asynchronous-reset controls failed the directed
bench; wrong polarity and depth also failed formal. Model revision unknown.
Evidence SHA256:
`7e5bbea46ca6c2a2f50eee0da587ce9ac028ab3109fe0889d4927802c4a20c5d`.
No unbounded-proof, timing-closure or silicon claim.
