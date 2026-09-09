module prio_enc(input [7:0] req, output reg [2:0] idx, output valid);
  assign valid = |req;
  integer i;
  always @* begin
    idx = 3'd0;
    for (i = 0; i < 8; i = i + 1) if (req[i]) idx = i[2:0];
  end
endmodule
