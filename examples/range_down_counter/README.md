# Variable-step down counter

`RangeCounter` subtracts unsigned `step` when enabled, wrapping modulo 256.
Synchronous reset has priority over clear, and clear over subtraction. With enable
low it holds. Descending packed ports are `step[4:1]` and `count[8:1]`.

This is an actual browser-requested revision of the addition counter. On JarvisLabs,
run `20260916-172819-e8b9e8` delivered contract v2, accepted nonprovisionally:
4161/4161 independent observations, three seeds × 20000 simulation cycles,
generic synthesis, and bounded formal depth20. All four earlier registered
artifacts retained their original hashes. Runtime: OpenCode Go `glm-5.3-flash`,
revision unknown. No timing closure or silicon validation is claimed.

Run the supplied independent bench from this directory:

```sh
iverilog -g2012 -s tb -o /tmp/openchip-down-counter.vvp RangeCounter.v tb.v
vvp /tmp/openchip-down-counter.vvp
```

Expected: `RANGE_COUNTER_RESULT mismatches=0 samples=4161`; mismatches exit nonzero.
The bench exercises all step values, wrap, hold, reset and clear. A wrong addition
control failed3776/4161 observations and was also rejected by bounded formal.
Evidence archive SHA256:
`a97711ea6cb94adab69b0265bfde1097f3424ba36936ca5442d442ebd906d9f5`.
