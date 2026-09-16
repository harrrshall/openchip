module TopModule (
    input  wire clk,
    input  wire areset,
    input  wire bump_left,
    input  wire bump_right,
    input  wire ground,
    input  wire dig,
    output wire walk_left,
    output wire walk_right,
    output wire aaah,
    output wire digging
);

    // State encoding
    localparam WALK_L = 3'd0;
    localparam WALK_R = 3'd1;
    localparam FALL_L = 3'd2;
    localparam FALL_R = 3'd3;
    localparam DIG_L  = 3'd4;
    localparam DIG_R  = 3'd5;

    reg [2:0] state;
    reg [2:0] next_state;

    // Next-state logic (combinational)
    always @* begin
        case (state)
            WALK_L: begin
                if (!ground)
                    next_state = FALL_L;
                else if (dig)
                    next_state = DIG_L;
                else if (bump_left)
                    next_state = WALK_R;
                else
                    next_state = WALK_L;
            end
            WALK_R: begin
                if (!ground)
                    next_state = FALL_R;
                else if (dig)
                    next_state = DIG_R;
                else if (bump_right)
                    next_state = WALK_L;
                else
                    next_state = WALK_R;
            end
            FALL_L: begin
                if (ground)
                    next_state = WALK_L;
                else
                    next_state = FALL_L;
            end
            FALL_R: begin
                if (ground)
                    next_state = WALK_R;
                else
                    next_state = FALL_R;
            end
            DIG_L: begin
                if (!ground)
                    next_state = FALL_L;
                else
                    next_state = DIG_L;
            end
            DIG_R: begin
                if (!ground)
                    next_state = FALL_R;
                else
                    next_state = DIG_R;
            end
            default: next_state = WALK_L;
        endcase
    end

    // State register with asynchronous positive-edge-triggered reset
    always @(posedge clk or posedge areset) begin
        if (areset)
            state <= WALK_L;
        else
            state <= next_state;
    end

    // Moore outputs: combinational decode of the state register
    assign walk_left  = (state == WALK_L);
    assign walk_right = (state == WALK_R);
    assign aaah       = (state == FALL_L) || (state == FALL_R);
    assign digging    = (state == DIG_L)  || (state == DIG_R);

endmodule
