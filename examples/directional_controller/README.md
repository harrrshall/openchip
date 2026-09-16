# Walking, falling and digging controller

This generated six-state Moore controller remembers its walking direction while
falling or digging. Falling takes priority over digging, and digging takes
priority over direction changes. A bump selects the opposite named direction;
selecting the already active direction holds it. Simultaneous bumps switch
direction. `areset` asynchronously returns the controller to walking left.

The full public specification is in `request.txt` (NVlabs VerilogEval v2,
`Prob152_lemmings3`, MIT). This example retains the requested `TopModule` name.

Run the independent directed bench with Icarus Verilog:

```sh
iverilog -g2012 -s tb -o /tmp/openchip-directional.vvp examples/directional_controller/TopModule.v examples/directional_controller/tb.v
vvp /tmp/openchip-directional.vvp
```

Expected: `STATE_RESULT mismatches=0 samples=384`. The bench exits nonzero on a
mismatch. It reaches each state through external inputs, exercises every control
combination, checks asynchronous reset, and checks remembered direction after
falling and landing. No internal state is forced.

Measured on JarvisLabs, 2026-09-16, run
`verilogeval-v2-agent-glm-5.3-flash-20260916-164020`: accepted nonprovisionally;
443/443 independent benchmark observations; 384/384 directed observations;
three seeds × 20000 simulation cycles; generic synthesis; request-derived formal
checker bounded pass at depth 20. The independent request check covered 784
observations across 96 transition cases. Runtime model: `glm-5.3-flash`, revision
unknown. The bench also rejected a retained wrong controller with 4/384 mismatches
and exit 1. Evidence archive SHA256:
`f6e7e0c78ff324524956e0be154e60e782a5b6ab1269a59cd86b17d183341223`.

OpenChip recognizes this complete request for an independent reference check and
formal checker. That recognition allows whitespace and module-name changes; it
is not a general natural-language FSM parser. Additional behavior falls outside
that grammar, and partial revisions require a complete updated specification.
Bounded verification is not unbounded proof, timing closure, or silicon validation.
