module TopModule (
    input        clk,
    input        load,
    input  [9:0] data,
    output reg   tc
);

    reg [9:0] count;
    reg [9:0] next_count;

    always @(posedge clk) begin
        if (load)
            count <= data;
        else if (count != 10'd0)
            count <= count - 10'd1;

        next_count = load ? data :
                     (count != 10'd0) ? (count - 10'd1) : 10'd0;
        tc <= (next_count == 10'd0);
    end

endmodule
