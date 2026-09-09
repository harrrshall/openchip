module updown_counter(input clk, input rst, input en, input up, input load, input [7:0] load_val, output reg [7:0] count);
  always @(posedge clk) begin
    if (rst) count <= 8'd0
    else count <= count + 1;
  end
endmodule
