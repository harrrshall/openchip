# HDLC bit framer

Consumes one bit on each positive clock edge. A zero after exactly five ones
pulses `disc`; a zero after six ones pulses `flag`; seven or more consecutive
ones assert `err`. Outputs last the following full cycle. Reset is synchronous
active-high and behaves as if the preceding bit were zero.

```sh
iverilog -g2012 -s tb -o /tmp/openchip-hdlc.vvp TopModule.v tb.v
vvp /tmp/openchip-hdlc.vvp
```

Expected `HDLC_RESULT mismatches=0 samples=123588`. Measured on JarvisLabs fresh
run `verilogeval-v2-agent-glm-5.3-flash-20260916-181125`: accepted nonprovisionally,
801/801 benchmark observations,123588/123588 independent directed observations,
three seeds ×20000 simulation cycles, synthesis and bounded formal20. The agent
repaired a state-constant width error within its original360-second budget.
Independent wrong-threshold, sticky-pulse and delayed-output controls failed
simulation and formal. The request recognizer supports the complete standard
framing specification with module-name/whitespace variations, not arbitrary
HDLC extensions. Evidence SHA256:
`3751a211f9e71172c70eaf3fa955ce56ffb7c74e32185fd3efc5996d8f8a71c2`.
No unbounded-proof, timing-closure or silicon claim.
