# Karnaugh map with nonzero bit labels

Implements the supplied map on input `x[4:1]`, preserving its printed labels.
The bench enumerates all16 input values and checks the nine specified cells;
the seven don't-care cells remain unconstrained.

```sh
iverilog -g2012 -s tb -o /tmp/openchip-offset-kmap.vvp TopModule.v tb.v
vvp /tmp/openchip-offset-kmap.vvp
```

Expected: `KMAP_RESULT mismatches=0 care_samples=9 stimuli=16`.
Measured JarvisLabs run `verilogeval-v2-agent-glm-5.3-flash-20260916-191822`:
100/100 benchmark observations,9/9 independent care cells for source and emitted
netlist,three seeds ×20000 cycles for each, and generic synthesis. Accepted
nonprovisionally,7model calls,31593tokens,82.1/360active seconds. Formal was not
run for this combinational block. The intake correction records that the model
proposed lower index0 and the complete public table required1; raw response and
review are retained. The old wrong design failed7/9carecells; reversed bits
failed6/9. Full-table binding cannot be skipped because contract labels disagree.
No unbounded-proof, timing-closure or silicon claim. Evidence archive SHA256:
`b0caf02b42e8fc2290e9906887b5cb5c2d3984ca6616a2310dbc6435726aca56`.
