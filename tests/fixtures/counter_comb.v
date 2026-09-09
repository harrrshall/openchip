// Correct counter written with a combinational next-state block. With inputs initialised to 0 and
// never toggling, Icarus does not evaluate `always @*` at time 0 and `nxt` stays X: the harness must
// not report that as a design failure.
module updown_counter(input clk, input rst, input en, input up, input load, input [7:0] load_val, output reg [7:0] count);
  reg [7:0] nxt;
  always @* begin
    nxt = count;
    if (load) nxt = load_val;
    else if (en) nxt = up ? count + 8'd1 : count - 8'd1;
  end
  always @(posedge clk) begin
    if (rst) count <= 8'd0;
    else count <= nxt;
  end
endmodule
