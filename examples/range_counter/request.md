Implement module RangeCounter. Ports: input clk, input reset, input clear,
input enable, input [4:1] step, output reg [8:1] count. Preserve these descending
packed ranges. All single-bit controls are active high. At each positive clk edge,
synchronous reset has first priority and clears count to zero. Otherwise clear
clears count to zero regardless of enable or step. Otherwise if enable is high,
add the unsigned packed value of step to count, wrapping modulo 256. If enable is
low, hold count. count is registered, with no combinational path from inputs.
The lower index is a label, not padding: step[1] has weight 1 and step[4] weight8;
count[1] has weight1 and count[8] weight128. No additional ports or state outputs.
