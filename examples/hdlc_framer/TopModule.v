module TopModule (
    input  wire clk,
    input  wire reset,
    input  wire in,
    output wire disc,
    output wire flag,
    output wire err
);

    // State encoding (4 bits wide to hold all 10 states without truncation)
    localparam S0   = 4'd0;  // previous input effectively 0 (reset state)
    localparam S1   = 4'd1;  // exactly 1 consecutive 1
    localparam S2   = 4'd2;  // exactly 2 consecutive 1s
    localparam S3   = 4'd3;  // exactly 3 consecutive 1s
    localparam S4   = 4'd4;  // exactly 4 consecutive 1s
    localparam S5   = 4'd5;  // exactly 5 consecutive 1s
    localparam DISC = 4'd6;  // 0 following exactly 5 ones (stuffed zero)
    localparam S6   = 4'd7;  // exactly 6 consecutive 1s
    localparam FLAG = 4'd8;  // 0 following exactly 6 ones (flag 01111110)
    localparam S7P  = 4'd9;  // 7 or more consecutive 1s

    reg [3:0] state;

    // State transition (synchronous active-high reset)
    always @(posedge clk) begin
        if (reset) begin
            state <= S0;
        end else begin
            case (state)
                S0:   state <= in ? S1   : S0;
                S1:   state <= in ? S2   : S0;
                S2:   state <= in ? S3   : S0;
                S3:   state <= in ? S4   : S0;
                S4:   state <= in ? S5   : S0;
                S5:   state <= in ? S6   : DISC;
                DISC: state <= in ? S1   : S0;
                S6:   state <= in ? S7P  : FLAG;
                FLAG: state <= in ? S1   : S0;
                S7P:  state <= in ? S7P  : S0;
                default: state <= S0;
            endcase
        end
    end

    // Moore outputs: combinational decodes of the registered state
    assign disc = (state == DISC);
    assign flag = (state == FLAG);
    assign err  = (state == S7P);

endmodule
