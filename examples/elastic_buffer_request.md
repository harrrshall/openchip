Build Verilog-2001 module elastic_buffer, a two-stage elastic streaming buffer.
Ports: clk, rst, in_valid, out_ready are unsigned 1-bit inputs; in_data is an
unsigned 8-bit input; in_ready is a combinational 1-bit output; out_valid is a
registered 1-bit output; out_data is a registered unsigned 8-bit output.
Use exactly two meaningful leaf modules, named ingress_stage and egress_stage,
each implementing one single-entry elastic buffer. Use different module names
for these leaves. Both use the same clk and synchronous active-high rst directly.
No parameters, asynchronous reset or combinational bypass of stored data.

Each leaf has ports clk, rst, s_valid, s_data[7:0], s_ready, m_valid, m_data[7:0],
and m_ready. s_valid and m_ready are one-bit inputs; s_data is an 8-bit input;
s_ready is a combinational one-bit output; m_valid is a registered one-bit output;
m_data is an 8-bit registered output. All ports unsigned. Each stage has one valid
register V and one data register D. Continuously s_ready = !V || m_ready.
On posedge clk: if rst is high, set V=0 and D=0; else if s_ready is high, set
V=s_valid and, only if s_valid is high, set D=s_data. Otherwise D holds. If
s_ready is low, both registers hold. m_valid=V and m_data=D. Even while reset is
asserted between edges, ready still follows the combinational equation; valid and
data reset only at the clock edge.

Wire top in_valid/in_data into ingress s_valid/s_data and ingress s_ready to top
in_ready. Connect ingress m_valid/m_data to egress s_valid/s_data and egress s_ready
to ingress m_ready. Wire top out_ready to egress m_ready, and egress m_valid/m_data
to top out_valid/out_data. At a clock edge, both stages use pre-edge values.
An input transfer occurs when in_valid && in_ready; an output transfer occurs
when out_valid && out_ready. Support simultaneous transfers at one byte per cycle
once filled, preserve order, hold the output under stall, never drop or duplicate
bytes, and discard all buffered bytes on synchronous reset. A first accepted byte
reaches the output after the next clock edge (two registered stages, no bypass).
