module updown_counter(input clk, input rst, input en, input up, input load, input [7:0] load_val, output reg [7:0] count);
  always @(posedge clk) begin
    if (load) count <= load_val;             // BUG: no reset -> X after reset
    else if (en) count <= up ? count + 8'd1 : count - 8'd1;
  end
endmodule
