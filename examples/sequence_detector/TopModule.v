module TopModule (
    input  clk,
    input  reset,
    input  data,
    output reg start_shifting
);

    localparam [2:0] S0         = 3'd0; // no progress
    localparam [2:0] S1         = 3'd1; // seen '1'
    localparam [2:0] S11        = 3'd2; // seen '11'
    localparam [2:0] S110       = 3'd3; // seen '110'
    localparam [2:0] S1101_DONE = 3'd4; // match latched

    reg [2:0] state;

    always @(posedge clk) begin
        if (reset) begin
            state <= S0;
        end else begin
            case (state)
                S0:         state <= data ? S1         : S0;
                S1:         state <= data ? S11        : S0;
                S11:        state <= data ? S11        : S110;
                S110:       state <= data ? S1101_DONE : S0;
                S1101_DONE: state <= S1101_DONE;
                default:    state <= S0;
            endcase
        end
    end

    always @(*) begin
        start_shifting = (state == S1101_DONE);
    end

endmodule
