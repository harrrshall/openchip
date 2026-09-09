module updown_counter(input clk, input rst, input en, input up, input load, input [7:0] load_val, output reg [7:0] count);
  always @(posedge clk) begin
    if (rst) count <= 8'd0;
    else if (en) count <= up ? count + 8'd1 : count - 8'd1;   // BUG: en has priority over load
    else if (load) count <= load_val;
  end
endmodule
