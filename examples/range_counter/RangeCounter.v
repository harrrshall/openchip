module RangeCounter (
    input clk,
    input reset,
    input clear,
    input enable,
    input [4:1] step,
    output reg [8:1] count
);

always @(posedge clk) begin
    if (reset)
        count <= 8'b0;
    else if (clear)
        count <= 8'b0;
    else if (enable)
        count <= count + {4'b0, step};
    else
        count <= count;
end

endmodule
