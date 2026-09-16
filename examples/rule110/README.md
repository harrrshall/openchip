# 512-cell Rule 110 engine

`TopModule` holds a 512-bit state `q`. On a rising `clk` edge, `load=1` loads
`data`; otherwise all cells advance together. The neighbourhood is old
`{q[i+1], q[i], q[i-1]}`, with zero outside the array. The next cell is one for
neighbourhoods 001, 010, 011, 101 and 110, and zero for the other three.
There is no reset; load establishes a known state.

The complete OpenChip build was accepted non-provisionally, passed 6283/6283
independent VerilogEval observations, and passed bounded formal depth 20.
Two incorrect generated references were rejected against the public transition
table before the final two references agreed. This is a measured example,
not a guarantee for every generated design or proof of timing closure.

Run the separate public-equation bench with Icarus Verilog:

```sh
iverilog -g2012 -s tb -o /tmp/rule110.vvp TopModule.v tb.v
vvp /tmp/rule110.vvp
```

Provenance and the measured bench result are in `verification.json`.
