# UART 8N1 transmitter

Generated from [the explicit timing request](request.md), with synchronous reset,
latched byte data, start/busy/done signals, and configurable clock periods per bit.

The delivered RTL passed independent checks for all 256 byte values at divisors 4
and 7: 10811/10811 and 18530/18530 checked cycles, including start/data changes while
busy, completion pulses, and reset interruption. The pipeline accepted the design
non-provisionally, including bounded formal depth 20. Exact provenance and limits
are in [verification.json](verification.json). This does not establish timing
closure or correctness for every possible parameter and environment.

Run the included independent bench with Icarus Verilog:

```sh
iverilog -g2012 -s tb -Ptb.D=4 -o /tmp/uart-d4.vvp uart_tx8n1.v tb.v
vvp /tmp/uart-d4.vvp
iverilog -g2012 -s tb -Ptb.D=7 -o /tmp/uart-d7.vvp uart_tx8n1.v tb.v
vvp /tmp/uart-d7.vvp
```

A passing run prints `mismatches=0`. The testbench is a separate check of the
request and was not supplied to the generating model. The measured design is
in [uart_tx8n1.v](uart_tx8n1.v); this example is not a claim about every OpenChip run.
