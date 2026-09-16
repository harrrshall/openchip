module event_counter (
    input        clk,
    input        reset_n,
    input        clear,
    input        enable,
    output reg [7:0] q
);

    always @(posedge clk or negedge reset_n) begin
        if (!reset_n) begin
            q <= 8'd0;
        end else if (clear) begin
            q <= 8'd0;
        end else if (enable) begin
            if (q != 8'd255)
                q <= q + 8'd1;
            else
                q <= 8'd255;
        end else begin
            q <= q;
        end
    end

endmodule
