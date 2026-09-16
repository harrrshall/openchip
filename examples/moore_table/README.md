# Moore transition table

Four-state synchronous FSM whose output is high only in state D. The request
specifies every next-state/output cell; OpenChip derives an independent reference
check and formal shadow from that complete table. The supported grammar allows
2–16 states, different transitions/output bits/reset states, and either reset
polarity. Additional prose or incomplete revisions are not silently inferred.

```sh
iverilog -g2012 -s tb -o /tmp/openchip-moore.vvp TopModule.v tb.v
vvp /tmp/openchip-moore.vvp
```

Expected `MOORE_RESULT mismatches=0 samples=5632`. Measured on JarvisLabs fresh
run `verilogeval-v2-agent-glm-5.3-flash-20260916-180723`: accepted nonprovisionally,
230/230 benchmark,5632/5632 directed observations, three seeds ×20000 simulation
cycles, synthesis and bounded formal20. Wrong output delay, input dependence,
transition and reset controls failed simulation and formal. A separate renamed
three-state active-low-reset variant passed the actual CLI verification flow.
Evidence SHA256:
`013d892369fcd860839e8cbf1eb176fcb7a9284f4d64738757b15377a690f607`.
No unbounded-proof, timing-closure or silicon claim.
