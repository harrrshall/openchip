# Three-byte packet framer

Consumes a continuous byte stream. A byte with bit 3 set starts a packet; exactly
two subsequent bytes complete it, regardless of their marker bits. `done` pulses
after the third edge. The following byte can immediately start another packet.
Synchronous `reset` discards a partial packet and clears `done`.

The full public specification is in `request.txt` (NVlabs VerilogEval v2,
`Prob128_fsm_ps2`, MIT). The generated module retains the name `TopModule`.

Run the independent bench with Icarus Verilog:

```sh
iverilog -g2012 -s tb -o /tmp/openchip-packet.vvp examples/ps2_framer/TopModule.v examples/ps2_framer/tb.v
vvp /tmp/openchip-packet.vvp
```

Expected: `PACKET_RESULT mismatches=0 samples=122880`. Mismatches exit nonzero.
The bench exercises every twelve-byte marker pattern, continuous packets,
unrelated byte bits, and synchronous reset before and after clock edges.

Measured on JarvisLabs, 2026-09-16, run
`verilogeval-v2-agent-glm-5.3-flash-20260916-165830`: accepted nonprovisionally;
400/400 independent benchmark observations; 122880/122880 directed observations;
three seeds × 20000 simulation cycles; generic synthesis; request-derived formal
bounded pass at depth 20. The independent reference check passed 3584 observations
and rejected both retained designs that dropped or reused a byte. Runtime model:
`glm-5.3-flash`, revision unknown. Evidence archive SHA256:
`3ede05278c7e8ef56999b9cc6d08c4d406b675195fcb1083e5bad7aabbad4fe7`.

Independent request checking recognizes only this complete specification, allowing
whitespace and module-name changes. Additional behavior is outside this grammar;
partial revisions require a complete updated specification. This is not a general
natural-language parser. Bounded verification is not timing or silicon validation.
