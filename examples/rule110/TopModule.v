module TopModule (
    input  clk,
    input  load,
    input  [511:0] data,
    output reg [511:0] q
);
    integer i;
    reg [511:0] next;

    always @* begin
        for (i = 0; i < 512; i = i + 1) begin
            next[i] = (~((i == 511) ? 1'b0 : q[i+1]) & ((i == 0) ? 1'b0 : q[i-1]))
                    | (q[i] & ~((i == 0) ? 1'b0 : q[i-1]))
                    | (~q[i] & ((i == 0) ? 1'b0 : q[i-1]));
        end
    end

    always @(posedge clk) begin
        if (load)
            q <= data;
        else
            q <= next;
    end

endmodule
